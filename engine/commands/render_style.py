"""Scene-stored looks. All rendering overrides are temporary, including on failure."""
from contextlib import contextmanager
import json
import math

import bpy
import bmesh
import numpy as np

from . import command
from ..filmstyle import STYLES, style_name, palette, LIGHT_MASSES

CONFIG_PROP = 'char3d_render_style'
# CPU Eevee measurements are documented in AGENTS.md. Keep these separate
# from machine calibration so a styled movie cannot inflate the baseline twice.
COST = {'none': 1.0, 'anime': 1.2, 'clay': 1.0, 'film': 1.1, 'noir': 1.05, 'vintage': 1.05,
        'animated_film': 1.25}
DEFAULTS = {
    'anime': dict(contrast=1.04, saturation=1.12),
    'clay': dict(contrast=1.0, saturation=1.0),
    'film': dict(contrast=1.12, saturation=0.94),
    'noir': dict(contrast=1.5, saturation=0.0),
    'vintage': dict(contrast=0.82, saturation=0.72, temperature=0.18),
    'animated_film': dict(contrast=1.08, saturation=1.12),
}


def get_config(sc):
    return json.loads(sc[CONFIG_PROP]) if sc.get(CONFIG_PROP) else None


def cost_factor(sc, engine):
    cfg = get_config(sc)
    if not cfg or engine == 'BLENDER_WORKBENCH' or cfg['strength'] == 0:
        return 1.0
    factor = COST[cfg['style']]
    if cfg['style'] == 'anime' and not cfg['outline']:
        factor = 1.05
    elif cfg['outline'] and cfg['style'] != 'anime':
        factor += 0.2
    return 1 + (factor - 1) * cfg['strength']


def _number(value, name, lo, hi):
    value = float(value)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{name} must be finite and between {lo} and {hi}')
    return value


@command('render_style')
def render_style(style='none', strength=1.0, outline=None, grade=None, letterbox=None):
    """Store a reversible render look; none removes it without touching scene settings."""
    style = style_name(style)
    strength = _number(strength, 'strength', 0, 1)
    grades = dict(DEFAULTS.get(style, {}))
    limits = dict(exposure=(-8, 8), contrast=(0, 3), saturation=(0, 3),
                  temperature=(-1, 1), tint=(-1, 1))
    if grade is not None:
        if not isinstance(grade, dict) or set(grade) - set(limits) - {'teal_orange'}:
            raise ValueError('grade accepts exposure, contrast, saturation, temperature, tint, teal_orange')
        for key, value in grade.items():
            grades[key] = bool(value) if key == 'teal_orange' else _number(value, key, *limits[key])
    if outline is not None and not isinstance(outline, bool):
        raise ValueError('outline must be true, false or null (anime default: true)')
    aspect = 2.39 if letterbox is True else 0.0 if letterbox in (None, False) else _number(letterbox, 'letterbox aspect', 1, 4)
    sc = bpy.context.scene
    if style == 'none':
        if CONFIG_PROP in sc:
            del sc[CONFIG_PROP]
        return {'style': 'none', 'strength': 0.0, 'cost_factor': 1.0}
    cfg = dict(style=style, strength=strength, outline=(style == 'anime') if outline is None else outline,
               grade=grades, letterbox=aspect)
    sc[CONFIG_PROP] = json.dumps(cfg)
    return {**cfg, 'cost_factor': cost_factor(sc, 'BLENDER_EEVEE'),
            'outline_method': 'inverted hull (opaque meshes only)' if cfg['outline'] else None}


def _input(tree, target, source):
    if source.is_linked:
        tree.links.new(source.links[0].from_socket, target)
    else:
        target.default_value = source.default_value


def _styled_material(original, cfg, engine, materials, groups, images, filtered):
    if original and original.get('c3d_vrm_material'):
        return original
    role=original.get('c3d_toon_role') if original else None
    if role:cfg={**cfg,'_toon_role':role}
    if original and original.get('c3d_toon_mouth'):cfg={**cfg,'_toon_mouth':True}
    toon_skin=original and original.get('c3d_toon_role')=='skin'
    enhanced_skin=original and original.get('c3d_material_role')=='skin'
    if toon_skin or enhanced_skin:
        # The same scan must keep its pigment when a toon look is applied to
        # either a realistically proportioned mesh or a flattened toon mesh.
        gain=original.get('c3d_toon_scan_style_gain',1.)
        if enhanced_skin:
            profile=json.loads(original.get('c3d_material_profile','{}'))
            gain=max(.00001,profile.get('albedo_gain',1.))**-.5
        cfg={**cfg,'_toon_skin':True,'_toon_head_height':original.get('c3d_toon_head_height',.23),
             '_toon_scan_style_gain':gain}
    mat = original.copy() if original else bpy.data.materials.new('__c3d_style_material')
    materials.append(mat)
    mat.use_nodes = True
    copies = {}

    def copy_groups(tree):
        # MPFB skin lives in nested groups. Copy the entire referenced graph so
        # group inputs, texture coordinates, alpha and animation remain connected.
        for node in list(tree.nodes):
            if node.type == 'GROUP' and node.node_tree:
                source = node.node_tree
                if source not in copies:
                    copy = source.copy()
                    groups.append(copy)
                    copies[source] = copy
                    copy_groups(copy)
                node.node_tree = copies[source]
    copy_groups(mat.node_tree)
    protected = _protected_colors(mat.node_tree) if cfg['style'] == 'animated_film' else set()
    visited = set()

    def visit(tree):
        if tree in visited:
            return
        visited.add(tree)
        for node in list(tree.nodes):
            if node.type == 'GROUP' and node.node_tree:
                visit(node.node_tree)
        if cfg['style'] == 'animated_film' and not _eye_material(mat.name):
            _filter_colors(tree, cfg, images, filtered, mat.name, protected)
        for bsdf in list(tree.nodes):
            if bsdf.type != 'BSDF_PRINCIPLED':
                continue
            consumers = [link.to_socket for link in bsdf.outputs['BSDF'].links]
            if consumers:
                if (cfg.get('_toon_skin') or role=='hair') and cfg['style'] in ('anime','animated_film'):
                    if cfg.get('_toon_skin'):
                        _toon_skin_response(tree,bsdf,cfg.get('_toon_scan_style_gain',1.))
                        if role=='skin':
                            warmth=tree.nodes.new('ShaderNodeHueSaturation')
                            # Retain the measured Round 4b pigment response.
                            # A Round 7 +4% value / warm-hue trial increased
                            # saturation but lowered dark cheek Y' below .33.
                            warmth.inputs['Saturation'].default_value=1.04
                            _input(tree,warmth.inputs['Color'],bsdf.inputs['Base Color'])
                            tree.links.new(warmth.outputs[0],bsdf.inputs['Base Color'])
                    if cfg.get('_skin_aovs'):
                        color_name,mask_name=cfg['_skin_aovs']
                        color_out=tree.nodes.new('ShaderNodeOutputAOV');color_out.aov_name=color_name
                        _input(tree,color_out.inputs['Color'],bsdf.inputs['Base Color'])
                        mask_out=tree.nodes.new('ShaderNodeOutputAOV');mask_out.aov_name=mask_name
                        mask_out.inputs['Value'].default_value=1.
                styled = (_animated_shader(tree, bsdf, cfg, mat.name, engine)
                          if cfg['style'] == 'animated_film' else _styled_shader(tree, bsdf, cfg, engine))
                for socket in consumers:
                    tree.links.new(styled, socket)

    visit(mat.node_tree)
    return mat


