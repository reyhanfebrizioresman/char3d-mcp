"""Owned cinematic atmosphere. Only JSON persists; all scene overrides use finally.

World/light/camera datablocks are copied for a render. Original pointers, actions,
settings and user compositor are restored, so clear never has to guess old state.
"""
from contextlib import contextmanager
import json
import math

import bpy
from mathutils import Vector

from . import command
from ..cinematic import resolve, cost_factor as config_cost

CONFIG_PROP = 'char3d_cinematic_look'


def get_config(sc):
    return json.loads(sc[CONFIG_PROP]) if sc.get(CONFIG_PROP) else None


def cost_factor(sc, engine):
    return config_cost(get_config(sc), engine)


@command('cinematic_look')
def cinematic_look(preset='golden_hour', intensity=1., haze=None, god_rays=None, bloom=None,
                   dof='auto', particles=None, grade=None, sun=None, clear=False):
    cfg = resolve(preset, intensity, haze, god_rays, bloom, dof, particles, grade, sun, clear)
    sc = bpy.context.scene
    if cfg['preset'] == 'none':
        if CONFIG_PROP in sc:
            del sc[CONFIG_PROP]
    else:
        sc[CONFIG_PROP] = json.dumps(cfg)
    return {**cfg, 'look_cost_factor': cost_factor(sc, 'BLENDER_EEVEE'),
            'application': 'temporary lit-render overrides; originals preserved',
            'grade_order': 'look defaults, render_style grade overrides; single bloom/vignette pass',
            'cameras': [o.name for o in sc.objects if o.type == 'CAMERA' and o.get('c3d_shot')]}


def compositor_config(sc, style):
    """Merge looks once, preserving the original style path exactly when inactive."""
    cfg = get_config(sc)
    if not cfg or cfg['intensity'] == 0:
        return style
    k = cfg['intensity']
    grade = {key: (float(value)*k if key == 'teal_orange' else
                  (1 + (value-1)*k if key in ('contrast', 'saturation') else value*k))
             for key, value in cfg['grade'].items()}
    style = style if style and style['strength'] > 0 else None
    if style:
        s = style['strength']
        for key, value in style['grade'].items():
            grade[key] = float(value)*s if key == 'teal_orange' else (
                1+(value-1)*s if key in ('contrast', 'saturation') else value*s)
        if style['style'] == 'noir':
            # Noir's default monochrome must not inherit a color cast from the
            # atmospheric grade. Explicit style tint/temperature still wins.
            for key in ('temperature', 'tint', 'teal_orange'):
                if key not in style['grade']:
                    grade[key] = 0
    style_name = style['style'] if style else 'cinematic'
    weight = style['strength'] if style else 0
    effects = dict(bloom=max(cfg['bloom']*k, {'film': .08, 'animated_film': .08}.get(style_name, 0)*weight),
        vignette=max(grade.pop('vignette', .09*k), {'film': .17, 'noir': .24, 'vintage': .11}.get(style_name, 0)*weight),
        grain=max(grade.pop('grain', 0), (.008 if style_name == 'noir' else .004 if style_name in ('film', 'vintage') else 0)*weight),
        lifted_blacks=max(grade.pop('lifted_blacks', 0), .025*weight if style_name == 'vintage' else 0),
        chromatic_aberration=grade.pop('chromatic_aberration', 0))
    return dict(style=style_name, strength=1., grade=grade, effects=effects,
                letterbox=style['letterbox'] if style else 0)


# (energy gain on the look's base subject-light factor, tint amount toward the sun color)
_ROLE_GAINS = {
    'warm': {'key': (.8, .55), 'fill': (.35, 0), 'rim': (2.2, 1.)},
    'cool': {'key': (.8, 0), 'fill': (.4, 0), 'rim': (1.8, 0)},
    'neutral': {'key': (.85, .3), 'fill': (.4, 0), 'rim': (1.4, .5)},
}
_ROLES = {}


def _mood(preset):
    if preset in ('golden_hour', 'sunset', 'epic', 'dreamy'):
        return 'warm'
    return 'cool' if preset in ('night', 'blue_hour') else 'neutral'


def _cast(sc):
    """(eye-level center, standing height) of the visible characters, or None."""
    rigs = _rigs(sc, None)
    if not rigs:
        return None
    eyes = [_eye(rig) for rig in rigs]
    center = sum(eyes, Vector()) / len(eyes)
    floor = min(rig.matrix_world.translation.z for rig in rigs)
    return center, max(1.0, (center.z - floor) / .93)


