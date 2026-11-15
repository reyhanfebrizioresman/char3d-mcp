"""Second render pass: lay caption PNGs over a rendered movie with the Video Sequencer.

Run by render_video in a background Blender process:
    blender -b --factory-startup --python engine/compose_subtitles.py -- spec.json
spec: {"movie", "out_base", "width", "height", "fps", "frames", "audio", "crf",
       "overlays": [{"path", "start", "end", "pop", "origin": [x, y]}]}
"""
import json
import sys

import bpy


def main(spec_path):
    with open(spec_path) as f:
        spec = json.load(f)
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = int(spec["width"]), int(spec["height"])
    r.resolution_percentage = 100
    r.fps, r.fps_base = int(round(spec["fps"])), 1.0
    sc.frame_start, sc.frame_end = 1, int(spec["frames"])
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure, sc.view_settings.gamma = 0.0, 1.0
    r.use_sequencer = True
    r.use_compositing = False
    se = sc.sequence_editor_create()
    strips = se.strips
    mov = strips.new_movie("video", spec["movie"], channel=1, frame_start=1)
    mov.frame_final_duration = int(spec["frames"])
    if spec.get("audio"):
        snd = strips.new_sound("audio", spec["movie"], channel=2, frame_start=1)
        snd.frame_final_duration = int(spec["frames"])
    for i, ov in enumerate(spec["overlays"]):
        st = strips.new_image(f"cap{i}", ov["path"], channel=3 + (i % 2), frame_start=int(ov["start"]))
        st.frame_final_duration = max(1, int(ov["end"]) - int(ov["start"]) + 1)
        st.blend_type = "ALPHA_OVER"
        if ov.get("pop"):
            t = st.transform
            t.origin = ov.get("origin", [0.5, 0.5])
            a = int(ov["start"])
            for df, s in ((0, 0.88), (2, 1.05), (4, 1.0)):
                t.scale_x = t.scale_y = s
                t.keyframe_insert("scale_x", frame=a + df)
                t.keyframe_insert("scale_y", frame=a + df)
    im = r.image_settings
    if hasattr(im, "media_type"):
        im.media_type = "VIDEO"
    im.file_format = "FFMPEG"
    r.ffmpeg.format = "MPEG4"
    r.ffmpeg.codec = "H264"
    r.ffmpeg.constant_rate_factor = spec.get("crf", "HIGH")
    r.ffmpeg.ffmpeg_preset = "GOOD"
    if spec.get("audio"):
        r.ffmpeg.audio_codec = "AAC"
        r.ffmpeg.audio_bitrate = 192
        if hasattr(r.ffmpeg, "audio_channels"):
            r.ffmpeg.audio_channels = "STEREO"
    else:
        r.ffmpeg.audio_codec = "NONE"
    r.use_file_extension = True
    r.filepath = spec["out_base"]
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1])
