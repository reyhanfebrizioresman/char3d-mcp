"""Audio: sound strips on the timeline and audio-driven lip sync.

Decoding uses Blender's own `aud` module (bundled FFmpeg): wav, mp3, flac, ogg, m4a...

Lip sync modes (picked automatically from what is provided):
  words - [{word, start, end}] seconds (e.g. from Whisper): best timing.
  text  - transcript only: words are spread over the voiced parts of the audio.
  audio - nothing else: mouth shapes guessed per frame from loudness and spectrum.
In every mode the loudness envelope scales how wide the mouth opens.
"""
import math
import json
import os
import uuid

import bpy
import numpy as np

from .. import context
from . import command
from .face import (VISEMES, VOWEL_VISEMES, _basemesh, _clear_mouth_keys, _ensure_face,
                   _face_meshes, _set, key_phonemes, key_viseme, text_tokens)
from .semantic import load_words, store_words
from ..phonemes import choose_language


def _resolve(path):
    p = context.resolve(path, "imports")
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    return p


def load_audio(path):
    import aud
    snd = aud.Sound(path)
    rate = int(snd.specs[0])
    data = np.asarray(snd.data(), dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data, rate


def analyze(samples, rate, fps):
    """Per-video-frame features: loudness (dB), openness 0..1, voiced mask, spectrum bands."""
    hop = rate / float(fps)
    n_frames = int(np.ceil(len(samples) / hop))
    win = int(hop * 2)
    nfft = 1 << int(np.ceil(np.log2(max(win, 256))))
    window = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, 1.0 / rate)
    bands = {"f1": (150, 900), "f2": (900, 2500), "hi": (2500, 5000), "sib": (5000, 8000)}
    masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in bands.items()}
    rms = np.zeros(n_frames, np.float32)
    zcr = np.zeros(n_frames, np.float32)
    band = {k: np.zeros(n_frames, np.float32) for k in bands}
    padded = np.concatenate([np.zeros(win // 2, np.float32), samples, np.zeros(win, np.float32)])
    for i in range(n_frames):
        start = int(i * hop)
        seg = padded[start:start + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        rms[i] = np.sqrt(np.mean(seg * seg) + 1e-12)
        zcr[i] = np.mean(np.abs(np.diff(np.sign(seg)))) / 2
        spec = np.abs(np.fft.rfft(seg * window, nfft)) ** 2
        for k, m in masks.items():
            band[k][i] = spec[m].sum()
    db = 20 * np.log10(rms + 1e-9)
    floor, peak = np.percentile(db, 10), np.percentile(db, 97)
    thr = floor + 0.35 * max(peak - floor, 6.0)
    voiced = db > thr
    # fill tiny gaps / drop blips (hangover smoothing)
    v = voiced.copy()
    for i in range(1, len(v) - 1):
        if not v[i] and v[i - 1] and v[i + 1]:
            v[i] = True
    for i in range(1, len(v) - 1):
        if v[i] and not v[i - 1] and not v[i + 1]:
            v[i] = False
    openness = np.clip((db - thr) / max(peak - thr, 1e-3), 0, 1) ** 0.7
    openness = np.convolve(openness, [0.25, 0.5, 0.25], mode="same")
    openness[~v] = 0
    return {"db": db, "voiced": v, "open": openness, "zcr": zcr, "band": band,
            "seconds": len(samples) / rate, "frames": n_frames}


def _segments(voiced, fps, merge_gap_s=0.15):
    segs, start = [], None
    for i, on in enumerate(list(voiced) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            segs.append([start, i])
            start = None
    merged = []
    for s in segs:
        if merged and (s[0] - merged[-1][1]) / fps < merge_gap_s:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return merged


def _thresholds(feat):
    """Speaker-adaptive cut points from this clip's own voiced frames."""
    v = feat["voiced"]
    b = feat["band"]
    eps = 1e-12
    lr = np.log10(b["f2"] + eps) - np.log10(b["f1"] + eps)            # vowel "frontness"
    tot = b["f1"] + b["f2"] + b["hi"] + b["sib"] + eps
    hr = np.log10(b["hi"] + b["sib"] + eps) - np.log10(tot)             # hiss share
    feat["lr"], feat["hr"] = lr, hr
    if v.sum() < 5:
        return None
    q = np.percentile(lr[v], [15, 35, 70, 88])
    return {"lr": q, "hr": np.percentile(hr[v], 90), "zcr": np.percentile(feat["zcr"][v], 70),
            "open": np.percentile(feat["open"][v], 20)}


def _classify(feat, i, th):
    """Guess a mouth shape for one frame: hiss -> s/sh, quiet dip -> closed lips,
    otherwise vowel by where its spectral balance sits within this speaker's range."""
    if th is None:
        return "aa_02"
    if feat["hr"][i] >= th["hr"] and feat["zcr"][i] >= th["zcr"]:
        return "s_z_15" if feat["band"]["sib"][i] > feat["band"]["hi"][i] else "sh_ch_jh_zh_16"
    o = feat["open"]
    if o[i] <= th["open"] and 0 < i < len(o) - 1 and o[i] <= o[i - 1] and o[i] <= o[i + 1]:
        return "p_b_m_21"
    lr = feat["lr"][i]
    q = th["lr"]
    if lr < q[0]:
        return "w_uw_07"
    if lr < q[1]:
        return "ow_08"
    if lr < q[2]:
        return "aa_02"
    if lr < q[3]:
        return "ey_eh_uh_04"
    return "y_iy_ih_ix_06"


def _open_at(feat, frame_rel):
    i = int(min(max(frame_rel, 0), feat["frames"] - 1))
    return float(feat["open"][i])


def _words_from_text(text, feat, fps):
    """Spread transcript words over voiced segments in proportion to their length."""
    words = [w for w in text.replace("\n", " ").split(" ") if w.strip()]
    segs = _segments(feat["voiced"], fps)
    if not words or not segs:
        return []
    total_voiced = sum(e - s for s, e in segs)
    total_chars = sum(len(w) for w in words)
    out, seg_i, cursor = [], 0, segs[0][0]
    for w in words:
        dur = total_voiced * len(w) / total_chars
        start = cursor
        remaining = dur
        while remaining > 1e-6 and seg_i < len(segs):
            room = segs[seg_i][1] - cursor
            if room >= remaining:
                cursor += remaining
                remaining = 0
            else:
                remaining -= room
                seg_i += 1
                if seg_i < len(segs):
                    cursor = segs[seg_i][0]
        out.append({"word": w, "start": start / fps, "end": cursor / fps})
        if seg_i < len(segs) and cursor >= segs[seg_i][1] - 1e-6:
            seg_i += 1
            if seg_i < len(segs):
                cursor = segs[seg_i][0]
    return out


def _sound_strips(sc):
    se = sc.sequence_editor
    if se is None:
        return []
    coll = se.strips_all if hasattr(se, "strips_all") else se.sequences_all
    return [s for s in coll if s.type == "SOUND"]


def _strips(se):
    # note: an empty collection is falsy, so never pick the API with `or`
    return se.strips if hasattr(se, "strips") else se.sequences


def _volume_curve(strip):
    from .talk import _fcurves
    sc = bpy.context.scene
    action = sc.animation_data.action if sc.animation_data else None
    path = strip.path_from_id("volume")
    return next((fc for fc in _fcurves(action) if fc.data_path == path), None)


def _key_volume(strip, ranges=(), amount_db=-12, attack=0.15, release=0.4):
    """Replace this strip's volume curve with its fades times the ducking envelope."""
    sc = bpy.context.scene
    fps = sc.render.fps / sc.render.fps_base
    start, end = int(strip.frame_final_start), int(strip.frame_final_end)
    frames = np.arange(start, end + 1, dtype=float)
    gain = np.ones(len(frames))
    floor = 10 ** (amount_db / 20)
    for a, b in ranges:
        envelope = np.full(len(frames), floor)
        before, after = frames < a, frames > b
        envelope[before] = (floor + (1 - floor) * np.clip((a - frames[before]) / (attack * fps), 0, 1)
                            if attack else 1)
        envelope[after] = (floor + (1 - floor) * np.clip((frames[after] - b) / (release * fps), 0, 1)
                           if release else 1)
        gain = np.minimum(gain, envelope)
    fade_in, fade_out = strip.get("char3d_fade_in", 0), strip.get("char3d_fade_out", 0)
    if fade_in:
        gain *= np.clip((frames - strip["char3d_audio_start"]) / (fade_in * fps), 0, 1)
    if fade_out:
        gain *= np.clip((strip["char3d_audio_end"] - frames) / (fade_out * fps), 0, 1)
    if strip.get('char3d_audio_kind') == 'music' or strip.get('char3d_sfx_kind') == 'ambience':
        for silence in json.loads(sc.get('char3d_director_silences', '[]')):
            # 80 ms shoulders preserve continuity; the held interior is -30 dB.
            a, b = silence['start'], silence['end']
            edge = max(1., .08*fps)
            depth = np.minimum(np.clip((frames-a)/edge, 0, 1), np.clip((b-frames)/edge, 0, 1))
            gain *= 1-depth*(1-10**(silence.get('db', -30)/20))
    volume = strip.get("char3d_volume", strip.volume)
    strip["char3d_volume"] = volume
    # Dense samples preserve overlapping fades/ramps exactly at each video frame.
    strip.keyframe_insert(data_path="volume", frame=start)
    curve = _volume_curve(strip)
    curve.keyframe_points.clear()
    curve.keyframe_points.add(len(frames))
    curve.keyframe_points.foreach_set("co", np.column_stack((frames, gain * volume)).ravel())
    for key in curve.keyframe_points:
        key.interpolation = "LINEAR"
    curve.update()


@command("add_audio")
def add_audio(path, start_frame=1, volume=1.0, channel=None, name=None,
              kind="voice", loop=False, fade_in=0.0, fade_out=0.0):
    """Place voice/music/sfx on the timeline, with optional music repeats and fades."""
    if kind not in {"voice", "music", "sfx"}:
        raise ValueError("kind must be voice, music or sfx")
    if loop and kind != "music":
        raise ValueError("loop=True requires kind='music'")
    if not all(math.isfinite(v) and v >= 0 for v in (volume, fade_in, fade_out)):
        raise ValueError("volume, fade_in and fade_out must be finite and nonnegative")
    path = _resolve(path)
    sc = bpy.context.scene
    start = int(start_frame)
    if loop and start > sc.frame_end:
        raise ValueError("looped music must start within or before the scene range")
    se = sc.sequence_editor or sc.sequence_editor_create()
    strips = _strips(se)
    used = {s.channel for s in _sound_strips(sc)}
    ch = int(channel) if channel else next(c for c in range(1, 64) if c not in used)
    strip = strips.new_sound(name or os.path.basename(path), path, ch, start)
    duration = int(strip.frame_final_duration)
    if duration < 1:
        strips.remove(strip)
        raise ValueError("audio must contain at least one frame")
    end = sc.frame_end + 1 if loop else int(strip.frame_final_end)
    group = uuid.uuid4().hex
    added = [strip]
    if loop:
        strip.frame_final_end = min(start + duration, end)
        for frame in range(start + duration, end, duration):
            repeat = strips.new_sound(strip.name + "_loop", path, ch, frame)
            repeat.frame_final_end = min(frame + duration, end)
            added.append(repeat)
    for sound in added:
        sound.volume = float(volume)
        sound["char3d_audio_kind"] = kind
        sound["char3d_audio_group"] = group
        sound["char3d_volume"] = float(volume)
        sound["char3d_audio_start"], sound["char3d_audio_end"] = start, end
        sound["char3d_fade_in"], sound["char3d_fade_out"] = float(fade_in), float(fade_out)
        if fade_in or fade_out:
            _key_volume(sound)
    if not loop:
        sc.frame_end = max(sc.frame_end, end)
    sc.frame_set(sc.frame_current)
    return {"strip": strip.name, "strips": [s.name for s in added], "kind": kind,
            "channel": ch, "frames": [start, end - 1],
            "seconds": round((end - start) / (sc.render.fps / sc.render.fps_base), 2), "path": path}


def _source_activity(path):
    import aud

    sound = aud.Sound(path)
    rate = int(sound.specs[0])
    samples = np.asarray(sound.data(), dtype=np.float32)
    if not len(samples):
        return []
    # Short, broadband RMS windows keep quiet consonants and handle stereo
    # recordings where opposite-polarity channels would cancel in the downmix.
    step = max(1, round(.02 * rate))
    power = np.square(samples)
    if power.ndim == 2:
        power = power.mean(axis=1)
    blocks = np.add.reduceat(power, np.arange(0, len(power), step))
    sizes = np.minimum(step, len(power) - np.arange(len(blocks)) * step)
    level = np.sqrt(blocks / sizes)
    gate = max(1e-4, min(.003, float(level.max()) * .02))
    return [(a * step / rate, min(b * step, len(samples)) / rate)
            for a, b in _segments(level > gate, rate / step, merge_gap_s=.5)]


def _speech_ranges(sc):
    """Detect active voice audio and retain timing for lips animated without sound."""
    fps = sc.render.fps / sc.render.fps_base
    ranges, activity, recorded = [], {}, {}
    for strip in _sound_strips(sc):
        if strip.get("char3d_audio_kind", "voice") != "voice":
            continue
        start, end = float(strip.frame_final_start), float(strip.frame_final_end)
        origin = float(strip.frame_start)
        speaker = strip.get("char3d_speaker")
        if speaker:
            recorded.setdefault(speaker, []).append((min(origin, start),
                                                      max(end, origin + strip.frame_duration)))
        if strip.mute or (strip.volume == 0 and _volume_curve(strip) is None):
            continue
        if not strip.sound or len(getattr(strip, "retiming_keys", ())):
            ranges.append((start, end))
            continue
        path = bpy.path.abspath(strip.sound.filepath)
        if path not in activity:
            try:
                activity[path] = _source_activity(path)
            except (OSError, RuntimeError, ValueError):
                activity[path] = None
        spans = activity[path]
        if spans is None:
            ranges.append((start, end))
            continue
        origin -= float(getattr(strip, "sound_offset", 0)) * fps
        ranges.extend((max(start, math.floor(origin + a * fps + 1e-6)),
                       min(end, math.ceil(origin + b * fps - 1e-6))) for a, b in spans)
    for obj in sc.objects:
        speaker = obj.parent if obj.parent and obj.parent.type == "ARMATURE" else obj
        clip_spans = recorded.get(speaker.name, ())
        ranges.extend((a, b) for _word, a, b in load_words(obj)
                      if not any(max(a, start) < min(b, end) for start, end in clip_spans))
    gap = .5 * fps
    merged = []
    for a, b in sorted(ranges):
        a, b = max(a, sc.frame_start), min(b, sc.frame_end + 1)
        if b <= a:
            continue
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


@command("duck_music")
def duck_music(music_strip=None, amount_db=-12, attack=0.15, release=0.4):
    """Key music down during speech; selecting one repeat also selects its loop group."""
    if not math.isfinite(amount_db) or amount_db > 0:
        raise ValueError("amount_db must be finite and <= 0")
    if not all(math.isfinite(v) and v >= 0 for v in (attack, release)):
        raise ValueError("attack and release must be finite and nonnegative seconds")
    sc = bpy.context.scene
    music = [s for s in _sound_strips(sc) if s.get("char3d_audio_kind") == "music"]
    if music_strip is not None:
        target = next((s for s in music if s.name == music_strip), None)
        if target is None:
            raise ValueError(f"music strip {music_strip!r} not found; use list_audio")
        group = target.get("char3d_audio_group")
        music = [s for s in music if s == target or (group and s.get("char3d_audio_group") == group)]
    if not music:
        raise ValueError("no music strips; use add_audio(kind='music') first")
    ranges = _speech_ranges(sc)
    for strip in music:
        _key_volume(strip, ranges, amount_db, attack, release)
    sc.frame_set(sc.frame_current)
    return {"strips": [s.name for s in music], "speech_ranges": ranges,
            "amount_db": amount_db, "gain": round(10 ** (amount_db / 20), 6),
            "attack": attack, "release": release}


@command("list_audio")
def list_audio():
    sc = bpy.context.scene
    return {"strips": [{"name": s.name, "channel": s.channel,
                        "frames": [int(s.frame_final_start), int(s.frame_final_end) - 1],
                        "kind": s.get("char3d_audio_kind", "voice"),
                        "speaker": s.get("char3d_speaker"),
                        "volume": round(s.volume, 2), "path": s.sound.filepath if s.sound else None}
                       for s in _sound_strips(sc)]}


@command("remove_audio")
def remove_audio(name=None):
    sc = bpy.context.scene
    se = sc.sequence_editor
    if se is None:
        return {"removed": []}
    strips = _strips(se)
    removed = []
    for s in list(_sound_strips(sc)):
        if name is None or s.name == name:
            removed.append(s.name)
            strips.remove(s)
    return {"removed": removed}


@command("lip_sync_audio")
def lip_sync_audio(character, audio, start_frame=1, words=None, text=None, strength=0.9,
                   add_sound=True, expression=None, volume=1.0, language=None, detail="phoneme"):
    """Animate visemes from an audio file (optionally with word timings or a transcript)."""
    if detail not in ("phoneme", "word"):
        raise ValueError("detail must be phoneme or word")
    language = choose_language(" ".join(w["word"] for w in words) if words else text or "", language)
    path = _resolve(audio)
    base = _basemesh(character)
    _ensure_face(base)
    meshes = _face_meshes(base)
    sc = bpy.context.scene
    fps = sc.render.fps
    samples, rate = load_audio(path)
    if len(samples) == 0:
        raise ValueError("audio file is empty")
    feat = analyze(samples, rate, fps)
    start = int(start_frame)
    n = feat["frames"]
    _clear_mouth_keys(meshes, start, start + n + 1)
    _set(meshes, {v: 0.0 for v in VISEMES}, start)

    if words:
        mode = "words"
    elif text:
        mode = "text"
        words = _words_from_text(text, feat, fps)
    else:
        mode = "audio"

    end = start + n + 1
    shapes, phones = 0, []
    if mode in ("words", "text") and detail == "phoneme":
        if expression:
            from .face import set_expression
            set_expression(character, expression, frame=start, keyframe=True, transition_frames=0)
        word_frames = [(w["word"], start + max(0.0, min(feat["seconds"], float(w["start"]))) * fps,
                        start + max(0.0, min(feat["seconds"], float(w["end"]))) * fps)
                       for w in words]
        phones = key_phonemes(meshes, word_frames, start, end, fps, strength, language,
                              lambda f: 0.45 + 0.55 * _open_at(feat, f - start))
        shapes = len(phones)
    elif mode in ("words", "text"):
        for w in words:
            toks = [t for t in text_tokens(w["word"]) if t != "sil_00"]
            merged = []
            for t in toks:
                if not merged or merged[-1] != t:
                    merged.append(t)
            if not merged:
                continue
            f0 = float(w["start"]) * fps
            f1 = max(float(w["end"]) * fps, f0 + len(merged) * 0.8)
            step = (f1 - f0) / len(merged)
            for k, vis in enumerate(merged):
                t0 = start + f0 + k * step
                loud = 0.45 + 0.55 * _open_at(feat, f0 + k * step)
                base_w = strength if vis in VOWEL_VISEMES else strength * 0.75
                key_viseme(meshes, vis, t0, t0 + step, base_w * loud)
                shapes += 1
    else:
        th = _thresholds(feat)
        cls = [(_classify(feat, i, th) if feat["voiced"][i] else "sil_00") for i in range(n)]
        # 3-frame majority filter against flicker
        sm = cls[:]
        for i in range(1, n - 1):
            if cls[i - 1] == cls[i + 1] != cls[i]:
                sm[i] = cls[i - 1]
        prev = None
        for i, vis in enumerate(sm):
            f = start + i
            if prev and prev != vis:
                _set(meshes, {prev: 0.0}, f)
            if vis != "sil_00":
                w = (strength if vis in VOWEL_VISEMES else strength * 0.75) * (0.35 + 0.65 * feat["open"][i])
                _set(meshes, {vis: w}, f)
                if vis != prev:
                    shapes += 1
            prev = vis if vis != "sil_00" else None
    if not phones:
        _set(meshes, {v: 0.0 for v in VISEMES}, end)
    # word times for meaning-driven gestures (talk_gestures); audio-only mode has none
    stored = store_words(base, [(w["word"], start + float(w["start"]) * fps,
                                 start + float(w["end"]) * fps) for w in (words or [])],
                         start, end)
    if expression and (detail == "word" or mode == "audio"):
        from .face import set_expression
        set_expression(character, expression, frame=start, keyframe=True, transition_frames=0)
    sound = add_audio(path, start, volume) if add_sound else None
    if sound:     # whose voice this is: talk_motion / talk_gestures react to their own voice only
        speaker = base.parent if base.parent and base.parent.type == "ARMATURE" else base
        _strips(sc.sequence_editor)[sound["strip"]]["char3d_speaker"] = speaker.name
    sc.frame_end = max(sc.frame_end, end)
    voiced_s = float(np.sum(feat["voiced"])) / fps
    return {"character": base.name, "mode": mode, "frames": [start, end],
            "next_start_frame": end + 1, "seconds": round(feat["seconds"], 2),
            "voiced_seconds": round(voiced_s, 2), "mouth_shapes": shapes,
            "words": len(words) if words else 0, "word_times_stored": stored,
            "sound_strip": sound["strip"] if sound else None,
            "detail": detail if mode != "audio" else "audio",
            "language": language if mode != "audio" else None, "phonemes": phones}