def _classify_lights(sc, cast):
    """Front lights: brightest is key, others fill; lights behind the cast are rims."""
    _ROLES.clear()
    lights = [o for o in sc.objects if o.type == 'LIGHT' and o.get('c3d_role') == 'light'
              and o.data.type != 'SUN']
    front = []
    for obj in lights:
        if cast:
            offset = obj.matrix_world.translation - cast[0]
            offset.z = 0
            facing = -offset.normalized().y if offset.length > 1e-6 else 1
        else:
            facing = -1 if obj.name.endswith('_2') else 1
        if facing < -.25:
            _ROLES[obj.name] = 'rim'
        else:
            front.append(obj)
    for obj in front:
        _ROLES[obj.name] = 'fill'
    if front:
        _ROLES[max(front, key=lambda o: o.data.energy).name] = 'key'


def _light_role(obj, cast):
    return _ROLES.get(obj.name, 'key')


def _eye(rig):
    if rig.get('c3d_rig_type') == 'vrm':
        from .vrm_actor import face_sites
        sites = face_sites(rig)
        if sites:
            from .anim import semantic_map
            return rig.matrix_world @ rig.pose.bones[semantic_map(rig)['head']].matrix @ sites['eyes']
    from .gaze import head_frame
    center, orientation = head_frame(rig)
    # Anatomical front (not bone-local -Y), at the eye plane rather than neck.
    return center + orientation @ Vector((0, -.075, .025))


def _rigs(sc, names):
    from .anim import semantic_map
    found = []
    if not names:
        names = [o.name for o in sc.objects if o.type == 'ARMATURE' and not o.hide_render]
    for name in names:
        obj = sc.objects.get(name)
        if obj is None:
            continue
        rig = obj if obj.type == 'ARMATURE' else next((m.object for m in obj.modifiers if m.type == 'ARMATURE' and m.object), None)
        if rig and rig not in found and {'head', 'hips', 'thigh.L', 'thigh.R'} <= set(semantic_map(rig)):
            found.append(rig)
    return found


def _focus(sc, camera, objects, actions):
    """A bone-following eye target for singles; sampled speaker focus for two-shots."""
    from .anim import semantic_map
    meta = camera.get('c3d_shot')
    if not meta or ('c3d_dof_explicit' in camera and not camera['c3d_dof_explicit']) or camera.data.dof.use_dof:  # Explicit camera_shot DOF keeps its f-stop.
        return
    rigs = _rigs(sc, meta.get('subject'))
    if not rigs:
        return
    size = meta.get('shot_size', meta.get('shot', 'medium'))
    stops = dict(extreme_close_up=3.2, close_up=2.8, medium_close=3.2, medium=4.,
                 medium_full=5.6, full=8., wide=11., extreme_wide=16.)
    dof = camera.data.dof
    dof.use_dof = True
    strength = get_config(sc)['intensity']
    dof.aperture_fstop = 32 * (stops.get(size, 5.6)/32)**strength
    dof.aperture_blades = 7
    turns = json.loads(camera.get('c3d_focus_turns', '[]'))
    incoming = bpy.data.objects.get(camera.get('c3d_focus_from', ''))
    if len(rigs) == 1 and incoming is not None:
        # A listener insert keeps the speaker's audio. Its short optical rack
        # follows the editorial reaction, then stays on the listener's eyes.
        args = json.loads(camera.get('c3d_shot_args', '{}'))
        a, b = args.get('start_frame', sc.frame_start), args.get('end_frame', sc.frame_end)
        saved = sc.frame_current, sc.frame_subframe
        target = bpy.data.objects.new('__c3d_look_reaction', None)
        sc.collection.objects.link(target)
        objects.append(target)
        from .script_scene import _bones_only
        try:
            with _bones_only():
                for frame in range(a, b+1):
                    sc.frame_set(frame)
                    u = min(1., (frame-a)/max(1., .28*sc.render.fps/sc.render.fps_base))
                    u = u*u*(3-2*u)
                    target.location = _eye(incoming).lerp(_eye(rigs[0]), u)
                    target.keyframe_insert('location', frame=frame)
        finally:
            if target.animation_data and target.animation_data.action:
                actions.append(target.animation_data.action)
            sc.frame_set(saved[0], subframe=saved[1])
        dof.focus_object = target
    elif len(rigs) == 1 or not turns:
        rig = rigs[0]
        bone = semantic_map(rig)['head']
        anchor = bpy.data.objects.new('__c3d_look_head', None)
        sc.collection.objects.link(anchor)
        objects.append(anchor)
        follow = anchor.constraints.new('COPY_TRANSFORMS')
        follow.target, follow.subtarget = rig, bone
        target = bpy.data.objects.new('__c3d_look_eyes', None)
        sc.collection.objects.link(target)
        objects.append(target)
        target.parent = anchor
        if camera.get('c3d_foreground'):
            from .ots import eye_point
            eye = eye_point(rig)
        else:
            eye = _eye(rig)
        target.location = (rig.matrix_world @ rig.pose.bones[bone].matrix).inverted() @ eye
        dof.focus_object = target
    else:
        # Editorial cuts and two-shot coverage carry live speaker turns. Focus
        # starts four frames before speech, with a short, smooth rack on one camera.
        saved = sc.frame_current, sc.frame_subframe
        target = bpy.data.objects.new('__c3d_look_speaker', None)
        sc.collection.objects.link(target)
        objects.append(target)
        from .script_scene import _bones_only
        try:
            with _bones_only():
                _sample_focus(sc, target, turns, rigs)
        finally:
            if target.animation_data and target.animation_data.action:
                actions.append(target.animation_data.action)
            sc.frame_set(saved[0], subframe=saved[1])
        dof.focus_object = target