def _toon_skin_response(tree,bsdf,style_gain=1.):
    """Illustrative pigment response under the compressed light ramps.

    A bounded monotone value lift keeps dark tones readable. Every RGB channel
    receives the same scalar; pigment hue/saturation are never desaturated.
    """
    nodes,links=tree.nodes,tree.links
    source=nodes.new('ShaderNodeVectorMath');source.operation='SCALE'
    _input(tree,source.inputs[0],bsdf.inputs['Base Color']);source.inputs['Scale'].default_value=style_gain
    luminance=nodes.new('ShaderNodeRGBToBW');links.new(source.outputs[0],luminance.inputs[0])
    target=nodes.new('ShaderNodeMath');target.operation='MULTIPLY_ADD'
    links.new(luminance.outputs[0],target.inputs[0]);target.inputs[1].default_value=.65;target.inputs[2].default_value=.09
    floor=nodes.new('ShaderNodeMath');floor.operation='MAXIMUM';floor.inputs[1].default_value=.001
    links.new(luminance.outputs[0],floor.inputs[0])
    gain=nodes.new('ShaderNodeMath');gain.operation='DIVIDE';links.new(target.outputs[0],gain.inputs[0]);links.new(floor.outputs[0],gain.inputs[1])
    minimum=nodes.new('ShaderNodeMath');minimum.operation='MAXIMUM';minimum.inputs[1].default_value=1.
    links.new(gain.outputs[0],minimum.inputs[0])
    maximum=nodes.new('ShaderNodeMath');maximum.operation='MINIMUM';maximum.inputs[1].default_value=2.2
    links.new(minimum.outputs[0],maximum.inputs[0])
    scale=nodes.new('ShaderNodeVectorMath');scale.operation='SCALE'
    links.new(source.outputs[0],scale.inputs[0]);links.new(maximum.outputs[0],scale.inputs['Scale'])
    links.new(scale.outputs[0],bsdf.inputs['Base Color'])


def _protected_colors(root):
    """Follow opacity/emission dependencies across group instance boundaries.

    A grayscale Color output can be an opacity mask, including when the same
    image also supplies albedo. Leave that sampler untouched rather than blur a
    silhouette. Alpha outputs remain on the original sampler in all cases.
    """
    protected, seen = set(), set()

    def matching(sockets, source):
        return next((s for s in sockets if s.identifier == source.identifier), None)

    def upstream(socket, parents):
        for link in socket.links:
            source = link.from_socket
            key = source.as_pointer(), tuple(n.as_pointer() for n in parents)
            if key in seen:
                continue
            seen.add(key)
            node = source.node
            if node.type == 'GROUP' and node.node_tree:
                for output in node.node_tree.nodes:
                    if output.type == 'GROUP_OUTPUT':
                        target = matching(output.inputs, source)
                        if target is not None:
                            upstream(target, parents+(node,))
            elif node.type == 'GROUP_INPUT':
                if parents:
                    target = matching(parents[-1].inputs, source)
                    if target is not None:
                        upstream(target, parents[:-1])
            else:
                if (node.type == 'TEX_IMAGE' and source.name == 'Color') or node.type == 'TEX_NOISE':
                    protected.add(node)
                for input in node.inputs:
                    upstream(input, parents)

    def collect(tree, parents=()):
        for node in tree.nodes:
            if node.type == 'GROUP' and node.node_tree:
                collect(node.node_tree, parents+(node,))
            elif node.type == 'BSDF_PRINCIPLED':
                for name in ('Alpha', 'Emission Color', 'Emission Strength'):
                    upstream(node.inputs[name], parents)
            elif node.type == 'MIX_SHADER':
                upstream(node.inputs[0], parents)
            elif node.type == 'EMISSION' or node.type.startswith('BSDF_'):
                for input in node.inputs:
                    upstream(input, parents)
    collect(root)
    return protected


def _eye_material(name):
    name = name.lower()
    words = name.replace('_', '.').replace('-', '.').split('.')
    return any(w in name for w in ('cornea', 'iris', 'high-poly')) or any(w in ('eye', 'eyes') for w in words)


def _filter_colors(tree, cfg, images, filtered, name, protected):
    """Low-pass color only. Original alpha, normal/data maps and UVs stay intact.

    Cache per source image across all copied materials. The temporary image is
    sampled with the original UV graph: no generated-coordinate texture seams.
    """
    for noise in tree.nodes:
        if noise.type == 'TEX_NOISE' and noise not in protected and not noise.inputs['Detail'].is_linked:
            noise.inputs['Detail'].default_value *= 1 - .9*cfg['strength']
    limit = 512 if any(w in name.lower() for w in ('body', 'skin')) else 256
    for node in list(tree.nodes):
        if node.type != 'TEX_IMAGE' or node in protected or not node.image or not node.outputs['Color'].is_linked:
            continue
        image = node.image
        if image.colorspace_settings.name not in ('sRGB', 'Linear Rec.709') or image.source not in ('FILE', 'GENERATED'):
            continue
        if max(image.size) <= limit:
            continue
        key = image, limit
        if key not in filtered:
            copy = image.copy()
            images.append(copy)
            copy.name = '__c3d_style_color'
            # Image.copy copies the datablock, not unsaved pixel edits. Carry
            # painted/generated buffers across before filtering the temporary.
            if image.is_dirty or image.source == 'GENERATED':
                pixels = np.empty(len(image.pixels), dtype=np.float32)
                image.pixels.foreach_get(pixels)
                copy.pixels.foreach_set(pixels)
                del pixels
            scale = limit / max(image.size)
            copy.scale(max(1, round(image.size[0]*scale)), max(1, round(image.size[1]*scale)))
            filtered[key] = copy
        color_links = [link.to_socket for link in node.outputs['Color'].links]
        soft = tree.nodes.new('ShaderNodeTexImage')
        soft.image = filtered[key]
        soft.interpolation, soft.extension, soft.projection = 'Linear', node.extension, node.projection
        soft.projection_blend = node.projection_blend
        _input(tree, soft.inputs['Vector'], node.inputs['Vector'])
        mix = tree.nodes.new('ShaderNodeMixRGB')
        mix.inputs[0].default_value = .94*cfg['strength']
        tree.links.new(node.outputs['Color'], mix.inputs[1])
        tree.links.new(soft.outputs['Color'], mix.inputs[2])
        for socket in color_links:
            tree.links.new(mix.outputs[0], socket)


