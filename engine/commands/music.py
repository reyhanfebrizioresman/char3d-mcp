"""Scene-aware procedural music, owned sound strips and saved scoring metadata."""
import json
import time

import bpy

from . import command
from .audio import _sound_strips, _strips, _volume_curve, add_audio, duck_music
from .. import context
from ..music import compose, render, metrics, write_cached, infer_mood, mood_name
from ..music.compose import number

PROP = "char3d_auto_music"


def scene_context(sc):
    from .semantic import load_words
    from ..emotion import classify, sentences
    from .sfx import _preset
    beats = json.loads(sc.get("char3d_music_beats", "[]"))
    emotions = []
    for obj in sc.objects:
        stored = json.loads(obj.get("char3d_emotions", "[]"))
        if stored:
            for e in stored:
                emotions.append(dict(frame=e["frames"][0], emotion=e["emotion"], strength=e["strength"]))
        else:
            for sentence in sentences(load_words(obj)):
                emotion, strength, _question = classify(sentence)
                emotions.append(dict(frame=round(sentence[0][1]), emotion=emotion, strength=strength))
    emotions += [dict(frame=b["frames"][0], emotion=b["emotion"], strength=.7)
                 for b in beats if b.get("emotion") and b.get("frames")]
    for e in emotions:
        beats.append(e)
    look = json.loads(sc.get("char3d_cinematic_look", "null"))
    mood = infer_mood(beats, look, sc.get("c3d_weather_kind"), _preset())
    cuts = {m.frame for m in sc.timeline_markers if m.camera}
    for graphic in json.loads(sc.get("char3d_graphics", "[]")):
        if graphic["type"] == "title":
            cuts.add(sc.frame_start+round(graphic.get("start_s", 0)*sc.render.fps/sc.render.fps_base))
    return mood, sorted(cuts), emotions


@command("auto_music")
def auto_music(mood="auto", duration=None, tempo=None, key=None, intensity=.6, seed=0, volume=.35,
               follow_cuts=True, follow_emotion=True, sections=None, fade_in=1., fade_out=2., clear=False,
               backend="auto"):
    sc = bpy.context.scene
    started = time.perf_counter()
    first, last = sc.frame_start, sc.frame_end
    fps = sc.render.fps/sc.render.fps_base
    number(volume, "volume", 0, 10)
    number(fade_in, "fade_in", 0, 600)
    number(fade_out, "fade_out", 0, 600)
    mood = mood_name(mood)
    samples = None
    if not clear and mood is not None:
        inferred, cuts, emotions = scene_context(sc)
        mood = inferred if mood == "auto" else mood
        duration = (last-first+1)/fps if duration is None else number(duration, "duration", .25, 600)
        score = compose(duration, mood, tempo, key, intensity, seed,
                        [c for c in cuts if first <= c < first+duration*fps] if follow_cuts else (),
                        [e for e in emotions if first <= e["frame"] < first+duration*fps] if follow_emotion else (),
                        sections, fps, first)
        parsed = time.perf_counter()
        samples = render(score, backend=backend)
        path, digest = write_cached(samples, context.resolve("audio/music/generated", "imports"))
        measured = metrics(samples, score)
        rendered = time.perf_counter()
    # Validate and render BEFORE removing the previous score: failures preserve it.
    removed = []
    for strip in list(_sound_strips(sc)):
        if strip.get(PROP):
            curve = _volume_curve(strip)
            if curve:
                curve.keyframe_points.clear()
            removed.append(strip.name)
            _strips(sc.sequence_editor).remove(strip)
    if samples is None:
        if PROP in sc:
            del sc[PROP]
        return dict(removed=removed, strips=[], mood=None)
    end = first+max(1, round(duration*fps))
    used = {s.channel for s in _strips(sc.sequence_editor) if s.frame_final_start < end and s.frame_final_end > first} if sc.sequence_editor else set()
    channel = next((c for c in range(1, 129) if c not in used), None)
    if channel is None:
        raise ValueError("auto_music needs a free sequencer channel")
    saved_frame = sc.frame_current
    try:
        info = add_audio(path, first, volume, channel, "Score_"+mood, "music", False, fade_in, fade_out)
        strip = _strips(sc.sequence_editor)[info["strip"]]
        strip.frame_final_end = end
        strip[PROP] = True
        strip["char3d_music_hash"] = digest
        result = {k: score[k] for k in ("mood", "key", "tempo", "sections", "accents", "emotion_cues", "seed")}
        result.update(path=path, hash=digest, backend=backend, renderer=score['renderer'], frames=[first, end-1], duration_s=duration,
                      sample_rate=48000, channels=2, loudness=measured, strips=[strip.name], removed=removed,
                      volume=volume, intensity=intensity, fade_in=fade_in, fade_out=fade_out,
                      follow_cuts=follow_cuts, follow_emotion=follow_emotion, custom_sections=sections or [])
        result["ducking"] = duck_music(strip.name)
        result["timings"] = dict(compose=round(parsed-started, 4), render=round(rendered-parsed, 4),
                                 total=round(time.perf_counter()-started, 4))
        sc[PROP] = json.dumps(result)
        return result
    finally:
        sc.frame_end = last
        sc.frame_set(saved_frame)