def _sample_focus(sc, target, turns, rigs):
    for frame in range(sc.frame_start, sc.frame_end+1):
        sc.frame_set(frame)
        turn = next((t for t in reversed(turns) if frame >= t['start']-4), None)
        active = turn['speaker'] if turn else rigs[0].name
        who = next((r for r in rigs if r.name == active), rigs[0])
        target.location = _eye(who)
        if turn and turns.index(turn) > 0:
            previous = turns[turns.index(turn)-1]['speaker']
            other = next((r for r in rigs if r.name == previous), rigs[0])
            u = min(1., max(0., (frame-turn['start']+4)/6))
            target.location = _eye(other).lerp(_eye(who), u*u*(3-2*u))
        target.keyframe_insert('location', frame=frame)


def _near_bounds():
    from .weather import _bounds
    from .script_scene import _bones_only
    # Frusta depend on cameras and skeletons only; do not reskin every MPFB mesh
    # dozens of times just to sample camera coverage across the timeline.
    with _bones_only():
        return _bounds()


def _world(sc, cfg, outdoors, worlds):
    old = sc.world
    world = old.copy() if old else bpy.data.worlds.new('__c3d_look_world')
    worlds.append(world)
    sc.world = world
    world.use_nodes = True
    if not outdoors:
        # Keep indoor world graphs and practical ambience. No indoor sun.
        return
    nodes, links = world.node_tree.nodes, world.node_tree.links
    original = next((n for n in nodes if n.type == 'OUTPUT_WORLD' and n.is_active_output), None)
    out = nodes.new('ShaderNodeOutputWorld')
    out.is_active_output = True
    sky = nodes.new('ShaderNodeTexSky')
    enums = sky.bl_rna.properties['sky_type'].enum_items.keys()
    sky.sky_type = 'SINGLE_SCATTERING' if 'SINGLE_SCATTERING' in enums else 'NISHITA'
    sky.sun_elevation = math.radians(max(-18, cfg['elevation']))
    # Sky Texture azimuth is from +X; public convention is from -Y toward +X.
    sky.sun_rotation = math.radians(cfg['azimuth']-90)
    sky.sun_disc = True
    sky.sun_size = math.radians(.8)
    sky.altitude = .1
    sky.air_density = 1.1
    if hasattr(sky, 'dust_density'):
        sky.dust_density = 2.4 if cfg['preset'] in ('golden_hour', 'sunset') else 1.2
    elif hasattr(sky, 'aerosol_density'):
        sky.aerosol_density = 2.4 if cfg['preset'] in ('golden_hour', 'sunset') else 1.2
    tint = nodes.new('ShaderNodeMixRGB')
    tint.blend_type = 'MULTIPLY'
    tint.inputs[0].default_value = 1
    tint.inputs[2].default_value = (*cfg['sky_tint'], 1)
    links.new(sky.outputs[0], tint.inputs[1])
    bg = nodes.new('ShaderNodeBackground')
    weather = sc.get('c3d_weather_kind', 'clear')
    cloud = sc.get('c3d_weather_intensity', 0) if weather in ('rain', 'snow', 'fog') else 0
    bg.inputs['Strength'].default_value = cfg['sky_strength'] * (1-.5*cloud)
    links.new(tint.outputs[0], bg.inputs['Color'])
    surface = bg.outputs[0]
    palettes = {
        'night': ((.045, .075, .18), (.005, .012, .045), .35),
        'blue_hour': ((.065, .11, .27), (.012, .028, .11), .65),
        'golden_hour': ((.95, .60, .28), (.26, .38, .60), .42),
        'sunset': ((.70, .24, .20), (.14, .045, .28), .45),
        'dreamy': ((.62, .43, .42), (.23, .25, .45), .40),
        'misty_morning': ((.50, .58, .62), (.22, .32, .43), .30),
        'overcast_soft': ((.50, .54, .58), (.28, .34, .40), .30),
        'epic': ((.32, .28, .22), (.05, .11, .22), .20),
    }
    if cfg['preset'] in palettes:
        # Art-directed atmospheric fill sits under the physical solar sky, so
        # sunset keeps a rose/violet upper sky rather than a muddy brown tint.
        # Below the solar horizon the same hemisphere supplies dim night airglow.
        horizon, zenith, power = palettes[cfg['preset']]
        coord = nodes.new('ShaderNodeTexCoord')
        xyz = nodes.new('ShaderNodeSeparateXYZ')
        links.new(coord.outputs['Normal'], xyz.inputs[0])
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0
        ramp.color_ramp.elements[0].color = (*horizon, 1)
        ramp.color_ramp.elements[1].position = .65
        ramp.color_ramp.elements[1].color = (*zenith, 1)
        if cfg['preset'] == 'sunset':
            rose = ramp.color_ramp.elements.new(.18)
            rose.color = (.50, .16, .34, 1)
        links.new(xyz.outputs['Z'], ramp.inputs[0])
        air = nodes.new('ShaderNodeBackground')
        air.inputs['Strength'].default_value = power*(1-.5*cloud)
        links.new(ramp.outputs[0], air.inputs['Color'])
        add = nodes.new('ShaderNodeAddShader')
        links.new(surface, add.inputs[0])
        links.new(air.outputs[0], add.inputs[1])
        surface = add.outputs[0]
    source = original.inputs['Surface'].links[0].from_socket if original and original.inputs['Surface'].is_linked else None
    if source and cfg['intensity'] < 1:
        blend = nodes.new('ShaderNodeMixShader')
        blend.inputs[0].default_value = cfg['intensity']
        links.new(source, blend.inputs[1])
        links.new(surface, blend.inputs[2])
        links.new(blend.outputs[0], out.inputs['Surface'])
    else:
        links.new(surface, out.inputs['Surface'])
    if original and original.inputs['Volume'].is_linked:
        links.new(original.inputs['Volume'].links[0].from_socket, out.inputs['Volume'])


