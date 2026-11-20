"""Persistent, reversible character shading. No handlers, baking or shells.

Original materials and inactive OBJECT slot overrides are retained as ID pointers;
private copies of nested MPFB graphs keep authored textures/UVs/normal maps intact.
Rest-space vertex attributes travel with skinning, morphs and saved video snapshots.
"""
from contextlib import contextmanager
import json
import math

import bpy
import numpy as np
from mathutils import Vector

from . import command
from .util import obj_or_raise
from .. import materials as profiles

CONFIG = 'char3d_materials'
BACKUP = 'c3d_material_slots'
REGIONS = 'c3d_material_regions'
REST = 'c3d_material_rest'
CORNEA = 'c3d_material_cornea'
OWNED = 'c3d_material_version'
CATCHLIGHT = 'c3d_material_catchlight_owner'


def _trees(tree, seen=None):
    seen = set() if seen is None else seen
    if tree in seen:
        return
    seen.add(tree)
    yield tree
    for node in tree.nodes:
        if node.type == 'GROUP' and node.node_tree:
            yield from _trees(node.node_tree, seen)


def _private(original):
    mat = original.copy()
    mat.name = 'c3d_enhanced.' + original.name
    mat[OWNED] = profiles.VERSION
    mat['c3d_material_source'] = original
    copies = {}

    def visit(tree):
        for node in tree.nodes:
            if node.type != 'GROUP' or not node.node_tree:
                continue
            source = node.node_tree
            if source not in copies:
                copy = source.copy()
                copy.name = 'c3d_material.' + source.name
                copy[OWNED] = profiles.VERSION
                copies[source] = copy
                visit(copy)
            node.node_tree = copies[source]
    visit(mat.node_tree)
    return mat


def _cleanup():
    for mat in list(bpy.data.materials):
        if mat.get(OWNED) and mat.users == 0:
            bpy.data.materials.remove(mat)
    # Outer groups hold inner groups; remove parents before their newly orphaned children.
    while True:
        unused = [g for g in bpy.data.node_groups if g.get(OWNED) and g.users == 0]
        if not unused:
            break
        for group in unused:
            bpy.data.node_groups.remove(group)


def _node(tree, kind, label):
    node = tree.nodes.new(kind)
    node.name = node.label = 'c3d ' + label
    return node


def _put(tree, socket, value):
    for link in list(socket.links):
        tree.links.remove(link)
    if hasattr(value, 'node'):
        tree.links.new(value, socket)
    else:
        socket.default_value = value


def _set(tree, bsdf, name, value):
    if name in bsdf.inputs:
        _put(tree, bsdf.inputs[name], value)


def _math(tree, op, a, b, label):
    node = _node(tree, 'ShaderNodeMath', label)
    node.operation = op
    _put(tree, node.inputs[0], a)
    _put(tree, node.inputs[1], b)
    return node.outputs[0]


def _mix(tree, color, tint, factor, label, blend='MULTIPLY'):
    node = _node(tree, 'ShaderNodeMixRGB', label)
    node.blend_type = blend
    _put(tree, node.inputs[0], factor)
    _put(tree, node.inputs[1], color)
    _put(tree, node.inputs[2], tint)
    return node.outputs[0]


def _source(socket):
    return socket.links[0].from_socket if socket.is_linked else (
        tuple(socket.default_value) if hasattr(socket.default_value, '__len__') else socket.default_value)


def _attribute(tree, name):
    node = _node(tree, 'ShaderNodeAttribute', name)
    node.attribute_name = name
    return node


def _channels(tree):
    attr = _attribute(tree, REGIONS)
    separate = _node(tree, 'ShaderNodeSeparateColor', 'region channels')
    tree.links.new(attr.outputs['Color'], separate.inputs[0])
    return (*separate.outputs[:3], attr.outputs['Alpha'])


def _noise(tree, scale, label):
    node = _node(tree, 'ShaderNodeTexNoise', label)
    node.inputs['Scale'].default_value = scale
    node.inputs['Detail'].default_value = 1.
    node.inputs['Roughness'].default_value = .5
    tree.links.new(_attribute(tree, REST).outputs['Vector'], node.inputs['Vector'])
    return node.outputs['Fac']


def _bump(tree, bsdf, height, distance, strength):
    bump = _node(tree, 'ShaderNodeBump', 'micro normal (meters)')
    _put(tree, bump.inputs['Height'], height)
    _put(tree, bump.inputs['Distance'], distance)
    _put(tree, bump.inputs['Strength'], strength)
    # Keep the authored map, but remove MPFB's excessive procedural pore branch.
    normal = next((n for n in tree.nodes if n.type == 'NORMAL_MAP'), None)
    if normal:
        tree.links.new(normal.outputs['Normal'], bump.inputs['Normal'])
    elif bsdf.inputs['Normal'].is_linked:
        source = bsdf.inputs['Normal'].links[0].from_node
        if source.type != 'BUMP':
            tree.links.new(source.outputs[0], bump.inputs['Normal'])
    _set(tree, bsdf, 'Normal', bump.outputs['Normal'])