def _head_anchor(sc, rig, helpers):
    """An anatomical coordinate frame that follows the animated head bone."""
    from mathutils import Matrix
    from .anim import semantic_map
    from .gaze import head_frame
    bones = semantic_map(rig)
    bone = bones.get('head')
    if not {'head', 'hips', 'thigh.L', 'thigh.R'} <= bones.keys():
        return None
    center, orient = head_frame(rig)
    parent = bpy.data.objects.new('__c3d_style_head_bone', None)
    sc.collection.objects.link(parent)
    helpers.append(parent)
    follow = parent.constraints.new('COPY_TRANSFORMS')
    follow.target, follow.subtarget = rig, bone
    anchor = bpy.data.objects.new('__c3d_style_cheeks', None)
    sc.collection.objects.link(anchor)
    helpers.append(anchor)
    anchor.parent = parent
    transform = Matrix.LocRotScale(center, orient, (1, 1, 1))
    anchor.matrix_basis = (rig.matrix_world @ rig.pose.bones[bone].matrix).inverted() @ transform
    return anchor


def _blush(tree, bsdf, anchor, strength):
    # Two broad ellipsoids in meters, never UV-dependent; follow face animation.
    nodes, links = tree.nodes, tree.links
    coord = nodes.new('ShaderNodeTexCoord')
    coord.object = anchor
    masks = []
    for side in (-1, 1):
        offset = nodes.new('ShaderNodeVectorMath')
        offset.operation = 'SUBTRACT'
        links.new(coord.outputs['Object'], offset.inputs[0])
        offset.inputs[1].default_value = (side*.047, -.077, -.012)
        ellipse = nodes.new('ShaderNodeVectorMath')
        ellipse.operation = 'MULTIPLY'
        links.new(offset.outputs[0], ellipse.inputs[0])
        ellipse.inputs[1].default_value = (1/.034, 1/.055, 1/.026)
        distance = nodes.new('ShaderNodeVectorMath')
        distance.operation = 'LENGTH'
        links.new(ellipse.outputs[0], distance.inputs[0])
        falloff = nodes.new('ShaderNodeMapRange')
        falloff.interpolation_type = 'SMOOTHERSTEP'
        falloff.inputs['From Max'].default_value = 1.4
        falloff.inputs['To Min'].default_value = .13*strength
        falloff.inputs['To Max'].default_value = 0
        links.new(distance.outputs['Value'], falloff.inputs[0])
        masks.append(falloff.outputs[0])
    add = nodes.new('ShaderNodeMath')
    add.operation = 'ADD'
    links.new(masks[0], add.inputs[0])
    links.new(masks[1], add.inputs[1])
    mix = nodes.new('ShaderNodeMixRGB')
    links.new(add.outputs[0], mix.inputs[0])
    _input(tree, mix.inputs[1], bsdf.inputs['Base Color'])
    mix.inputs[2].default_value = (.76, .22, .20, 1)
    links.new(mix.outputs[0], bsdf.inputs['Base Color'])