def _volume(sc, cfg, outdoors, objects, meshes, materials):
    from .anim import semantic_map
    stage = any(o.get('c3d_environment_preset') == 'stage' for o in sc.objects)
    density = cfg['haze'] * cfg['intensity']
    # Weather already owns the fog: share it, never stack two scattering volumes.
    if density == 0 or sc.get('c3d_weather_kind') == 'fog':
        return
    low, high = _near_bounds()
    if outdoors:
        low.z = min(low.z, -.2)
        high.z = min(high.z, 16)
    else:
        # Sets are open for filming. Keep their haze localized to the room.
        root = next((o for o in sc.objects if o.get('c3d_environment_preset')), None)
        origin = root.matrix_world.translation if root else Vector((0, 0, 0))
        unit = abs(root.scale.x) if root else 1.
        low.z, high.z = origin.z-.1*unit, origin.z+4.5*unit
        low.x, low.y = max(low.x, origin.x-12*unit), max(low.y, origin.y-10*unit)
        high.x, high.y = min(high.x, origin.x+12*unit), min(high.y, origin.y+10*unit)
        density *= .85 if stage else .6
    verts = [(x, y, z) for z in (low.z, high.z) for y in (low.y, high.y) for x in (low.x, high.x)]
    mesh = bpy.data.meshes.new('__c3d_look_volume')
    meshes.append(mesh)
    mesh.from_pydata(verts, [], [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)])
    obj = bpy.data.objects.new('__c3d_look_haze', mesh)
    obj['c3d_role'] = 'cinematic'
    sc.collection.objects.link(obj)
    objects.append(obj)
    mat = bpy.data.materials.new('__c3d_look_haze')
    materials.append(mat)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.remove(nodes.get('Principled BSDF'))
    scatter = nodes.new('ShaderNodeVolumeScatter')
    scatter.inputs['Color'].default_value = (1, .80, .55, 1) if cfg['preset'] in ('golden_hour', 'sunset') else (.78, .87, 1, 1)
    scatter.inputs['Anisotropy'].default_value = .15 if stage else .25 + .35*cfg['rays']
    value = None
    for rig in [o for o in sc.objects if o.type == 'ARMATURE' and not o.hide_render]:
        try:
            head = semantic_map(rig)['head']
        except (KeyError, ValueError):
            continue  # Non-humanoid props can also have armatures.
        clear_zone = bpy.data.objects.new('__c3d_look_clear_face', None)
        sc.collection.objects.link(clear_zone)
        objects.append(clear_zone)
        follow = clear_zone.constraints.new('COPY_LOCATION')
        follow.target, follow.subtarget, follow.head_tail = rig, head, .5
        coord = nodes.new('ShaderNodeTexCoord')
        coord.object = clear_zone
        distance = nodes.new('ShaderNodeVectorMath')
        distance.operation = 'LENGTH'
        links.new(coord.outputs['Object'], distance.inputs[0])
        falloff = nodes.new('ShaderNodeMapRange')
        falloff.interpolation_type = 'SMOOTHERSTEP'
        falloff.inputs['From Min'].default_value = .45 if stage else 1.2
        falloff.inputs['From Max'].default_value = 1.6 if stage else 4.
        falloff.inputs['To Min'].default_value = .08
        falloff.inputs['To Max'].default_value = 1
        links.new(distance.outputs['Value'], falloff.inputs['Value'])
        if value is None:
            value = falloff.outputs[0]
        else:
            multiply = nodes.new('ShaderNodeMath')
            multiply.operation = 'MULTIPLY'
            links.new(value, multiply.inputs[0])
            links.new(falloff.outputs[0], multiply.inputs[1])
            value = multiply.outputs[0]
    if cfg['preset'] == 'misty_morning':
        geometry = nodes.new('ShaderNodeNewGeometry')
        xyz = nodes.new('ShaderNodeSeparateXYZ')
        links.new(geometry.outputs['Position'], xyz.inputs[0])
        height = nodes.new('ShaderNodeMapRange')
        height.inputs['From Min'].default_value = .2
        height.inputs['From Max'].default_value = 4
        height.inputs['To Min'].default_value = 1.5
        height.inputs['To Max'].default_value = .25
        links.new(xyz.outputs['Z'], height.inputs[0])
        if value:
            multiply = nodes.new('ShaderNodeMath')
            multiply.operation = 'MULTIPLY'
            links.new(value, multiply.inputs[0])
            links.new(height.outputs[0], multiply.inputs[1])
            value = multiply.outputs[0]
        else:
            value = height.outputs[0]
    if value:
        gain = nodes.new('ShaderNodeMath')
        gain.operation = 'MULTIPLY'
        gain.inputs[1].default_value = density
        links.new(value, gain.inputs[0])
        links.new(gain.outputs[0], scatter.inputs['Density'])
    else:
        scatter.inputs['Density'].default_value = density
    links.new(scatter.outputs[0], nodes.get('Material Output').inputs['Volume'])
    mesh.materials.append(mat)


