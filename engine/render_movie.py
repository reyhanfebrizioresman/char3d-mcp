"""Render the snapshot movie, then outgoing-camera handles for genuine crossfades.

Invoked by render_video in its background Blender, never in the interactive engine.
The scene animation continues through each handle; a camera whose keys end at the cut
holds its last keyed transform/lens, following Blender's usual constant extrapolation.
"""
import json
import sys

import bpy


def main(spec_path):
    with open(spec_path) as f:
        spec = json.load(f)
    sc = bpy.context.scene
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