def _animated_shader(tree, bsdf, cfg, name, engine):
    """Soft light masses shared by photographed humans and procedural scenery.

    Read linked Principled inputs generically, including inside enhanced skin
    groups. Preserve optical eyes, alpha cards and authored practical emission.
    """
    nodes, links = tree.nodes, tree.links
    k = cfg['strength']
    if cfg.get('_toon_mouth'):
        from .toon7_mouth import styled_shader
        return styled_shader(tree,bsdf,cfg['strength'])
    if cfg.get('_toon_role') in ('hair','skin'):
        from .toon_render import key_bands
        return key_bands(tree,bsdf,cfg)
    name = name.lower()
    eye = _eye_material(name)
    if any(w in name for w in ('teeth', 'tongue', 'lash')):
        return bsdf.outputs['BSDF']
    skin = any(w in name for w in ('skin', 'body')) or (
        not bsdf.inputs['Subsurface Weight'].is_linked and bsdf.inputs['Subsurface Weight'].default_value > .12)
    hair = any(w in name for w in ('hair', 'beard', 'ponytail', 'braid', 'bob0', 'short0', 'long0', 'afro', 'eyebrow'))
    color = nodes.new('ShaderNodeHueSaturation')
    color.inputs['Saturation'].default_value = 1 if cfg.get('_toon_skin') else 1 + (.22 if eye else -.10 if skin else .10)*k
    _input(tree, color.inputs['Color'], bsdf.inputs['Base Color'])
    color.inputs['Value'].default_value = 1 if cfg.get('_toon_skin') else 1 + (.05 if skin else 0)*k
    links.new(color.outputs[0], bsdf.inputs['Base Color'])
    if skin and cfg.get('_head') and not cfg.get('_toon_skin'):
        _blush(tree, bsdf, cfg['_head'], k)
    if eye:
        # Retain full-resolution iris/limbal detail and enhanced layered corneas.
        if not bsdf.inputs['Roughness'].is_linked:
            rough = nodes.new('ShaderNodeMath')
            rough.operation = 'MULTIPLY_ADD'
            _input(tree, rough.inputs[0], bsdf.inputs['Roughness'])
            rough.inputs[1].default_value = 1-k
            rough.inputs[2].default_value = min(.18, bsdf.inputs['Roughness'].default_value)*k
            links.new(rough.outputs[0], bsdf.inputs['Roughness'])
        return bsdf.outputs['BSDF']
    optical = bsdf.inputs['Metallic'].default_value > .25 or bsdf.inputs['Transmission Weight'].default_value > .1 or 'water' in name
    rough = nodes.new('ShaderNodeMath')
    rough.operation = 'MULTIPLY_ADD'
    _input(tree, rough.inputs[0], bsdf.inputs['Roughness'])
    rough.inputs[1].default_value = 1 - .8*k
    rough.inputs[2].default_value = (.20 if optical else .28 if hair else .42)*k
    links.new(rough.outputs[0], bsdf.inputs['Roughness'])
    if bsdf.inputs['Normal'].is_linked:
        normal = nodes.new('ShaderNodeMixRGB')
        normal.inputs[0].default_value = .96*k
        _input(tree, normal.inputs[1], bsdf.inputs['Normal'])
        geometry = nodes.new('ShaderNodeNewGeometry')
        links.new(geometry.outputs['Normal'], normal.inputs[2])
        links.new(normal.outputs[0], bsdf.inputs['Normal'])
    # Cycles has no Shader-to-RGB. Use its physical soft terminator/SSS with the
    # same filtered albedo, palette, normal suppression and large softboxes.
    if engine == 'CYCLES':
        tint = nodes.new('ShaderNodeMixRGB')
        tint.blend_type = 'MULTIPLY'
        tint.inputs[0].default_value = .22*k
        _input(tree, tint.inputs[1], bsdf.inputs['Base Color'])
        tint.inputs[2].default_value = (*cfg['_palette'][1], 1)
        links.new(tint.outputs[0], bsdf.inputs['Base Color'])
        return bsdf.outputs['BSDF']
    diffuse = nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    diffuse.inputs['Roughness'].default_value = .65
    _input(tree, diffuse.inputs['Normal'], bsdf.inputs['Normal'])
    rgb = nodes.new('ShaderNodeShaderToRGB')
    links.new(diffuse.outputs[0], rgb.inputs[0])
    luma = nodes.new('ShaderNodeRGBToBW')
    links.new(rgb.outputs[0], luma.inputs[0])
    bands = nodes.new('ShaderNodeValToRGB')
    bands.color_ramp.interpolation = 'EASE'
    for el in list(bands.color_ramp.elements)[1:]:
        bands.color_ramp.elements.remove(el)
    for i, (x, y) in enumerate(LIGHT_MASSES):
        el = bands.color_ramp.elements[0] if i == 0 else bands.color_ramp.elements.new(x)
        el.position, el.color = x, (y, y, y, 1)
    # Compress HDR before the light ramp. A raw 0..1 ramp clips lit faces to
    # its last mass; the bounded coordinate retains shape in bright softboxes.
    denominator = nodes.new('ShaderNodeMath')
    denominator.operation = 'ADD'
    denominator.inputs[1].default_value = .8
    links.new(luma.outputs[0], denominator.inputs[0])
    exposure = nodes.new('ShaderNodeMath')
    exposure.operation = 'DIVIDE'
    links.new(luma.outputs[0], exposure.inputs[0])
    links.new(denominator.outputs[0], exposure.inputs[1])
    shape = nodes.new('ShaderNodeMath')
    shape.operation = 'POWER'
    shape.inputs[1].default_value = 1.6
    links.new(exposure.outputs[0], shape.inputs[0])
    links.new(shape.outputs[0], bands.inputs[0])
    inverse = nodes.new('ShaderNodeMath')
    inverse.operation = 'DIVIDE'
    inverse.inputs[0].default_value = 1.45
    links.new(denominator.outputs[0], inverse.inputs[1])
    continuous = nodes.new('ShaderNodeVectorMath')
    continuous.operation = 'SCALE'
    links.new(rgb.outputs[0], continuous.inputs[0])
    links.new(inverse.outputs[0], continuous.inputs['Scale'])
    mass = nodes.new('ShaderNodeMixRGB')
    mass.blend_type = 'MULTIPLY'
    mass.inputs[0].default_value = 1
    mass.inputs[2].default_value = (1.45, 1.45, 1.45, 1)
    links.new(bands.outputs[0], mass.inputs[1])
    gradient = nodes.new('ShaderNodeMixRGB')
    gradient.inputs[0].default_value = .86
    links.new(continuous.outputs[0], gradient.inputs[1])
    links.new(mass.outputs[0], gradient.inputs[2])
    tint = nodes.new('ShaderNodeValToRGB')
    tint.color_ramp.elements[0].position = .02
    tint.color_ramp.elements[0].color = (*cfg['_palette'][0], 1)
    tint.color_ramp.elements[1].position = .72
    tint.color_ramp.elements[1].color = (*cfg['_palette'][1], 1)
    links.new(shape.outputs[0], tint.inputs[0])
    shaded = nodes.new('ShaderNodeMixRGB')
    shaded.blend_type = 'MULTIPLY'
    shaded.inputs[0].default_value = .80
    links.new(gradient.outputs[0], shaded.inputs[1])
    links.new(tint.outputs[0], shaded.inputs[2])
    paint = nodes.new('ShaderNodeMixRGB')
    paint.blend_type = 'MULTIPLY'
    paint.inputs[0].default_value = 1
    _input(tree, paint.inputs[1], bsdf.inputs['Base Color'])
    links.new(shaded.outputs[0], paint.inputs[2])
    if skin:
        # Warm broad bounce in the lit shadow transition, never an unlit floor.
        bounce = nodes.new('ShaderNodeMixRGB')
        bounce.blend_type = 'MULTIPLY'
        bounce.inputs[0].default_value = .12
        links.new(paint.outputs[0], bounce.inputs[1])
        bounce.inputs[2].default_value = (1.18, .83, .78, 1)
        painted_color = bounce.outputs[0]
    else:
        painted_color = paint.outputs[0]
    # A continuous form gradient under the light masses rounds cheeks, cloth and
    # props together. Geometric normals remove photographic micro-normal noise;
    # the camera vector is live, so this remains smooth through camera/head moves.
    geometry = nodes.new('ShaderNodeNewGeometry')
    facing = nodes.new('ShaderNodeVectorMath')
    facing.operation = 'DOT_PRODUCT'
    links.new(geometry.outputs['Normal'], facing.inputs[0])
    links.new(geometry.outputs['Incoming'], facing.inputs[1])
    absolute = nodes.new('ShaderNodeMath')
    absolute.operation = 'ABSOLUTE'
    links.new(facing.outputs['Value'], absolute.inputs[0])
    form = nodes.new('ShaderNodeValToRGB')
    form.color_ramp.interpolation = 'EASE'
    form.color_ramp.elements[0].color = (*cfg['_palette'][0], 1)
    form.color_ramp.elements[1].position = .92
    form.color_ramp.elements[1].color = (1.04, 1., .96, 1)
    links.new(absolute.outputs[0], form.inputs[0])
    sculpt = nodes.new('ShaderNodeMixRGB')
    sculpt.blend_type = 'MULTIPLY'
    sculpt.inputs[0].default_value = .20 if cfg.get('_toon_skin') else .72 if skin else .46
    links.new(painted_color, sculpt.inputs[1])
    links.new(form.outputs[0], sculpt.inputs[2])
    # Short-range AO restores contacts/creases after texture noise is removed.
    # No extra render pass or render-sample increase.
    ao = nodes.new('ShaderNodeAmbientOcclusion')
    ao.samples = 4
    ao.inputs['Distance'].default_value = min(.025,cfg.get('_toon_head_height',.23)*.08) if cfg.get('_toon_skin') else .12
    contact = nodes.new('ShaderNodeMixRGB')
    contact.blend_type = 'MULTIPLY'
    contact.inputs[0].default_value = .10 if cfg.get('_toon_skin') else .28
    links.new(sculpt.outputs[0], contact.inputs[1])
    links.new(ao.outputs['AO'], contact.inputs[2])
    painted_color=contact.outputs[0]
    if cfg.get('_toon_skin'):
        # Recover one illumination value. Per-channel palette/floor operations
        # otherwise turn warm flat pigment grey/pink. Keep the form and AO but
        # apply their scalar to the original pigment, with an albedo-relative fill.
        lit=nodes.new('ShaderNodeRGBToBW');links.new(painted_color,lit.inputs[0])
        base=nodes.new('ShaderNodeRGBToBW');_input(tree,base.inputs[0],bsdf.inputs['Base Color'])
        denominator=nodes.new('ShaderNodeMath');denominator.operation='MAXIMUM';denominator.inputs[1].default_value=.00001
        links.new(base.outputs[0],denominator.inputs[0])
        ratio=nodes.new('ShaderNodeMath');ratio.operation='DIVIDE'
        links.new(lit.outputs[0],ratio.inputs[0]);links.new(denominator.outputs[0],ratio.inputs[1])
        minimum=nodes.new('ShaderNodeMath');minimum.operation='MAXIMUM';minimum.inputs[1].default_value=.40
        links.new(ratio.outputs[0],minimum.inputs[0])
        pigment=nodes.new('ShaderNodeVectorMath');pigment.operation='SCALE'
        _input(tree,pigment.inputs[0],bsdf.inputs['Base Color']);links.new(minimum.outputs[0],pigment.inputs['Scale'])
        painted_color=pigment.outputs[0]
    soft = nodes.new('ShaderNodeEmission')
    links.new(painted_color, soft.inputs['Color'])
    painted = soft.outputs[0]
    emission, emitted_color = bsdf.inputs['Emission Strength'], bsdf.inputs['Emission Color']
    if (emission.is_linked or emission.default_value > 0) and (emitted_color.is_linked or max(emitted_color.default_value[:3]) > 0):
        glow = nodes.new('ShaderNodeEmission')
        _input(tree, glow.inputs['Color'], emitted_color)
        _input(tree, glow.inputs['Strength'], emission)
        add = nodes.new('ShaderNodeAddShader')
        links.new(painted, add.inputs[0])
        links.new(glow.outputs[0], add.inputs[1])
        painted = add.outputs[0]
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    alpha = nodes.new('ShaderNodeMixShader')
    _input(tree, alpha.inputs[0], bsdf.inputs['Alpha'])
    links.new(transparent.outputs[0], alpha.inputs[1])
    links.new(painted, alpha.inputs[2])
    blend = nodes.new('ShaderNodeMixShader')
    blend.inputs[0].default_value = (.55 if optical else .72 if hair else .88)*k
    links.new(bsdf.outputs[0], blend.inputs[1])
    links.new(alpha.outputs[0], blend.inputs[2])
    return blend.outputs[0]


