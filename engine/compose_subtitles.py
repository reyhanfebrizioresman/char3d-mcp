"""Second render pass: transitions, titles and caption PNGs with the Video Sequencer.

Run by render_video in a background Blender process:
    blender -b --factory-startup --python engine/compose_subtitles.py -- spec.json
spec: {"movie", "out_base", "width", "height", "fps", "frames", "audio", "crf",
       "transitions": [{"kind", "start", "end", "keys", "movie" (crossfade only)}],
       "overlays": [{"path", "start", "end", "pop", "origin": [x, y], "keys"}]}
"""
import json
import sys

import bpy


def opacity_keys(strip, keys):
    for frame, alpha, *dx in keys:
        strip.blend_alpha = alpha
        strip.keyframe_insert("blend_alpha", frame=frame)
        if dx:
            strip.transform.offset_x = dx[0]
            strip.transform.keyframe_insert("offset_x", frame=frame)


def linear_keys(sc):
    action = sc.animation_data.action if sc.animation_data else None
    if action:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for key in fc.keyframe_points:
                            key.interpolation = "LINEAR"


def main(spec_path):
    with open(spec_path) as f:
        spec = json.load(f)
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = int(spec["width"]), int(spec["height"])
    r.resolution_percentage = 100
    r.fps = int(round(spec["fps"]))
    r.fps_base = r.fps / spec["fps"]
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
    # A handle is the outgoing camera rendered at the SAME scene times as the incoming
    # shot. Fading it over the main movie preserves motion, audio sync and total length.
    for i, t in enumerate(spec.get("transitions", [])):
        if t["kind"] != "crossfade":
            continue
        st = strips.new_movie(f"handle{i}", t["movie"], channel=3, frame_start=t["start"])
        st.frame_final_duration = t["end"] - t["start"] + 1
        st.blend_type = "ALPHA_OVER"
        opacity_keys(st, t["keys"])
    placed = []
    for i, ov in enumerate(spec["overlays"]):
        # Reuse channels for disjoint caption states, even on long word-heavy videos.
        channel = max([3] + [ch for a, b, ch in placed if a <= ov["end"] and b >= ov["start"]]) + 1
        placed.append((ov["start"], ov["end"], channel))
        st = strips.new_image(f"overlay{i}", ov["path"], channel=channel, frame_start=int(ov["start"]))
        st.frame_final_duration = max(1, int(ov["end"]) - int(ov["start"]) + 1)
        st.blend_type = "ALPHA_OVER"
        if ov.get("keys"):
            opacity_keys(st, ov["keys"])
        if ov.get("pop"):
            t = st.transform
            t.origin = ov.get("origin", [0.5, 0.5])
            a = int(ov["start"])
            for df, s in ((0, 0.88), (2, 1.05), (4, 1.0)):
                t.scale_x = t.scale_y = s
                t.keyframe_insert("scale_x", frame=a + df)
                t.keyframe_insert("scale_y", frame=a + df)
    # Color fades cover picture, titles and captions together.
    for i, t in enumerate(spec.get("transitions", [])):
        if t["kind"] == "crossfade":
            continue
        st = strips.new_effect(f"fade{i}", type="COLOR", channel=max([3] + [x[2] for x in placed]) + 1,
                                frame_start=t["start"], length=t["end"] - t["start"] + 1)
        st.color = (1, 1, 1) if t["kind"] == "fade_white" else (0, 0, 0)
        st.blend_type = "ALPHA_OVER"
        opacity_keys(st, t["keys"])
    linear_keys(sc)
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
