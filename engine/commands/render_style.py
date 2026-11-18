"""Scene-stored looks. All rendering overrides are temporary, including on failure."""
from contextlib import contextmanager
import json
import math

import bpy
import bmesh
import numpy as np

from . import command

CONFIG_PROP = 'char3d_render_style'
STYLES = ('none', 'anime', 'toon', 'clay', 'film', 'noir', 'vintage')
# CPU Eevee 540p measurements are documented in AGENTS.md. Keep these separate
# from machine calibration so a styled movie cannot inflate the baseline twice.
COST = {'none': 1.0, 'anime': 1.2, 'clay': 1.0, 'film': 1.1, 'noir': 1.05, 'vintage': 1.05}
DEFAULTS = {
    'anime': dict(contrast=1.04, saturation=1.12),
    'clay': dict(contrast=1.0, saturation=1.0),
    'film': dict(contrast=1.12, saturation=0.94),
    'noir': dict(contrast=1.5, saturation=0.0),
    'vintage': dict(contrast=0.82, saturation=0.72, temperature=0.18),
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
    if style not in STYLES:
        raise ValueError(f'style must be one of {STYLES}')
    style = 'anime' if style == 'toon' else style
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


def _styled_material(original, cfg, engine, materials, groups):
    mat = original.copy() if original else bpy.data.materials.new('__c3d_style_material')
    materials.append(mat)
    mat.use_nodes = True
    copies = {}

    def visit(tree):
        # MPFB skin lives in nested groups. Copy the entire referenced graph so
        # group inputs, texture coordinates, alpha and animation remain connected.
        for node in list(tree.nodes):
            if node.type == 'GROUP' and node.node_tree:
                source = node.node_tree
                if source not in copies:
                    copy = source.copy()
                    groups.append(copy)
                    copies[source] = copy
                    visit(copy)
                node.node_tree = copies[source]
        for bsdf in list(tree.nodes):
            if bsdf.type != 'BSDF_PRINCIPLED':
                continue
            consumers = [link.to_socket for link in bsdf.outputs['BSDF'].links]
            if consumers:
                styled = _styled_shader(tree, bsdf, cfg, engine)
                for socket in consumers:
                    tree.links.new(styled, socket)

    visit(mat.node_tree)
    return mat


def _styled_shader(tree, bsdf, cfg, engine):
    nodes, links = tree.nodes, tree.links
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
            for el, pos, value in zip(ramp.color_ramp.elements, (0, 0.45), (0.42, 0.78)):
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
    if (effects and effects['bloom'] > 0) or (effects is None and style == 'film'):
        glow = nodes.new('CompositorNodeGlare')
        glow.inputs['Type'].default_value = 'Fog Glow'
        glow.inputs['Quality'].default_value = 'Low'
        glow.inputs['Threshold'].default_value = 1.3
        glow.inputs['Strength'].default_value = effects['bloom'] if effects else .08
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
    links.new(image, output.inputs.get('Image') or output.inputs[0])
    return tree


@contextmanager
def applied_style(sc):
    """Apply only for the render duration; user datablocks are never edited."""
    from .cinematic import compositor_config
    cfg = get_config(sc)
    post = compositor_config(sc, cfg)
    if not post or post['strength'] == 0 or sc.render.engine == 'BLENDER_WORKBENCH':
        yield []
        return
    cfg = cfg or dict(style='cinematic', strength=1., outline=False)
    slots, materials, meshes, hulls, images, groups = [], [], [], [], [], []
    compositor = None
    old_group = sc.compositing_node_group
    old_compositing = sc.render.use_compositing
    view = sc.view_settings
    saved_view = {k: getattr(view, k) for k in ('view_transform', 'look', 'exposure', 'gamma')}
    try:
        if cfg['style'] == 'film':
            view.view_transform = 'AgX'
            view.look = 'AgX - Medium High Contrast'
        if cfg['style'] in ('anime', 'clay') or cfg['outline']:
            cache = {}
            black = None
            for obj in list(sc.objects):
                if obj.type != 'MESH' or obj.hide_render or obj.get('c3d_role') in ('weather', 'cinematic'):
                    continue
                hull = cfg['outline'] and _opaque(obj)
                if not obj.material_slots:
                    old = obj.data
                    obj.data = old.copy()
                    meshes.append((obj, old, obj.data))
                    obj.data.materials.append(None)
                for slot in obj.material_slots if cfg['style'] in ('anime', 'clay') else ():
                    orig = slot.material
                    if orig not in cache:
                        cache[orig] = _styled_material(orig, cfg, sc.render.engine, materials, groups)
                    link = slot.link
                    slot.link = 'OBJECT'
                    # DATA-linked slots can retain a different inactive OBJECT
                    # override. Preserve that too for an exact restoration.
                    slots.append((slot, link, slot.material))
                    slot.material = cache[orig]
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
                    sc.collection.objects.link(shell)
                    hulls.append(shell)
                    shell.name = '__c3d_style_outline'
                    shell.visible_shadow = False
                    # A reversed, expanded shell: only its back-facing silhouette shows.
                    bm = bmesh.new()
                    bm.from_mesh(shell.data)
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