def _particles(sc, cfg, objects, meshes, materials, groups):
    # Reuse the weather frustum/Scene Time wrapping graph, without weather ownership.
    from .weather import _particles as weather_particles
    options = cfg['particles']
    if options['kind'] == 'none' or options['count'] == 0:
        return
    low, high = _particle_bounds(sc)
    rise = {'dust': .94, 'pollen': 1.08, 'petals': .45, 'embers': 1.8}[options['kind']]
    pools = [(bpy.data.objects, objects), (bpy.data.meshes, meshes),
             (bpy.data.materials, materials), (bpy.data.node_groups, groups)]
    before = [set(pool) for pool, _ in pools]
    try:
        obj, _ = weather_particles(sc.collection, 'snow', .1, (.06, .015, rise), options['seed'], low, high)
    finally:
        # The shared builder can fail part-way through node construction. Own
        # every allocation even then, while preserving pre-existing weather IDs.
        for (pool, owned), existing in zip(pools, before):
            owned.extend(item for item in pool if item not in existing)
    obj.name = '__c3d_look_particles'
    group = obj.modifiers[0].node_group
    nodes = group.nodes
    mat = next(n for n in nodes if n.bl_idname == 'GeometryNodeSetMaterial').inputs['Material'].default_value
    line = next(n for n in nodes if n.bl_idname == 'GeometryNodeMeshLine')
    line.inputs['Count'].default_value = max(1, round(options['count'] * cfg['intensity']))
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    colors = dict(dust=(1, .87, .56), pollen=(.92, 1, .59), petals=(1, .50, .66), embers=(1, .23, .025))
    color = (*colors[options['kind']], 1)
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Emission Color'].default_value = color
    bsdf.inputs['Emission Strength'].default_value = 2 if options['kind'] == 'embers' else .4
    instance = next(n for n in nodes if n.bl_idname == 'GeometryNodeInstanceOnPoints')
    instance.inputs['Scale'].default_value = (.018, .009, .003) if options['kind'] == 'petals' else (.006,)*3
    for item in (obj, obj.data, group, mat):
        if 'c3d_weather' in item:
            del item['c3d_weather']
    obj['c3d_role'] = 'cinematic'


