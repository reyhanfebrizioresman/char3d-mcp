"""Render the snapshot movie, then outgoing-camera handles for genuine crossfades.

Invoked by render_video in its background Blender, never in the interactive engine.
The scene animation continues through each handle; a camera whose keys end at the cut
holds its last keyed transform/lens, following Blender's usual constant extrapolation.
"""
import json
import os
import sys

import bpy

# Background Blender does not inherit the engine bootstrap's Python search path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.commands.render_style import applied_style  # noqa: E402
from engine.commands.cinematic import applied_look, compositor_config  # noqa: E402


def main(spec_path):
    with open(spec_path) as f:
        spec = json.load(f)
    sc = bpy.context.scene
    # Keep overrides through output encoding, including view color management.
    # Material copies retain animation; grain changes deterministically per frame.
    import numpy as np

    def grain(scene):
        img = grain_image
        if img:
            w, h = img.size
            pixels = np.ones((h, w, 4), dtype=np.float32)
            rng = np.random.default_rng(733 + scene.frame_current)
            cfg = json.loads(scene['char3d_render_style']) if scene.get('char3d_render_style') else None
            cfg = compositor_config(scene, cfg)
            amount = cfg['effects']['grain'] if 'effects' in cfg else .008 if cfg['style'] == 'noir' else .004
            pixels[:, :, :3] = rng.normal(0, amount, (h, w, 1))
            img.pixels.foreach_set(pixels.ravel())
            img.update()

    with applied_look(sc), applied_style(sc) as effects:
        grain_image = next((img for img in effects if img.name.startswith('__c3d_style_grain')), None)
        bpy.app.handlers.render_pre.append(grain)
        try:
            render_movies(sc, spec)
        finally:
            bpy.app.handlers.render_pre.remove(grain)


def render_movies(sc, spec):
    bpy.ops.render.render(animation=True)
    for marker in list(sc.timeline_markers):
        sc.timeline_markers.remove(marker)
    sc.render.ffmpeg.audio_codec = "NONE"
    for handle in spec["handles"]:
        sc.frame_start, sc.frame_end = handle["frames"]
        sc.camera = bpy.data.objects[handle["camera"]]
        sc.render.filepath = handle["path"]
        bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1])