def _styled_shader(tree, bsdf, cfg, engine):
    nodes, links = tree.nodes, tree.links
    if cfg.get('_toon_mouth') and cfg['style']=='anime':
        from .toon7_mouth import styled_shader
        return styled_shader(tree,bsdf,cfg['strength'])
    if cfg['style']=='anime' and cfg.get('_toon_role') in ('skin','clothes','hair'):
        from .toon_render import key_bands
        return key_bands(tree,bsdf,cfg)
    if cfg['style'] == 'clay':
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        shader.inputs['Base Color'].default_value = (0.48, 0.30, 0.20, 1)
        shader.inputs['Roughness'].default_value = 1.0
        shader.inputs['Specular IOR Level'].default_value = 0.15
        _input(tree, shader.inputs['Alpha'], bsdf.inputs['Alpha'])
        styled = shader.outputs[0]
    else:
        if engine == 'CYCLES':
            shader = nodes.new('ShaderNodeBsdfToon')
            _input(tree, shader.inputs['Color'], bsdf.inputs['Base Color'])
            shader.inputs['Size'].default_value = 0.65
            shader.inputs['Smooth'].default_value = 0.04
            styled = shader.outputs[0]
        else:
            diffuse = nodes.new('ShaderNodeBsdfDiffuse')
            diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
            _input(tree, diffuse.inputs['Normal'], bsdf.inputs['Normal'])
            rgb = nodes.new('ShaderNodeShaderToRGB')
            links.new(diffuse.outputs[0], rgb.inputs[0])
            ramp = nodes.new('ShaderNodeValToRGB')
            ramp.color_ramp.interpolation = 'CONSTANT'
            values=(.62,.86) if cfg.get('_toon_skin') else (.42,.78)
            for el, pos, value in zip(ramp.color_ramp.elements, (0, 0.45), values):
                el.position, el.color = pos, (value, value, value, 1)
            el = ramp.color_ramp.elements.new(0.85)
            el.color = (1.05, 1.05, 1.05, 1)
            links.new(rgb.outputs[0], ramp.inputs[0])
            color = nodes.new('ShaderNodeMixRGB')
            color.blend_type = 'MULTIPLY'
            color.inputs[0].default_value = 1
            _input(tree, color.inputs[1], bsdf.inputs['Base Color'])
            links.new(ramp.outputs[0], color.inputs[2])
            shader = nodes.new('ShaderNodeEmission')
            links.new(color.outputs[0], shader.inputs['Color'])
            styled = shader.outputs[0]
        # Alpha comes from the original texture graph, including MPFB hair cards.
        alpha = nodes.new('ShaderNodeMixShader')
        transparent = nodes.new('ShaderNodeBsdfTransparent')
        _input(tree, alpha.inputs[0], bsdf.inputs['Alpha'])
        links.new(transparent.outputs[0], alpha.inputs[1])
        links.new(styled, alpha.inputs[2])
        styled = alpha.outputs[0]
    # A full-strength look does not need the original BSDF evaluated at all.
    # In particular this avoids retaining MPFB's expensive skin SSS branch.
    if cfg['strength'] == 1:
        return styled
    mix = nodes.new('ShaderNodeMixShader')
    mix.inputs[0].default_value = cfg['strength']
    links.new(bsdf.outputs['BSDF'], mix.inputs[1])
    links.new(styled, mix.inputs[2])
    return mix.outputs[0]