def _particle_bounds(sc):
    """A short (1..8 m) camera volume keeps sparse motes visible and cheap."""
    from .script_scene import _bones_only
    saved = sc.frame_current, sc.frame_subframe
    points = []
    try:
        with _bones_only():
            cameras = [o for o in sc.objects if o.type == 'CAMERA' and not o.name.startswith('__')]
            for camera in cameras:
                frames = {sc.frame_start, sc.frame_end}
                if camera.animation_data:
                    frames.update(range(sc.frame_start, sc.frame_end+1, max(1, (sc.frame_end-sc.frame_start)//8)))
                for frame in sorted(frames):
                    sc.frame_set(frame)
                    mw = camera.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
                    for depth in (1, 8):
                        points.extend(mw @ (v*(depth/abs(v.z))) for v in camera.data.view_frame(scene=sc))
    finally:
        sc.frame_set(saved[0], subframe=saved[1])
    if not points:
        return Vector((-3, -3, .1)), Vector((3, 3, 4))
    return (Vector((min(p.x for p in points), min(p.y for p in points), max(.1, min(p.z for p in points)))),
            Vector((max(p.x for p in points), max(p.y for p in points), max(3., max(p.z for p in points)))))


@contextmanager
def applied_look(sc, camera=None):
    cfg = get_config(sc)
    if not cfg or cfg['intensity'] == 0 or sc.render.engine == 'BLENDER_WORKBENCH':
        yield
        return
    from .outdoor import outdoor_root
    from .materials import apply_look_materials, restore_look_materials
    portrait_materials = []
    objects, meshes, materials, groups, worlds, actions = [], [], [], [], [], []
    lights, cameras = [], []
    old_world = sc.world
    saved_frame = sc.frame_current, sc.frame_subframe
    saved_view = {k: getattr(sc.view_settings, k) for k in ('view_transform', 'look', 'exposure', 'gamma')}
    settings = ('volumetric_tile_size', 'volumetric_samples', 'volumetric_start', 'volumetric_end',
                'use_volume_custom_range', 'use_volumetric_shadows', 'volumetric_shadow_samples')
    saved_settings = {k: getattr(sc.eevee, k) for k in settings}
    environment = next((o.get('c3d_environment_preset') for o in sc.objects
                        if o.get('c3d_environment_preset')), None)
    outdoors = outdoor_root() is not None or (environment is None and cfg['preset'] != 'studio_film')
    k = cfg['intensity']
    dark = cfg['preset'] in ('night', 'blue_hour')
    try:
        sc.view_settings.view_transform = 'AgX'
        sc.view_settings.look = 'AgX - Medium High Contrast'
        sc.eevee.volumetric_tile_size = '8'
        sc.eevee.volumetric_samples = 32
        sc.eevee.volumetric_start, sc.eevee.volumetric_end = .1, 65 if outdoors else 25
        sc.eevee.use_volume_custom_range = True
        sc.eevee.use_volumetric_shadows = cfg['rays'] > .8
        sc.eevee.volumetric_shadow_samples = 8
        _world(sc, cfg, outdoors, worlds)
        if outdoors and not any(o.type == 'LIGHT' and o.data.type == 'SUN' for o in sc.objects):
            sun = bpy.data.lights.new('__c3d_look_sun', 'SUN')
            obj = bpy.data.objects.new('__c3d_look_sun', sun)
            sc.collection.objects.link(obj)
            objects.append(obj)
            # This owned temporary light is removed separately from copied data.
            sun.energy = 0
        cast = _cast(sc)
        _classify_lights(sc, cast)
        has_rim = False
        for obj in list(sc.objects):
            if obj.type != 'LIGHT':
                continue
            if obj.get('c3d_material_catchlight_owner'):
                continue
            original = obj.data
            transform = {key: (getattr(obj, key).copy() if hasattr(getattr(obj, key), 'copy')
                               else list(getattr(obj, key)) if key == 'rotation_axis_angle'
                               else getattr(obj, key))
                         for key in ('location', 'scale', 'rotation_mode', 'rotation_euler',
                                     'rotation_quaternion', 'rotation_axis_angle')}
            temporary = original.copy()
            lights.append((obj, original, transform, obj.hide_render))
            obj.data = temporary
            obj.rotation_mode = 'XYZ'
            light = obj.data
            # Subject key/fill never contribute to fog: faces remain clean.
            light.volume_factor = 0
            if light.type == 'SUN':
                if outdoors:
                    weather = sc.get('c3d_weather_kind')
                    dim = 1-.6*sc.get('c3d_weather_intensity', 0) if weather in ('rain', 'snow', 'fog') else 1
                    light.energy = original.energy*(1-k) + cfg['sun_energy']*dim*k
                    light.color = Vector(original.color).lerp(Vector(cfg['sun_color']), k)
                    light.angle = original.angle*(1-k) + math.radians(18 if cfg['preset'] == 'overcast_soft' else 1.4)*k
                    # Night uses a visible moon key above the horizon; sky stays astronomical.
                    el = math.radians(30 if dark and cfg['elevation'] < 0 else cfg['elevation'])
                    az = math.radians(cfg['azimuth'])
                    direction = Vector((math.sin(az)*math.cos(el), -math.cos(az)*math.cos(el), math.sin(el)))
                    obj.rotation_euler = obj.rotation_euler.to_quaternion().slerp((-direction).to_track_quat('-Z', 'Y'), k).to_euler()
                    light.use_shadow = True
                    light.volume_factor = .5 + cfg['rays']*1.5
                else:
                    light.energy *= 1-k
            elif obj.get('c3d_role') == 'light':
                # Shape faces: classify subject lights by direction (front key/fill vs
                # back rim) and set a cinematic key:fill ratio with a motivated rim.
                role = _light_role(obj, cast)
                gains = _ROLE_GAINS[_mood(cfg['preset'])][role]
                base = ((.28 if dark else .58) if outdoors else (.55 if dark else .88))
                gain = gains[0] if outdoors else 1 + (gains[0]-1)*.5
                light.energy *= 1 + (base*gain - 1)*k
                if environment == 'stage' and cfg['preset'] == 'epic':
                    light.energy *= 1-.3*k
                if dark:
                    tint, amount = (.55, .70, 1), .85
                elif role == 'fill':
                    tint, amount = (.70, .80, 1), .55
                else:
                    tint, amount = tuple(cfg['sun_color']), gains[1]
                light.color = Vector(original.color).lerp(Vector(tint), amount*k)
                has_rim = has_rim or role == 'rim'
                if not outdoors and obj.name.endswith('_0'):
                    light.volume_factor = .35*cfg['rays']
            elif obj.get('c3d_role') == 'environment':
                if obj.get('c3d_nature_night_fill'):
                    light.energy=original.energy*(1-k)+(obj['c3d_nature_night_fill']*k if dark else 0)
                    light.volume_factor=0
                    continue
                practical = any(w in obj.name for w in ('lamp', 'stage_spot', 'window_daylight'))
                if practical:
                    light.volume_factor = 1 + cfg['rays']*4
                    light.use_shadow = True
                    if dark and 'window' not in obj.name:
                        light.energy *= 1 + .7*k
                    if 'stage_spot' in obj.name:
                        light.volume_factor = 18*cfg['rays']
                        light.spot_size *= 1-.4*k*cfg['rays']
                        light.spot_blend = light.spot_blend*(1-k*cfg['rays']) + .25*k*cfg['rays']
                    if 'window_daylight' in obj.name:
                        light.color = Vector(original.color).lerp(Vector(cfg['sun_color']), k)
                        light.volume_factor = cfg['rays']*4
                        if cfg['rays'] > 0 and not dark:
                            # The existing window is opaque emissive scenery.
                            # Project from just inside its plane, behind mullions,
                            # so those authored frames can cut the volume beam.
                            beam = bpy.data.lights.new('__c3d_look_window', 'SPOT')
                            beam.color = light.color
                            beam.energy = original.energy*k*cfg['rays']
                            beam.volume_factor = 4
                            beam.spot_size, beam.spot_blend = math.radians(48), .25
                            beam.shadow_soft_size = .035
                            projector = bpy.data.objects.new('__c3d_look_window', beam)
                            sc.collection.objects.link(projector)
                            objects.append(projector)
                            projector.parent = obj.parent
                            projector.location = obj.location
                            projector.location.x += .35
                            projector.location.y = 2.48
                            direction = Vector((0, -1.5, .4))-projector.location
                            projector.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
                            light.energy *= 1-.4*k
                elif dark:
                    light.energy *= 1-.35*k
        if cast and not has_rim and _mood(cfg['preset']) != 'neutral':
            # Motivated edge light from the sun/moon side behind the cast.
            center, height = cast
            az = math.radians(cfg['azimuth'] if math.cos(math.radians(cfg['azimuth'])) < -.2 else 165)
            el = math.radians(28)
            direction = Vector((math.sin(az)*math.cos(el), -math.cos(az)*math.cos(el), math.sin(el)))
            rim = bpy.data.lights.new('__c3d_look_rim', 'AREA')
            rim.shape, rim.size = 'DISK', .6*height
            rim.color = (.55, .70, 1) if dark else tuple(cfg['sun_color'])
            rim.energy = (260 if dark else 420)*(height/1.75)**2*k
            rim.volume_factor = 0
            holder = bpy.data.objects.new('__c3d_look_rim', rim)
            sc.collection.objects.link(holder)
            objects.append(holder)
            holder.location = center + direction*1.9*height
            holder.rotation_euler = (center - holder.location).to_track_quat('-Z', 'Y').to_euler()
        for camera in ([camera] if camera else [o for o in sc.objects if o.type == 'CAMERA']):
            if cfg['dof'] != 'auto':
                continue
            original = camera.data
            temporary = original.copy()
            cameras.append((camera, original))
            camera.data = temporary
            _focus(sc, camera, objects, actions)
        _volume(sc, cfg, outdoors, objects, meshes, materials)
        _particles(sc, cfg, objects, meshes, materials, groups)
        portrait_materials = apply_look_materials(sc, cfg)
        bpy.context.view_layer.update()
        yield
    finally:
        restore_look_materials(portrait_materials)
        for camera, original in cameras:
            copy = camera.data
            camera.data = original
            bpy.data.cameras.remove(copy)
        for obj, original, transform, hidden in lights:
            copy = obj.data
            obj.data, obj.hide_render = original, hidden
            for key, value in transform.items():
                setattr(obj, key, value)
            bpy.data.lights.remove(copy)
        sc.world = old_world
        for obj in reversed(objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if isinstance(data, bpy.types.Light) and data.users == 0:
                bpy.data.lights.remove(data)
        for pool, items in ((bpy.data.meshes, meshes), (bpy.data.materials, materials),
                            (bpy.data.node_groups, groups), (bpy.data.worlds, worlds)):
            for item in items:
                pool.remove(item)
        for action in actions:
            if action.users == 0:
                bpy.data.actions.remove(action)
        for key, value in saved_settings.items():
            setattr(sc.eevee, key, value)
        for key, value in saved_view.items():
            setattr(sc.view_settings, key, value)
        sc.frame_set(saved_frame[0], subframe=saved_frame[1])