def _image(mat, hint='diffuse'):
    if not mat or not mat.node_tree:
        return None
    return next((n.image for t in _trees(mat.node_tree) for n in t.nodes
                 if n.type == 'TEX_IMAGE' and n.image and hint in n.name.lower()), None)


def _pixels(image):
    """One bounded float32 read; repeated RNA slices can materialize the image."""
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels


def _sample_skin(body, mat, eye_z):
    image = _image(mat)
    if not image or not body.data.uv_layers:
        return tuple(mat.diffuse_color[:3])
    # Select fitted facial texels; the median limits freckles/highlight bias.
    uv = body.data.uv_layers.active.data
    indices = []
    w, h = image.size
    if not w or not h:
        return tuple(mat.diffuse_color[:3])
    for loop in body.data.loops:
        v = body.data.vertices[loop.vertex_index].co
        if .018 < abs(v.x) < .058 and eye_z-.06 < v.z < eye_z-.012 and v.y < -.06:
            u, y = uv[loop.index].uv
            index = 4*(min(h-1, max(0, int(y*h)))*w + min(w-1, max(0, int(u*w))))
            indices.append(index)
            if len(indices) >= 80:
                break
    if not indices:
        return tuple(mat.diffuse_color[:3])
    pixels = _pixels(image)
    samples = [tuple(float(v) for v in pixels[i:i+3]) for i in indices]
    rgb = tuple(sorted(s[i] for s in samples)[len(samples)//2] for i in range(3))
    return profiles.srgb_to_linear(rgb) if image.colorspace_settings.name == 'sRGB' else rgb


def _hair_color(meshes, body):
    hair = next((o for o in meshes if _role(o, body) == 'hair'), None)
    image = _image(hair.material_slots[0].material) if hair and hair.material_slots else None
    if not image or not image.size[0]:
        return None
    w, h = image.size
    pixels = _pixels(image)
    samples = []
    for y in range(1, 12):
        for x in range(1, 12):
            i = 4*(int(y*h/12)*w+int(x*w/12))
            rgba = pixels[i:i+4]
            if len(rgba) == 4 and float(rgba[3]) > .6:
                samples.append(tuple(float(v) for v in rgba[:3]))
    if not samples:
        return None
    rgb = tuple(sorted(s[i] for s in samples)[len(samples)//2] for i in range(3))
    return profiles.srgb_to_linear(rgb) if image.colorspace_settings.name == 'sRGB' else rgb


def _family(character):
    obj = obj_or_raise(character)
    rig = obj if obj.type == 'ARMATURE' else obj.find_armature() if obj.type == 'MESH' else None
    meshes = [o for o in ([rig, *rig.children_recursive] if rig else [obj, *obj.children_recursive])
              if o.type == 'MESH' and not o.get('c3d_role')]
    body = next((o for o in meshes if o.get('c3d_source') == 'mpfb'), None)
    if body is None:
        raise ValueError('upgrade_materials needs an MPFB body or its armature')
    return rig or body, body, meshes


def _role(obj, body):
    if obj == body:
        return 'skin'
    part = obj.get('c3d_material_part', obj.name.split('.', 1)[-1]).lower()
    if any(s in part for s in ('eyebrow', 'eyelash', 'beard', 'moustache', 'mustache')):
        return 'brows'
    if any(s in part for s in ('high-poly', 'low-poly', 'eye')):
        return 'eyes'
    if any(s in part for s in ('hair', 'bob', 'ponytail', 'braid', 'short0', 'long0', 'afro')):
        return 'hair'
    if any(s in part for s in ('teeth', 'tongue')):
        return 'mouth'
    if any(s in part for s in ('glasses', 'spectacles')):
        return 'accessory'
    return 'clothes'


def _eye_frame(meshes, body):
    eyes = next((o for o in meshes if _role(o, body) == 'eyes'), None)
    if eyes:
        coords = [body.matrix_world.inverted() @ eyes.matrix_world @ v.co for v in eyes.data.vertices]
        z = (min(v.z for v in coords)+max(v.z for v in coords))/2
        y = min(v.y for v in coords)
        width = max(v.x for v in coords)-min(v.x for v in coords)
        return z, y, max(.6, min(1.5, width/.088))
    z = max(v.co.z for v in body.data.vertices)*.885
    return z, -.12, 1.


def _attributes(obj, body, role, frame):
    """Masks in fitted rest anatomy, independent of skin UV layout and ethnicity."""
    me = obj.data
    # Refuse to overwrite custom user attributes; record only newly owned names.
    owned = json.loads(obj.get('c3d_material_attributes', '[]'))
    specs = [(REST, 'FLOAT_VECTOR'), (REGIONS, 'FLOAT_COLOR')]
    if role == 'eyes':
        specs.append((CORNEA, 'FLOAT'))
    for name, kind in specs:
        if name not in me.attributes:
            me.attributes.new(name=name, type=kind, domain='POINT')
            owned.append(name)
        elif name not in owned:
            raise ValueError(f'Reserved attribute {name} already exists on {obj.name}')
    obj['c3d_material_attributes'] = json.dumps(owned)
    rest, region = me.attributes[REST], me.attributes[REGIONS]
    ez, ey, unit = frame
    transform = body.matrix_world.inverted() @ obj.matrix_world
    coords = [transform @ v.co for v in me.vertices]
    low, high = min(v.z for v in coords), max(v.z for v in coords)
    values = []
    vectors = []
    cornea = []

    def gaussian(x, z, cx, cz, sx, sz):
        return math.exp(-.5*((x-cx)/sx)**2-.5*((z-cz)/sz)**2)

    for p in coords:
        vectors.extend(p)
        x, z = p.x/unit, (p.z-ez)/unit
        if role == 'skin':
            front = min(1., max(0., (ey+.04*unit-p.y)/(.045*unit)))
            cheeks = gaussian(abs(x), z, .043, -.036, .024, .025)*front
            nose = gaussian(x, z, 0, -.030, .018, .027)*front
            tip = gaussian(x, z, 0, -.047, .013, .011)*front
            ears = gaussian(abs(x), z, .078, -.007, .016, .032)
            # Anatomical hand region, limited to joints by a broad rest-space mask.
            knuckles = gaussian(abs(x), z, .43, -.58, .04, .045)
            red = min(1., max(cheeks*.8, tip*.9, nose*.35, ears*.7, knuckles*.4))
            oil = max(gaussian(x, z, 0, .035, .035, .025), nose)*front
            lips = gaussian(x, z, 0, -.075, .025, .009)*front
            lids = gaussian(abs(x), z, .030, .001, .019, .011)*front
            detail = .12+.88*math.exp(-.5*(z/.13)**4)
            values.extend((red, oil, detail, max(lips, lids*.35)))
        elif role == 'eyes':
            # Each eyeball's rest surface. The original iris/vein texture remains.
            cx = (.029 if p.x >= 0 else -.029)*unit
            radial = math.hypot(p.x-cx, p.z-ez)/unit
            iris = max(0., min(1., (.0075-radial)/.002))
            lid = max(0., min(1., (z-.004)/.009))
            tear = math.exp(-.5*((z+.007)/.0018)**2)
            angle = (math.atan2(p.z-ez, p.x-cx)+math.pi)/(2*math.pi)
            values.extend((iris, lid, tear, angle))
            cornea.append(max(0., 1-(radial/.0075)**2))
        else:
            tip = min(1., max(0., (high-p.z)/max(.01, high-low)))
            values.extend((tip, 0, 0, 1))
    rest.data.foreach_set('vector', vectors)
    region.data.foreach_set('color', values)
    if role == 'eyes':
        me.attributes[CORNEA].data.foreach_set('value', cornea)
    me.update()


def _skin(tree, bsdf, profile, detail):
    red, oil, face, lips = _channels(tree)
    color = _source(bsdf.inputs['Base Color'])
    color = _mix(tree, color, (profile['albedo_gain'],)*3+(1.,), 1., 'skin reflectance')
    color = _mix(tree, color, (*profile['albedo_tint'], 1.), 1., 'restrained rosy undertone')
    # Multiply selectively: no whole-face orange tint, no lift that washes out melanin.
    color = _mix(tree, color, (1.03, .72, .78, 1), _math(tree, 'MULTIPLY', red, profile['redness']*4, 'blood perfusion'), 'warm cheek/ear tint')
    color = _mix(tree, color, (.78, .50, .52, 1), _math(tree, 'MULTIPLY', lips, .4, 'lip/lid depth'), 'lip/lid tint')
    _set(tree, bsdf, 'Base Color', color)
    noise = _noise(tree, 1800., 'fine pores 0.55 mm')
    roughness = _math(tree, 'ADD', _math(tree, 'MULTIPLY', noise, .045*detail, 'roughness variation'), profile['roughness'], 'cheek roughness')
    roughness = _math(tree, 'SUBTRACT', roughness, _math(tree, 'MULTIPLY', oil, .095, 'T-zone oil'), 'skin roughness')
    _set(tree, bsdf, 'Roughness', roughness)
    _set(tree, bsdf, 'Specular IOR Level', profile['specular'])
    _set(tree, bsdf, 'IOR', 1.4)
    _set(tree, bsdf, 'Coat Weight', 0.)
    _set(tree, bsdf, 'Sheen Weight', 0.)
    _set(tree, bsdf, 'Subsurface Weight', profile['sss'])
    _set(tree, bsdf, 'Subsurface Radius', profile['radius'])
    _set(tree, bsdf, 'Subsurface Scale', profile['scale'])
    _set(tree, bsdf, 'Subsurface IOR', 1.4)
    if profile['pore_distance']:
        _bump(tree, bsdf, noise, _math(tree, 'MULTIPLY', face, profile['pore_distance'], 'fade pores on body'), .18)
    else:
        normal = next((n for n in tree.nodes if n.type == 'NORMAL_MAP'), None)
        _set(tree, bsdf, 'Normal', normal.outputs['Normal'] if normal else (0., 0., 0.))


def _neutral_default_skin_tint(mat):
    """MPFB's 5% uniform red mix is large relative to dark scan reflectance.

    Keep authored texture colors and non-default user adjustments. Local blood
    perfusion replaces only this known legacy default on the private graph.
    """
    for tree in _trees(mat.node_tree):
        for node in tree.nodes:
            if node.type != 'GROUP':
                continue
            amount = node.inputs.get('colorMixInStrength')
            color = node.inputs.get('colorMixIn')
            if amount and color and not amount.is_linked and not color.is_linked and (
                abs(amount.default_value-.05) < 1e-6 and
                all(abs(a-b) < 1e-6 for a,b in zip(color.default_value, (1.,.2,.2,1.)))):
                amount.default_value = 0.


def _eyes(tree, bsdf, unit=1., brown=True):
    iris, lid, tear, angle = _channels(tree)
    sclera = _math(tree, 'SUBTRACT', 1., iris, 'sclera mask')
    color = _source(bsdf.inputs['Base Color'])
    color = _mix(tree, color, (.95, .91, .87, 1), sclera, 'warm sclera')
    color = _mix(tree, color, (.55, .52, .53, 1), _math(tree, 'MULTIPLY', lid, .28, 'upper lid occlusion'), 'soft lid shade')
    pigment = _node(tree, 'ShaderNodeHueSaturation', 'natural iris pigment')
    _put(tree, pigment.inputs['Color'], color)
    pigment.inputs['Saturation'].default_value = profiles.IRIS_SATURATION if brown else .9
    pigment.inputs['Value'].default_value = profiles.IRIS_VALUE if brown else .85
    corrected = _mix(tree, pigment.outputs['Color'], (*(profiles.IRIS_TINT if brown else (1., 1., 1.)), 1.), 1., 'iris red balance')
    color = _mix(tree, color, corrected, iris, 'preserve iris pattern', blend='MIX')
    ring = _math(tree, 'MULTIPLY', iris, sclera, 'limbal ring profile')
    color = _mix(tree, color, (.25, .25, .25, 1), _math(tree, 'MULTIPLY', ring, 2., 'limbal ring depth'), 'dark limbal ring')
    phase = _math(tree, 'MULTIPLY', angle, 42*math.pi, 'radial fiber phase')
    fibers = _math(tree, 'ADD', .94, _math(tree, 'MULTIPLY',
                   _math(tree, 'SINE', phase, 0., 'radial fibers'), .06, 'fiber contrast'), 'iris fiber value')
    color = _mix(tree, color, fibers, iris, 'subtle radial detail')
    _set(tree, bsdf, 'Base Color', color)
    _set(tree, bsdf, 'Roughness', .28)
    _set(tree, bsdf, 'IOR', 1.376)
    _set(tree, bsdf, 'Metallic', 0.)
    _set(tree, bsdf, 'Subsurface Weight', 0.)
    _set(tree, bsdf, 'Emission Strength', 0.)
    # Large beauty-light reflections must not erase the pupil. Retain a sharp
    # wet catchlight, with lower central reflection gain and wetter sclera/tears.
    _set(tree, bsdf, 'Specular IOR Level', _math(tree, 'SUBTRACT', .24,
         _math(tree, 'MULTIPLY', iris, .225, 'iris reflection balance'), 'eye specular'))
    _set(tree, bsdf, 'Coat Weight', _math(tree, 'SUBTRACT', .60,
         _math(tree, 'MULTIPLY', iris, .555, 'clear iris coat'), 'wet eye coat'))
    _set(tree, bsdf, 'Coat IOR', 1.336)
    bulge = _node(tree, 'ShaderNodeBump', 'corneal cap normal')
    _put(tree, bulge.inputs['Height'], _attribute(tree, CORNEA).outputs['Fac'])
    bulge.inputs['Distance'].default_value = .0012*unit
    bulge.inputs['Strength'].default_value = 1.
    _set(tree, bsdf, 'Coat Normal', bulge.outputs['Normal'])
    _set(tree, bsdf, 'Coat Roughness', _math(tree, 'SUBTRACT', .025, _math(tree, 'MULTIPLY', tear, .01, 'tear moisture'), 'wet cornea'))
    # Opaque single-layer coat is stable in Eevee DOF; no refraction/ray tracing.


def _hair(tree, bsdf, detail, brows=False, hair_color=None, coily=False):
    tip, _, _, _ = _channels(tree)
    color = _source(bsdf.inputs['Base Color'])
    if brows and hair_color:
        # Keep authored strands and alpha, add a restrained shared hair undertone.
        tint = tuple(min(.22, max(.002, v*.65)) for v in hair_color)+(1.,)
        color = _mix(tree, color, tint, .18*detail, 'coherent brow/lash undertone', blend='MIX')
    gradient = _math(tree, 'ADD', _math(tree, 'MULTIPLY', tip, .25*detail, 'lighter tips'), 1-.28*detail, 'root-tip gradient')
    color = _mix(tree, color, gradient, 1., 'root depth')
    uv = _node(tree, 'ShaderNodeTexCoord', 'strand UV')
    scale = _node(tree, 'ShaderNodeVectorMath', 'longitudinal strand coordinates')
    scale.operation = 'MULTIPLY'
    tree.links.new(uv.outputs['UV'], scale.inputs[0])
    scale.inputs[1].default_value = (130, 3, 1)
    noise = _node(tree, 'ShaderNodeTexNoise', 'strand variation')
    noise.inputs['Scale'].default_value = 1.
    noise.inputs['Detail'].default_value = 0.
    tree.links.new(scale.outputs['Vector'], noise.inputs['Vector'])
    color = _mix(tree, color, noise.outputs['Fac'], .12*detail, 'individual strands')
    _set(tree, bsdf, 'Base Color', color)
    _set(tree, bsdf, 'Roughness', .52 if brows else .64 if coily else .46)
    _set(tree, bsdf, 'Specular IOR Level', .20 if brows else .12 if coily else .24)
    if hair_color and not brows:
        maximum = max(max(hair_color), .001)
        highlight = tuple(.65+.35*v/maximum for v in hair_color)+(1.,)
        _set(tree, bsdf, 'Specular Tint', highlight)
        _set(tree, bsdf, 'Sheen Tint', highlight)
    _set(tree, bsdf, 'Coat Weight', 0.)
    _set(tree, bsdf, 'Anisotropic', .05 if coily else .35 if not brows else .12)
    tangent = _node(tree, 'ShaderNodeTangent', 'strand tangent')
    tangent.direction_type = 'UV_MAP'
    _set(tree, bsdf, 'Tangent', tangent.outputs['Tangent'])
    _set(tree, bsdf, 'Sheen Weight', .03 if brows else .06)
    _set(tree, bsdf, 'Sheen Roughness', .45)
    _set(tree, bsdf, 'Subsurface Weight', .015 if brows else .04)
    _set(tree, bsdf, 'Subsurface Radius', (1., .5, .25))
    _set(tree, bsdf, 'Subsurface Scale', .00025)
    if detail and not brows:
        _bump(tree, bsdf, noise.outputs['Fac'], .000018*detail, .10)


def _fabric(tree, bsdf, kind):
    cfg = profiles.FABRICS[kind]
    # Authored maps continue to control big folds and surface wear.
    rough = _source(bsdf.inputs['Roughness'])
    if hasattr(rough, 'node'):
        rough = _math(tree, 'MULTIPLY', rough, cfg['roughness']/.7, 'fabric roughness map')
    else:
        rough = cfg['roughness']
    _set(tree, bsdf, 'Roughness', rough)
    _set(tree, bsdf, 'Sheen Weight', cfg['sheen'])
    _set(tree, bsdf, 'Sheen Roughness', .65)
    _set(tree, bsdf, 'Specular IOR Level', .3)
    _set(tree, bsdf, 'Anisotropic', cfg['anisotropy'])
    if kind == 'leather':
        height = _noise(tree, cfg['scale'], 'leather grain')
    else:
        wave = _node(tree, 'ShaderNodeTexWave', 'micro weave')
        wave.wave_type, wave.bands_direction, wave.wave_profile = 'BANDS', 'DIAGONAL', 'SIN'
        wave.inputs['Scale'].default_value = cfg['scale']
        wave.inputs['Distortion'].default_value = .35 if kind in ('wool', 'knit') else .05
        tree.links.new(_attribute(tree, REST).outputs['Vector'], wave.inputs['Vector'])
        height = wave.outputs['Fac']
    _bump(tree, bsdf, height, cfg['bump'], .12)


def _catchlight(body, meshes, frame):
    """Tiny eye-linked reflection source; no diffuse, volumes or shadow maps."""
    eyes = [o for o in meshes if _role(o, body) == 'eyes']
    if not eyes:
        return None
    data = bpy.data.lights.new('c3d_cornea.'+body.name, 'POINT')
    data.diffuse_factor, data.volume_factor = 0., 0.
    data.use_shadow = False
    z, y, unit = frame
    data.energy = 20.*unit*unit
    data.shadow_soft_size = .06*unit
    light = bpy.data.objects.new('c3d_cornea.'+body.name, data)
    light[CATCHLIGHT] = body
    light['c3d_role'] = 'material_catchlight'
    bpy.context.scene.collection.objects.link(light)
    receivers = bpy.data.collections.new('c3d_cornea.'+body.name)
    receivers[CATCHLIGHT] = body
    for eye in eyes:
        receivers.objects.link(eye)
    light.light_linking.receiver_collection = receivers
    point = body.matrix_world @ Vector((-.10*unit, y-.50*unit, z+.12*unit))
    rig = body.find_armature()
    if rig:
        from .anim import semantic_map
        head = semantic_map(rig).get('head')
        if head:
            rest, posed = rig.data.bones[head], rig.pose.bones[head]
            point = rig.matrix_world @ posed.matrix @ rest.matrix_local.inverted() @ rig.matrix_world.inverted() @ point
            light.parent, light.parent_type, light.parent_bone = rig, 'BONE', head
        else:
            light.parent = rig
    else:
        light.parent = body
    bpy.context.view_layer.update()
    light.matrix_world.translation = point
    return dict(object=light.name, watts=data.energy, eye_linked=True, diffuse=0., shadows=False)


def _restore(meshes):
    members = set(meshes)
    for light in list(bpy.data.objects):
        if light.get(CATCHLIGHT) in members:
            data = light.data
            bpy.data.objects.remove(light, do_unlink=True)
            if data.users == 0:
                bpy.data.lights.remove(data)
    for collection in list(bpy.data.collections):
        if collection.get(CATCHLIGHT) in members:
            bpy.data.collections.remove(collection)
    restored = []
    for obj in meshes:
        backup = json.loads(obj.get(BACKUP, '[]'))
        for i, state in enumerate(backup):
            if i >= len(obj.material_slots):
                raise ValueError(f'Material slots changed on {obj.name}; restore before editing slots')
            slot = obj.material_slots[i]
            slot.link = 'OBJECT'
            slot.material = obj.get(f'c3d_material_inactive_{i}')
            slot.link = state['link']
            if state['link'] == 'OBJECT':
                slot.material = obj.get(f'c3d_material_original_{i}')
            for prefix in ('original', 'inactive'):
                obj.pop(f'c3d_material_{prefix}_{i}', None)
        if backup:
            restored.append(obj.name)
        obj.pop(BACKUP, None)
        obj.pop(CONFIG, None)
        for name in json.loads(obj.get('c3d_material_attributes', '[]')):
            attr = obj.data.attributes.get(name)
            if attr:
                obj.data.attributes.remove(attr)
        obj.pop('c3d_material_attributes', None)
    _cleanup()
    return restored


@command('upgrade_materials')
def upgrade_materials(character, quality='enhanced', skin_tone=None, skin_detail=1., hair_detail=1.):
    cfg = profiles.options(quality, skin_tone, skin_detail, hair_detail)
    root, body, meshes = _family(character)
    # Validate reserved names before replacing any slots; reruns reuse originals.
    for obj in meshes:
        owned = json.loads(obj.get('c3d_material_attributes', '[]'))
        if quality == 'enhanced' and any(n in obj.data.attributes and n not in owned for n in (REST, REGIONS, CORNEA)):
            raise ValueError(f'Reserved material attributes already exist on {obj.name}')
    if quality == 'mpfb':
        restored = _restore(meshes)
        root.pop(CONFIG, None)
        return dict(character=root.name, quality=quality, restored=restored,
                    materials_cost_factor=scene_cost_factor(bpy.context.scene, 'BLENDER_EEVEE'))
    _restore(meshes)
    frame = _eye_frame(meshes, body)
    hair_color = _hair_color(meshes, body)
    skin_mat = body.material_slots[0].material
    sampled = _sample_skin(body, skin_mat, frame[0])
    rgb = profiles.TONES[skin_tone]['color'] if isinstance(skin_tone, str) else skin_tone or sampled
    macro_age = body.get('HUM_age', getattr(body, 'HUM_age', .5))
    age = float(body.get('c3d_age', profiles.age_years(macro_age)))
    profile = profiles.skin_profile(rgb, age, skin_detail)
    changed, skipped = [], []
    try:
        for obj in meshes:
            role = _role(obj, body)
            if role in ('mouth', 'accessory'):
                skipped.append(obj.name)
                continue
            _attributes(obj, body, role, frame)
            states = []
            obj[BACKUP] = '[]'
            for i, slot in enumerate(obj.material_slots):
                original = slot.material
                link = slot.link
                slot.link = 'OBJECT'
                inactive = slot.material
                states.append(dict(link=link))
                obj[BACKUP] = json.dumps(states)
                if original:
                    obj[f'c3d_material_original_{i}'] = original
                if inactive:
                    obj[f'c3d_material_inactive_{i}'] = inactive
                if not original or not original.node_tree:
                    slot.link = link
                    continue
                mat = _private(original)
                slot.material = mat
                mat['c3d_material_role'] = role
                mat['c3d_material_profile'] = json.dumps(profile if role == 'skin' else {})
                if role == 'skin':
                    _neutral_default_skin_tint(mat)
                for tree in _trees(mat.node_tree):
                    for bsdf in [n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED']:
                        if role == 'skin':
                            _skin(tree, bsdf, profile, skin_detail)
                        elif role == 'eyes':
                            image = _image(original)
                            _eyes(tree, bsdf, frame[2], brown=bool(image and 'brown' in image.filepath.lower()))
                        elif role in ('hair', 'brows'):
                            _hair(tree, bsdf, hair_detail, role == 'brows', hair_color,
                                  coily='afro' in obj.get('c3d_material_part', obj.name).lower())
                        else:
                            hints = obj.get('c3d_garment_category', '')+' '+obj.get('c3d_garment_tags', '')
                            kind = profiles.fabric_kind(obj.name, hints)
                            mat['c3d_material_fabric'] = kind
                            _fabric(tree, bsdf, kind)
                if role in ('hair', 'brows'):
                    if hasattr(mat, 'surface_render_method'):
                        mat.surface_render_method = 'DITHERED'
                    elif hasattr(mat, 'blend_method'):
                        mat.blend_method = 'HASHED'
                changed.append(dict(object=obj.name, material=mat.name, role=role,
                                    fabric=mat.get('c3d_material_fabric')))
            obj[CONFIG] = json.dumps(cfg)
        root[CONFIG] = json.dumps(cfg)
        catchlight = _catchlight(body, meshes, frame)
    except Exception:
        _restore(meshes)
        root.pop(CONFIG, None)
        raise
    return dict(character=root.name, **cfg, materials=changed, skipped=skipped,
                sampled_skin_rgb=sampled, skin_profile=profile, catchlight=catchlight,
                materials_cost_factor=scene_cost_factor(bpy.context.scene, 'BLENDER_EEVEE'),
                limits=['Single-surface corneal coat; no refractive iris geometry or tear mesh.',
                        'Hair anisotropy depends on Eevee support; sheen/strand normals approximate it.',
                        'No volume shells or animated shader noise; authored alpha/texture colors retained.'])


def scene_cost_factor(sc, engine):
    from .render_style import get_config
    bodies = [o for o in sc.objects if o.type == 'MESH' and not o.hide_render and o.get('c3d_source') == 'mpfb']
    enhanced = sum(any(s.material and s.material.get(OWNED) for s in o.material_slots) for o in bodies)
    cfg = get_config(sc) or {}
    return profiles.cost_factor(enhanced, len(bodies), engine, cfg.get('style'), cfg.get('strength', 1.))


def restore_look_materials(saved):
    for socket, value in reversed(saved):
        socket.default_value = value


def apply_look_materials(sc, config):
    """Temporary scalar calibration only; snapshots bake it into native nodes."""
    saved, seen = [], set()
    try:
        for obj in sc.objects:
            if obj.type != 'MESH':
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if not mat or mat in seen or mat.get(OWNED, 0) < 2 or mat.get('c3d_material_role') != 'skin':
                    continue
                seen.add(mat)
                profile = json.loads(mat['c3d_material_profile'])
                gain = profiles.look_albedo_gain(profile, config)
                if abs(gain-profile['albedo_gain']) < 1e-8:
                    continue
                for tree in _trees(mat.node_tree):
                    node = tree.nodes.get('c3d skin reflectance')
                    if node:
                        socket = node.inputs[2]
                        saved.append((socket, tuple(socket.default_value)))
                        socket.default_value = (gain, gain, gain, 1.)
    except Exception:
        restore_look_materials(saved)
        raise
    return saved


def _fallback(original, enhanced):
    """Exporter-recognizable PBR graph: authored images + scalar material parameters."""
    mat = bpy.data.materials.new('c3d_export.'+original.name)
    mat.use_nodes = True
    mat[OWNED] = profiles.VERSION
    tree = mat.node_tree
    bsdf = tree.nodes.get('Principled BSDF')
    role = enhanced.get('c3d_material_role')
    profile = json.loads(enhanced.get('c3d_material_profile', '{}'))
    kind = enhanced.get('c3d_material_fabric', 'cotton')
    surface_roughness = {'eyes': .28, 'brows': .52,
                         'hair': .64 if 'afro' in original.name.lower() else .46}
    rough = profile.get('roughness', surface_roughness.get(role, profiles.FABRICS[kind]['roughness']))
    flat = enhanced.get('c3d_photo_flat_color')
    bsdf.inputs['Base Color'].default_value = tuple(flat)+(1.,) if flat is not None else original.diffuse_color
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Specular IOR Level'].default_value = .28 if role == 'skin' else .5
    photo = enhanced.get('c3d_photo_base_image')
    iris = enhanced.get('c3d_photo_iris_image')
    diffuse = photo or iris or _image(original)
    if diffuse:
        node = _node(tree, 'ShaderNodeTexImage', 'export base texture')
        node.image = diffuse
        if iris:
            node.extension = 'EXTEND'
            uv = _node(tree, 'ShaderNodeUVMap', 'export photo iris UV')
            uv.uv_map = 'c3d_photo_iris'
            tree.links.new(uv.outputs[0], node.inputs['Vector'])
        if flat is None:
            tree.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
        if (role == 'skin' and flat is None and not photo) or (enhanced.get('c3d_photo_tint') and not iris):
            # glTF recognizes this image * constant graph as baseColorFactor,
            # keeping the restrained reflectance correction without a bake.
            factor = _node(tree, 'ShaderNodeMix', 'export skin reflectance factor')
            factor.data_type, factor.blend_type = 'RGBA', 'MULTIPLY'
            factor.inputs[0].default_value = 1.
            gain = profile.get('albedo_gain', 1.) if role=='skin' else 1.
            tint = profile.get('albedo_tint', (1., 1., 1.)) if role=='skin' else enhanced['c3d_photo_tint']
            factor.inputs[7].default_value = tuple(gain*t for t in tint)+(1.,)
            tree.links.new(node.outputs['Color'], factor.inputs[6])
            tree.links.new(factor.outputs[2], bsdf.inputs['Base Color'])
        # Explicit photo pigment/texture replaces the scan. Its original
        # scan-specific exposure correction must not be applied a second time.
        if role in ('hair', 'brows'):
            tree.links.new(node.outputs['Alpha'], bsdf.inputs['Alpha'])
    opacity = _image(original, 'opacity')
    if opacity:
        node = _node(tree, 'ShaderNodeTexImage', 'export authored opacity')
        node.image = opacity
        tree.links.new(node.outputs['Color'], bsdf.inputs['Alpha'])
    roughness = _image(original, 'roughness')
    if roughness:
        node = _node(tree, 'ShaderNodeTexImage', 'export authored roughness')
        node.image = roughness
        tree.links.new(node.outputs['Color'], bsdf.inputs['Roughness'])
    normal = _image(original, 'normal')
    if normal:
        node = _node(tree, 'ShaderNodeTexImage', 'export authored normal')
        node.image = normal
        convert = _node(tree, 'ShaderNodeNormalMap', 'export normal')
        tree.links.new(node.outputs['Color'], convert.inputs['Color'])
        tree.links.new(convert.outputs['Normal'], bsdf.inputs['Normal'])
    if hasattr(mat, 'surface_render_method'):
        mat.surface_render_method = 'DITHERED'
    return mat


@contextmanager
def export_materials(objects):
    slots, temporary, cache, meshes = [], [], {}, []
    hidden = []
    lost = []
    try:
        for obj in objects:
            if obj.get(CATCHLIGHT):
                hidden.append((obj, obj.hide_get(), obj.select_get()))
                obj.hide_set(True)
                obj.select_set(False)
            if obj.type == 'MESH' and any(s.material and s.material.get(OWNED) for s in obj.material_slots):
                names = json.loads(obj.get('c3d_material_attributes', '[]'))
                if any(name in obj.data.attributes for name in names):
                    original_mesh = obj.data
                    copy = original_mesh.copy()
                    meshes.append((obj, original_mesh, copy))
                    obj.data = copy
                    # The exporter can ship unused color attributes by default.
                    # Internal shader masks must never become glTF vertex colors.
                    for name in names:
                        attr = copy.attributes.get(name)
                        if attr:
                            copy.attributes.remove(attr)
            for slot in obj.material_slots if obj.type == 'MESH' else ():
                original = slot.material
                if not original or not original.get(OWNED):
                    continue
                if original not in cache:
                    fallback = _fallback(original['c3d_material_source'], original)
                    cache[original] = fallback
                    temporary.append(fallback)
                    lost.append(original.name)
                link = slot.link
                slot.link = 'OBJECT'
                slots.append((slot, link, slot.material))
                slot.material = cache[original]
        yield dict(mode='bake-free PBR fallback', materials=lost,
                   lost=['subsurface scattering', 'procedural color/roughness masks',
                         'micro pores/weave/strand normals', 'cornea coat and lid/tear shading',
                         'iris pigment/limbal/fiber shading and eye-linked catchlights',
                         'hair sheen/translucency/anisotropy', 'fabric sheen/fuzz',
                         'separate AO/emission/metallic controls'],
                   kept=['authored base-color/alpha textures', 'skin reflectance factor',
                         'authored normal maps', 'scalar roughness and authored roughness maps']) if lost else None
    finally:
        for obj, hide, selected in hidden:
            obj.hide_set(hide)
            obj.select_set(selected)
        for slot, link, material in reversed(slots):
            slot.material, slot.link = material, link
        for obj, original, copy in reversed(meshes):
            obj.data = original
            bpy.data.meshes.remove(copy)
        for mat in temporary:
            bpy.data.materials.remove(mat)