def _opaque(obj):
    # Thin alpha cards and facial inserts must never acquire an opaque black shell.
    if obj.get('c3d_toon_mouth'):return False
    if any(word in obj.name.lower() for word in ('eye', 'brow', 'lash', 'teeth', 'tongue', 'hair', 'beard')):
        return False
    for slot in obj.material_slots:
        mat = slot.material
        if mat and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_TRANSPARENT':
                    return False
                if node.type == 'BSDF_PRINCIPLED':
                    alpha = node.inputs['Alpha']
                    if alpha.is_linked or alpha.default_value < 1:
                        return False
    return True


def _mix(tree, image, value, blend='MULTIPLY'):
    n = tree.nodes.new('ShaderNodeMix')
    n.data_type, n.blend_type = 'RGBA', blend
    n.inputs[0].default_value = 1
    tree.links.new(image, n.inputs[6])
    if hasattr(value, 'node'):
        tree.links.new(value, n.inputs[7])
    else:
        n.inputs[7].default_value = value
    return n.outputs[2]


def _compositor(sc, cfg, images, tree):
    if not any(getattr(s, 'in_out', None) == 'OUTPUT' for s in tree.interface.items_tree):
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    nodes, links = tree.nodes, tree.links
    # Extend a COPY of the user's graph. Nesting an entire scene compositor in
    # a Group can hide Render Layers from Blender 5.2's render dependency scan,
    # producing black animation frames without ever rendering the scene.
    output = next((n for n in nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output), None)
    socket = (output.inputs.get('Image') or output.inputs[0]) if output else None
    if socket and socket.is_linked:
        image = socket.links[0].from_socket
    else:
        source = nodes.new('CompositorNodeRLayers')
        source.scene = sc
        image = source.outputs.get('Image') or source.outputs[0]
    original = image
    grade, style, strength = cfg['grade'], cfg['style'], cfg['strength']
    exp = nodes.new('CompositorNodeExposure')
    exp.inputs['Exposure'].default_value = grade.get('exposure', 0)
    links.new(image, exp.inputs['Image'])
    image = exp.outputs[0]
    sat = nodes.new('CompositorNodeHueSat')
    sat.inputs['Saturation'].default_value = grade.get('saturation', 1)
    links.new(image, sat.inputs['Image'])
    image = sat.outputs[0]
    contrast = nodes.new('CompositorNodeBrightContrast')
    contrast.inputs['Contrast'].default_value = (grade.get('contrast', 1) - 1) * 50
    links.new(image, contrast.inputs['Image'])
    image = contrast.outputs[0]
    temp, tint = grade.get('temperature', 0), grade.get('tint', 0)
    image = _mix(tree, image, (1 + temp * .18 + tint * .06, 1 - tint * .12, 1 - temp * .18 + tint * .06, 1))
    if grade.get('teal_orange'):
        balance = nodes.new('CompositorNodeColorBalance')
        amount = float(grade['teal_orange'])
        balance.inputs['Color Lift'].default_value = (1-.03*amount, 1+.006*amount, 1+.018*amount, 1)
        balance.inputs['Color Gain'].default_value = (1+.04*amount, 1+.008*amount, 1-.03*amount, 1)
        links.new(image, balance.inputs['Image'])
        image = balance.outputs[0]
    effects = cfg.get('effects')
    if (effects and effects['bloom'] > 0) or (effects is None and style in ('film', 'animated_film')):
        glow = nodes.new('CompositorNodeGlare')
        glow.inputs['Type'].default_value = 'Fog Glow'
        glow.inputs['Quality'].default_value = 'Low'
        glow.inputs['Threshold'].default_value = 1.3
        glow.inputs['Strength'].default_value = effects['bloom'] if effects else .08 if style == 'animated_film' else .08
        links.new(image, glow.inputs['Image'])
        image = glow.outputs[0]
    w = round(sc.render.resolution_x * sc.render.resolution_percentage / 100)
    h = round(sc.render.resolution_y * sc.render.resolution_percentage / 100)

    def texture(name, pixels):
        img = bpy.data.images.new(name, width=w, height=h, float_buffer=True)
        images.append(img)
        img.colorspace_settings.name = 'Non-Color'
        img.pixels.foreach_set(pixels.astype(np.float32).ravel())
        img.update()
        node = nodes.new('CompositorNodeImage')
        node.image = img
        return node.outputs[0]

    if effects is not None or style in ('film', 'noir', 'vintage'):
        y, x = np.mgrid[-1:1:complex(h), -1:1:complex(w)]
        amount = effects['vignette'] if effects else .24 if style == 'noir' else .17 if style == 'film' else .11
        mask = np.ones((h, w, 4), dtype=np.float32)
        mask[:, :, :3] = (1 - amount * np.clip((x*x + y*y) / 1.5, 0, 1))[:, :, None]
        image = _mix(tree, image, texture('__c3d_style_vignette', mask))
        noise = np.ones((h, w, 4), dtype=np.float32)
        rng = np.random.default_rng(733 + sc.frame_current)
        noise[:, :, :3] = rng.normal(0, effects['grain'] if effects else .008 if style == 'noir' else .004, (h, w, 1))
        image = _mix(tree, image, texture('__c3d_style_grain', noise), 'ADD')
        if effects and effects['lifted_blacks']:
            lift = effects['lifted_blacks']
            color = (lift, lift, lift, 0) if style == 'noir' else (lift, lift*.9, lift*.85, 0)
            image = _mix(tree, image, color, 'ADD')
        elif style == 'vintage':
            image = _mix(tree, image, (.025, .019, .012, 0), 'ADD')
        if effects and effects['chromatic_aberration']:
            lens = nodes.new('CompositorNodeLensdist')
            lens.inputs['Dispersion'].default_value = effects['chromatic_aberration']
            links.new(image, lens.inputs['Image'])
            image = lens.outputs[0]
    blend = nodes.new('ShaderNodeMix')
    blend.data_type = 'RGBA'
    blend.inputs[0].default_value = strength
    links.new(original, blend.inputs[6])
    links.new(image, blend.inputs[7])
    image = blend.outputs[2]
    if cfg['letterbox']:
        mask = np.ones((h, w, 4), dtype=np.float32)
        rows = max(0, int(round((h - w / cfg['letterbox']) / 2)))
        if rows:
            mask[:rows, :, :3] = mask[-rows:, :, :3] = 0
        image = _mix(tree, image, texture('__c3d_style_bars', mask))
    output = output or nodes.new('NodeGroupOutput')
    if cfg.get('_skin_aovs'):
        # The scene's per-channel contrast can crush a dark pigment's blue
        # channel, while highlights lose saturation. Keep its graded value but
        # restore pigment H/S on the actual skin coverage, including AA edges.
        layers=nodes.new('CompositorNodeRLayers');layers.scene=sc
        pigment=nodes.new('CompositorNodeSeparateColor');pigment.mode='HSV'
        shaded=nodes.new('CompositorNodeSeparateColor');shaded.mode='HSV'
        links.new(layers.outputs[cfg['_skin_aovs'][0]],pigment.inputs[0])
        links.new(image,shaded.inputs[0])
        restored=nodes.new('CompositorNodeCombineColor');restored.mode='HSV'
        links.new(pigment.outputs[0],restored.inputs[0]);links.new(pigment.outputs[1],restored.inputs[1])
        links.new(shaded.outputs[2],restored.inputs[2])
        if 'Alpha' in restored.inputs and 'Alpha' in shaded.outputs:
            links.new(shaded.outputs['Alpha'],restored.inputs['Alpha'])
        skin=nodes.new('ShaderNodeMix');skin.data_type='RGBA'
        links.new(layers.outputs[cfg['_skin_aovs'][1]],skin.inputs[0])
        links.new(image,skin.inputs[6]);links.new(restored.outputs[0],skin.inputs[7]);image=skin.outputs[2]
    links.new(image, output.inputs.get('Image') or output.inputs[0])
    return tree


@contextmanager
def applied_style(sc):
    from .vrm_render import applied
    with applied(sc, get_config(sc)):
        with _applied_style(sc) as images:
            yield images


@contextmanager
def _applied_style(sc):
    """Apply only for the render duration; user datablocks are never edited."""
    from .cinematic import compositor_config
    cfg = get_config(sc)
    if cfg and cfg['strength'] == 0:
        cfg = None
    post = compositor_config(sc, cfg)
    if not post or post['strength'] == 0 or sc.render.engine == 'BLENDER_WORKBENCH':
        yield []
        return
    cfg = cfg or dict(style='cinematic', strength=1., outline=False)
    slots, materials, meshes, hulls, images, groups = [], [], [], [], [], []
    skin_aovs=[]
    # Explicit artistic colour grades still take precedence over the default
    # pigment protection (including a deliberate monochrome override).
    default_grade=DEFAULTS.get(cfg['style'],{})
    lock_pigment=all(cfg.get('grade',{}).get(k,default_grade.get(k,v))==default_grade.get(k,v)
                     for k,v in dict(saturation=1.,temperature=0.,tint=0.,teal_orange=False).items())
    if cfg['style'] in ('anime','animated_film') and lock_pigment and any(
            slot.material and (slot.material.get('c3d_toon_role') in ('skin','hair') or slot.material.get('c3d_material_role')=='skin')
            for obj in sc.objects if obj.type=='MESH' and not obj.hide_render for slot in obj.material_slots):
        names=[]
        for base,kind in (('__c3d_skin_pigment','COLOR'),('__c3d_skin_coverage','VALUE')):
            name=base;index=0
            while any(layer.aovs.get(name) for layer in sc.view_layers):
                index+=1;name=base+str(index)
            names.append(name)
            for layer in sc.view_layers:
                aov=layer.aovs.add();aov.name=name;aov.type=kind;skin_aovs.append((layer,aov))
        cfg={**cfg,'_skin_aovs':names}
        post={**post,'_skin_aovs':names}
    lights, helpers, worlds = [], [], []
    compositor = None
    normal_context = None
    old_group = sc.compositing_node_group
    old_compositing = sc.render.use_compositing
    view = sc.view_settings
    saved_view = {k: getattr(view, k) for k in ('view_transform', 'look', 'exposure', 'gamma')}
    try:
        if cfg['style'] in ('anime','animated_film'):
            from .toon_render import face_normal_proxies
            normal_context=face_normal_proxies(sc,cfg['style'])
            normal_context.__enter__()
        if cfg['style'] == 'film':
            view.view_transform = 'AgX'
            view.look = 'AgX - Medium High Contrast'
        if cfg['style'] == 'animated_film':
            view.view_transform = 'AgX'
            view.look = 'AgX - Medium High Contrast'
            from .cinematic import get_config as look_config
            look = (look_config(sc) or {}).get('preset')
            cfg = {**cfg, '_palette': palette(look)}
            # Enlarge existing softboxes, retain their motivated colors and saved
            # tracking/placement. The cinematic context runs first, so night stays
            # night and weather still controls outdoor exposure.
            from .cinematic import _cast, _classify_lights, _light_role
            cast = _cast(sc)
            _classify_lights(sc, cast)
            for obj in sc.objects:
                if obj.type != 'LIGHT' or obj.get('c3d_role') != 'light' or obj.data.type != 'AREA':
                    continue
                original = obj.data
                obj.data = original.copy()
                lights.append((obj, original))
                role = _light_role(obj, cast)
                k = cfg['strength']
                obj.data.size *= 1 + (.8 if role == 'fill' else .3)*k
                gain = {'key': 1.12, 'fill': .85, 'rim': 1.85}.get(role, 1.)
                obj.data.energy *= 1 + (gain-1)*k
                tint = cfg['_palette'][0 if role == 'fill' else 1]
                amount = (.58 if role == 'fill' else .25)*k
                obj.data.color = [v*(1-amount)+t*amount for v,t in zip(obj.data.color,tint)]
            if sc.world and sc.world.use_nodes:
                old_world = sc.world
                sc.world = old_world.copy()
                worlds.append((old_world, sc.world))
                nt = sc.world.node_tree
                for node in list(nt.nodes):
                    if node.type != 'BACKGROUND':
                        continue
                    color = nt.nodes.new('ShaderNodeHueSaturation')
                    color.inputs['Saturation'].default_value = 1 + .12*cfg['strength']
                    # Designed midnight blues keep distant scenery readable;
                    # blue_hour remains brighter through its own sky/tint values.
                    gain = 5. if look in ('night', 'blue_hour') else 1.08
                    color.inputs['Value'].default_value = 1 + (gain-1)*cfg['strength']
                    _input(nt, color.inputs['Color'], node.inputs['Color'])
                    nt.links.new(color.outputs[0], node.inputs['Color'])
        if cfg['style'] in ('anime','animated_film'):
            from .toon_render import key_light
            cfg={**cfg,'_toon_key':key_light(sc)}
        if cfg['style'] in ('anime', 'clay', 'animated_film') or cfg['outline']:
            cache, filtered, heads = {}, {}, {}
            black = None
            for obj in list(sc.objects):
                if obj.type != 'MESH' or obj.hide_render or obj.get('c3d_role') in ('weather', 'cinematic'):
                    continue
                hull = cfg['outline'] and _opaque(obj) and not any(s.material and s.material.get('c3d_vrm_material') for s in obj.material_slots)
                if not obj.material_slots:
                    old = obj.data
                    obj.data = old.copy()
                    meshes.append((obj, old, obj.data))
                    obj.data.materials.append(None)
                for slot in obj.material_slots if cfg['style'] in ('anime', 'clay', 'animated_film') else ():
                    orig = slot.material
                    local_cfg = cfg
                    if cfg['style'] == 'animated_film' and orig and any(w in orig.name.lower() for w in ('skin', 'body')):
                        rig = obj.find_armature()
                        if rig:
                            if rig not in heads:
                                heads[rig] = _head_anchor(sc, rig, helpers)
                            local_cfg = {**cfg, '_head': heads[rig]}
                    key = orig, local_cfg.get('_head')
                    if key not in cache:
                        cache[key] = _styled_material(orig, local_cfg, sc.render.engine, materials, groups, images, filtered)
                    link = slot.link
                    slot.link = 'OBJECT'
                    # DATA-linked slots can retain a different inactive OBJECT
                    # override. Preserve that too for an exact restoration.
                    slots.append((slot, link, slot.material))
                    slot.material = cache[key]
                if hull and cfg['strength'] > 0:
                    if black is None:
                        black = bpy.data.materials.new('__c3d_style_ink')
                        materials.append(black)
                        black.use_nodes = True
                        black.use_backface_culling = True
                        black.use_backface_culling_shadow = True
                        # Cycles ignores raster backface culling: reproduce it in
                        # the shader as well so a hull can never black out a face.
                        nt = black.node_tree
                        ink = nt.nodes.new('ShaderNodeEmission')
                        ink.inputs['Color'].default_value = (.005, .007, .012, 1)
                        geometry = nt.nodes.new('ShaderNodeNewGeometry')
                        transparent = nt.nodes.new('ShaderNodeBsdfTransparent')
                        mix = nt.nodes.new('ShaderNodeMixShader')
                        nt.links.new(geometry.outputs['Backfacing'], mix.inputs[0])
                        nt.links.new(ink.outputs[0], mix.inputs[1])
                        nt.links.new(transparent.outputs[0], mix.inputs[2])
                        nt.links.new(mix.outputs[0], nt.nodes.get('Material Output').inputs['Surface'])
                    shell = obj.copy()
                    shell.data = obj.data.copy()
                    # Proxy normals shape lighting; hull extrusion must retain
                    # its own reversed geometric normals and silhouette.
                    for modifier in list(shell.modifiers):
                        if modifier.name.startswith('__c3d_face_normals'):shell.modifiers.remove(modifier)
                    sc.collection.objects.link(shell)
                    hulls.append(shell)
                    shell.name = '__c3d_style_outline'
                    shell.visible_shadow = False
                    # A reversed, expanded shell: only its back-facing silhouette shows.
                    bm = bmesh.new()
                    bm.from_mesh(shell.data)
                    native_faces=obj.get('c3d_toon_outline_face_count',len(obj.data.polygons))==len(obj.data.polygons)
                    omit=set(obj.get('c3d_toon_outline_omit',[])) if obj.get('c3d_source')=='mpfb' and native_faces else set()
                    if omit:
                        bm.faces.ensure_lookup_table()
                        bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.index in omit],context='FACES_ONLY')
                    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
                    bm.to_mesh(shell.data)
                    bm.free()
                    for slot in shell.material_slots:
                        slot.link, slot.material = 'OBJECT', black
                    displace = shell.modifiers.new('__c3d_style_outline', 'DISPLACE')
                    displace.strength, displace.mid_level = -.0012 * cfg['strength'], 0
        compositor = old_group.copy() if old_group and old_compositing else bpy.data.node_groups.new('__c3d_style_compositor', 'CompositorNodeTree')
        compositor.name = '__c3d_style_compositor'
        _compositor(sc, post, images, compositor)
        sc.compositing_node_group = compositor
        sc.render.use_compositing = True
        yield images
    finally:
        try:
            for layer,aov in reversed(skin_aovs):
                layer.aovs.remove(aov)
            for original, temporary in worlds:
                sc.world = original
                bpy.data.worlds.remove(temporary)
            for obj, original in lights:
                temporary = obj.data
                obj.data = original
                bpy.data.lights.remove(temporary)
            sc.compositing_node_group = old_group
            sc.render.use_compositing = old_compositing
            if compositor:
                bpy.data.node_groups.remove(compositor)
            for key, value in saved_view.items():
                setattr(view, key, value)
            for shell in hulls:
                mesh = shell.data
                bpy.data.objects.remove(shell, do_unlink=True)
                bpy.data.meshes.remove(mesh)
            for slot, link, material in slots:
                slot.material, slot.link = material, link
            for obj, old, temporary in meshes:
                obj.data = old
                bpy.data.meshes.remove(temporary)
            for mat in materials:
                bpy.data.materials.remove(mat)
            for group in groups:
                bpy.data.node_groups.remove(group)
            for img in images:
                bpy.data.images.remove(img)
            for obj in reversed(helpers):
                bpy.data.objects.remove(obj, do_unlink=True)
        finally:
            if normal_context is not None:
                normal_context.__exit__(None,None,None)
