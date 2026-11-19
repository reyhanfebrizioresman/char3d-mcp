"""Conversational head and eye motion layered on top of existing animation.

Driven by speech rhythm: the loudness envelope of the timeline audio (or, without audio,
the activity of the character's lip-sync shape keys). Only neck/head rotations and a few
face shape keys (brows, eye gaze) are (re)keyed, so body animation stays intact.

Character-space angles: nod (+ = look down), turn (+ = toward the character's left),
tilt (+ = top of head toward the left shoulder).
"""
import math
import os
import random

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from . import command
from .anim import _key_rot, semantic_map
from .face import _basemesh, _ensure_face, _face_meshes, _set, VISEMES, MOUTH_UNITS
from .gaze import head_frame
from .util import obj_or_raise


def _rig_of(character):
    obj = obj_or_raise(character)
    if obj.type == "ARMATURE":
        return obj
    if obj.parent and obj.parent.type == "ARMATURE":
        return obj.parent
    raise ValueError(f"{character} has no armature (talk_motion needs a rigged character)")


def _fcurves(action):
    if action is None:
        return []
    if hasattr(action, "layers"):
        return [fc for layer in action.layers for strip in layer.strips
                for bag in strip.channelbags for fc in bag.fcurves]
    return list(action.fcurves)


def _data_curves(data):
    """Only this ID's slot; imported animations can share one multi-slot Action."""
    ad = data.animation_data if data else None
    action = ad.action if ad else None
    if action is not None and hasattr(action, 'layers'):
        slot = ad.action_slot
        if slot is None:
            return []
        bags = [strip.channelbag(slot) for layer in action.layers for strip in layer.strips]
        return [fc for bag in bags if bag is not None for fc in bag.fcurves]
    return _fcurves(action)


def _viseme_activity(base, f0, f1):
    """Per-frame sum of mouth shape-key values from the lip-sync animation."""
    sk = base.data.shape_keys
    paths = {f'key_blocks["{name}"].value' for name in (*VISEMES, *MOUTH_UNITS)}
    curves = [fc for fc in _data_curves(sk) if fc.data_path in paths]
    frames = np.arange(f0, f1 + 1)
    if not curves:
        return np.zeros(len(frames))
    return np.array([sum(max(0.0, fc.evaluate(float(f))) for fc in curves) for f in frames])


def _audio_activity(f0, f1, character=None):
    """Loudness envelope of voice strips (music/SFX excluded) on the timeline, aligned to frames.

    With `character` (a rig name), voice strips tagged for other speakers (lip_sync_audio
    sets ``char3d_speaker``) are ignored, so in a dialog everyone reacts to their own voice.
    """
    from .audio import _sound_strips, analyze, load_audio
    sc = bpy.context.scene
    env = np.zeros(f1 - f0 + 1)
    used = []
    strips = _sound_strips(sc)
    if character is not None:
        mine = [st for st in strips if st.get("char3d_speaker") == character]
        tagged = any(st.get("char3d_speaker") for st in strips)
        strips = mine if tagged else strips
    fps = sc.render.fps
    for st in strips:
        if not st.sound or st.mute or st.get("char3d_audio_kind", "voice") != "voice":
            continue
        path = bpy.path.abspath(st.sound.filepath)
        if not os.path.isfile(path):
            continue
        samples, rate = load_audio(path)
        feat = analyze(samples, rate, fps)
        start = int(st.frame_start)
        for i, v in enumerate(feat["open"]):
            f = start + i
            if f0 <= f <= f1:
                env[f - f0] = max(env[f - f0], v * st.volume)
        used.append(st.name)
    return env, used


def _smooth(x, k=5):
    if len(x) < k:
        return x
    w = np.hanning(k + 2)[1:-1]
    return np.convolve(x, w / w.sum(), mode="same")


def _peaks(env, fps, min_gap_s=0.45, pct=75):
    """Emphasis moments: local maxima of the speech envelope above a percentile."""
    if env.max() <= 1e-6:
        return []
    thr = np.percentile(env[env > 1e-3], pct) if np.any(env > 1e-3) else 1.0
    gap = int(fps * min_gap_s)
    out, last = [], -10 ** 9
    for i in range(1, len(env) - 1):
        if env[i] >= thr and env[i] >= env[i - 1] and env[i] >= env[i + 1] and i - last >= gap:
            out.append(i)
            last = i
    return out


def _phrases(env, fps, gap_s=0.25):
    """(start, end) frame indices of speech runs separated by pauses."""
    on = env > max(1e-3, 0.12 * env.max())
    runs, s = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and s is None:
            s = i
        elif not v and s is not None:
            runs.append([s, i - 1])
            s = None
    merged = []
    for r in runs:
        if merged and (r[0] - merged[-1][1]) / fps < gap_s:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return merged


def _noise(t, seed):
    return (math.sin(t * 0.9 + seed) * 0.55 + math.sin(t * 1.7 + seed * 1.9) * 0.3
            + math.sin(t * 3.3 + seed * 0.4) * 0.15)


def _pulse(i, center, attack, release):
    """Smooth 0..1..0 bump peaking at `center`."""
    d = i - center
    if -attack <= d <= 0:
        return 0.5 - 0.5 * math.cos(math.pi * (d + attack) / attack)
    if 0 < d <= release:
        return 0.5 + 0.5 * math.cos(math.pi * d / release)
    return 0.0


def _target_point(target, frame):
    """World point to look at: "camera" (the shot active at frame), a character (its head)
    or any object (its origin)."""
    sc = bpy.context.scene
    if target == "camera":
        marks = sorted((m for m in sc.timeline_markers if m.camera and m.frame <= frame),
                       key=lambda m: m.frame)
        cam = marks[-1].camera if marks else sc.camera
        return cam.matrix_world.translation.copy() if cam else None
    obj = bpy.data.objects.get(target)
    if obj is None:
        return None
    rig = obj if obj.type == "ARMATURE" else (obj.parent if obj.parent and obj.parent.type == "ARMATURE" else None)
    if rig is not None:
        head = semantic_map(rig).get("head")
        if head:
            return head_frame(rig)[0]
    return obj.matrix_world.translation.copy()


def _look_target(look_at, frame):
    """look_at: a target name or a schedule [{"frame_start", "frame_end", "target"}]."""
    if isinstance(look_at, (list, tuple)):
        for item in look_at:
            if int(item["frame_start"]) <= frame <= int(item["frame_end"]):
                return item["target"]
        return None
    return look_at


def _camera_angles(head_pos, forward_q, frame, target="camera", point=None):
    """Yaw/pitch (deg, character space) from the head to the look target at frame."""
    point = point if point is not None else (_target_point(target, frame) if target else None)
    if point is None:
        return 0.0, 0.0
    d = forward_q.inverted() @ (point - head_pos)
    # character space: forward = -Y, left = +X, up = +Z
    yaw = math.degrees(math.atan2(d.x, -d.y))
    pitch = math.degrees(math.atan2(-d.z, math.hypot(d.x, d.y)))   # + = camera below eyes
    return yaw, pitch


def _speech_env(rig, base, f0, f1):
    """(envelope, audio strip names) of THIS character's speech: its own voice strips, or its
    lip-sync shape keys when it has no recording."""
    env, sources = _audio_activity(f0, f1, rig.name)
    if env.max() <= 1e-6 and base is not None:
        env = _viseme_activity(base, f0, f1)
        env = np.maximum(0.0, env - np.percentile(env, 5))   # a held smile is not speech
    return env, sources


@command("talk_motion")
def talk_motion(character, frame_start=None, frame_end=None, intensity=1.0, head=True, eyes=True,
                brows=True, look_at_camera=True, seed=3, look_at=None, listen_to=None, life=1.0,
                _defer_life=False):
    """Add speech-driven head nods/turns, brow flashes and eye saccades over a range.

    look_at: None = the shot camera (when look_at_camera), or a character/object name, or a
    schedule [{"frame_start", "frame_end", "target"}] (dialog: look at whoever talks).
    listen_to: another character — while they talk and this one is silent, add small
    listener nods on their stressed words.
    """
    from ..face_life import intensity as life_intensity
    life = life_intensity(life)
    rig = _rig_of(character)
    sc = bpy.context.scene
    fps = sc.render.fps
    f0 = int(frame_start if frame_start is not None else sc.frame_start)
    f1 = int(frame_end if frame_end is not None else sc.frame_end)
    if f1 <= f0:
        raise ValueError("frame_end must be after frame_start")
    k = float(intensity)
    if not math.isfinite(k) or k < 0:
        raise ValueError('intensity must be finite and non-negative')
    rng = random.Random(seed)

    base = None
    try:
        base = _basemesh(rig.name)
        _ensure_face(base)
    except (ValueError, RuntimeError):
        base = None                     # rigs without a face still get head motion

    if look_at is None:
        look_at = (listen_to if isinstance(listen_to, str) else (listen_to[0] if listen_to else None)) or ("camera" if look_at_camera else None)
    env, sources = _speech_env(rig, base, f0, f1)
    source = "audio:" + ",".join(sources) if sources else None
    if env.max() <= 1e-6 and base is not None:
        source = "lip_sync_keys"
    if env.max() <= 1e-6:
        source = "idle (no speech found)"
    else:
        env = _smooth(env / env.max(), 7)
    n = len(env)
    peaks = _peaks(env, fps)
    phrases = _phrases(env, fps)
    listen_peaks = []
    peers = [listen_to] if isinstance(listen_to, str) else listen_to or []
    for peer in peers:
        other = _rig_of(peer)
        try:
            other_base = _basemesh(other.name)
        except (ValueError, RuntimeError):
            other_base = None
        oenv, _src = _speech_env(other, other_base, f0, f1)
        if oenv.max() > 1e-6:
            oenv = _smooth(oenv / oenv.max(), 7)
            listen_peaks.extend(p for p in _peaks(oenv, fps, min_gap_s=1.2)
                                if env[p] < 0.15 and rng.random() < 0.6)
    listen_peaks = sorted(set(listen_peaks))

    # ---------------------------------------------------------------- head offsets per frame
    nod = np.zeros(n)
    turn = np.zeros(n)
    tilt = np.zeros(n)
    for i in range(n):
        t = (f0 + i) / fps
        talk = env[i]
        nod[i] = 1.6 * _noise(t, seed) * (0.6 + 0.8 * talk)
        turn[i] = 3.0 * _noise(t * 0.7, seed + 11) * (0.7 + 0.6 * talk)
        tilt[i] = 1.8 * _noise(t * 0.8, seed + 23)
    for p in peaks:                         # emphasis nods on stressed words
        amp = rng.uniform(3.5, 6.5) * env[p]
        for i in range(max(0, p - 6), min(n, p + 14)):
            nod[i] += amp * _pulse(i, p, 5, 12)
    for p in listen_peaks:                  # listener: small, slower acknowledging nods
        amp = rng.uniform(2.0, 3.5)
        for i in range(max(0, p - 8), min(n, p + 18)):
            nod[i] += amp * _pulse(i, p, 7, 14)
    for a, b in phrases:                    # phrase rhythm: slight tilt per phrase, settle at end
        side = rng.choice((-1, 1)) * rng.uniform(1.5, 3.0)
        for i in range(a, min(n, b + 10)):
            ramp = min(1.0, (i - a) / 8.0) * (1.0 if i <= b else max(0.0, 1 - (i - b) / 10.0))
            tilt[i] += side * ramp
        for i in range(b, min(n, b + 12)):
            nod[i] -= 1.5 * _pulse(i, b + 5, 5, 7)
    nod, turn, tilt = nod * k, turn * k, tilt * k

    smap = semantic_map(rig)
    neck_b, head_b = smap.get("neck"), smap.get("head")
    result = {"character": rig.name, "frames": [f0, f1], "driven_by": source,
              "emphasis_frames": [f0 + p for p in peaks], "phrases": len(phrases)}
    if listen_to:
        result["listener_nods"] = [f0 + p for p in listen_peaks]

    rq = rig.matrix_world.to_quaternion()
    if head and head_b:
        prev = {}
        chest_b = smap.get("chest")
        person = look_at is not None and look_at != "camera"
        bones = [b for b in (chest_b if person else None, neck_b, head_b) if b]
        # pass 1: record the untouched base pose for every frame BEFORE inserting keys, so
        # offsets never stack on top of keys we add (matters where the base has no keys)
        base_pose, target_points = {}, {}
        for i in range(n):
            sc.frame_set(f0 + i)
            base_pose[f0 + i] = {b: rig.pose.bones[b].matrix_basis.copy() for b in bones}
            target = _look_target(look_at, f0 + i)
            target_points[f0 + i] = _target_point(target, f0 + i) if target else None
        for i in range(n):
            f = f0 + i
            sc.frame_set(f)
            for b in bones:
                rig.pose.bones[b].matrix_basis = base_pose[f][b]
            bpy.context.view_layer.update()
            hp = rig.pose.bones[head_b]
            yaw_c, pitch_c = (0.0, 0.0)
            target = _look_target(look_at, f)
            body_turn = 0.0
            if target:
                if target == "camera":
                    yaw_c, pitch_c = _camera_angles(rig.matrix_world @ hp.head, rq, f, target,
                                                    target_points[f])
                    yaw_c, pitch_c = max(-35, min(35, yaw_c)) * 0.45, max(-20, min(20, pitch_c)) * 0.35
                else:
                    pos, facing = head_frame(rig)
                    point = target_points[f]
                    if isinstance(look_at, (list, tuple)) and point is not None:
                        cue = next((s for s in look_at if s["frame_start"] <= f <= s["frame_end"]), {})
                        cheat = math.radians(cue.get("cheat_deg", 0))
                        delta = point - pos
                        # Open faces a little to the current camera side of the
                        # conversation axis while keeping the eyeline within 18°.
                        side = delta.cross(Vector((0, 0, 1))) * cue.get("side_sign", 1.0)
                        if side.length > 1e-6:
                            point = pos + delta * math.cos(cheat) + side.normalized() * delta.length * math.sin(cheat)
                    yaw_c, pitch_c = _camera_angles(pos, facing, f, target, point)
                    if chest_b:
                        body_turn = math.copysign(min(45, max(0, abs(yaw_c) - 65) * 0.6), yaw_c)
                    yaw_c = max(-135, min(135, yaw_c - body_turn))
                    pitch_c = max(-40, min(40, pitch_c))
            q_char = (Quaternion((0, 0, 1), math.radians(turn[i] + yaw_c))
                      @ Quaternion((1, 0, 0), math.radians(nod[i] + pitch_c))
                      @ Quaternion((0, 1, 0), math.radians(tilt[i])))
            for bone, share in ((chest_b if person else None, 0),
                                (neck_b, 0.4), (head_b, 0.6 if neck_b else 1.0)):
                if not bone:
                    continue
                pb = rig.pose.bones[bone]
                if target and target != "camera":
                    if share == 0:
                        d = Quaternion((0, 0, 1), math.radians(body_turn))
                    else:
                        d = facing @ Quaternion().slerp(q_char, share) @ facing.inverted()
                else:
                    part = Quaternion().slerp(q_char, share)
                    d = rq @ part @ rq.inverted()
                mw = rig.matrix_world @ pb.matrix
                new = Matrix.LocRotScale(mw.translation, d @ mw.to_quaternion(), mw.to_scale())
                pb.matrix = rig.matrix_world.inverted() @ new
                bpy.context.view_layer.update()
                _key_rot(pb, f, prev)
                if share == 0 and target and target != "camera":
                    # Turning the chest also translates the head around the spine.
                    # Re-aim from that new origin instead of subtracting torso yaw
                    # from an angle measured before the torso moved.
                    pos, facing = head_frame(rig)
                    yaw_c, pitch_c = _camera_angles(pos, facing, f, target, point)
                    yaw_c = max(-135, min(135, yaw_c))
                    pitch_c = max(-40, min(40, pitch_c))
                    q_char = (Quaternion((0, 0, 1), math.radians(turn[i] + yaw_c))
                              @ Quaternion((1, 0, 0), math.radians(nod[i] + pitch_c))
                              @ Quaternion((0, 1, 0), math.radians(tilt[i])))
        result["head_bones"] = [b for b in (neck_b, head_b) if b]
        result["head_range_deg"] = {"nod": [round(float(nod.min()), 1), round(float(nod.max()), 1)],
                                    "turn": [round(float(turn.min()), 1), round(float(turn.max()), 1)],
                                    "tilt": [round(float(tilt.min()), 1), round(float(tilt.max()), 1)]}

    if base is not None:
        meshes = _face_meshes(base)
        if brows and peaks and life == 0:
            strongest = sorted(peaks, key=lambda p: -env[p])[:max(1, len(peaks) // 2)]
            for p in strongest:
                f = f0 + p
                v = min(0.45, 0.3 * k) * env[p]
                _set(meshes, {"browInnerUp": 0.0, "browOuterUpLeft": 0.0, "browOuterUpRight": 0.0}, f - 5)
                _set(meshes, {"browInnerUp": v, "browOuterUpLeft": v * 0.8, "browOuterUpRight": v * 0.8}, f)
                _set(meshes, {"browInnerUp": 0.0, "browOuterUpLeft": 0.0, "browOuterUpRight": 0.0}, f + 10)
            result["brow_flashes"] = len(strongest)
        if eyes:
            names = ["eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft", "eyeLookOutRight",
                     "eyeLookUpLeft", "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight"]

            def gaze(yaw, pitch):
                """yaw + = look to the character's left, pitch + = look down (degrees)."""
                g = dict.fromkeys(names, 0.0)
                h = min(1.0, abs(yaw) / 30.0)
                if yaw > 0:
                    g["eyeLookOutLeft"] = g["eyeLookInRight"] = h
                else:
                    g["eyeLookOutRight"] = g["eyeLookInLeft"] = h
                v = min(1.0, abs(pitch) / 25.0)
                key = "Down" if pitch > 0 else "Up"
                g[f"eyeLook{key}Left"] = g[f"eyeLook{key}Right"] = v
                return g

            saccades, t = [], f0
            phrase_starts = {f0 + a for a, _b in phrases}
            while t < f1:
                saccades.append(t)
                t += int(fps * rng.uniform(0.7, 2.2))
            prev_g = None
            for f in saccades:
                yaw_c = pitch_c = 0.0
                target = _look_target(look_at, f)
                if target:
                    sc.frame_set(f)
                    hp = rig.pose.bones[head_b] if head_b else None
                    if hp is not None:
                        if target == "camera":
                            yaw_c, pitch_c = _camera_angles(rig.matrix_world @ hp.head, rq, f, target)
                            yaw_c = max(-30, min(30, yaw_c)) * 0.55     # head covers the rest
                            pitch_c = max(-25, min(25, pitch_c)) * 0.65
                        else:
                            pos, facing = head_frame(rig)
                            yaw_c, pitch_c = _camera_angles(pos, facing, f, target)
                            yaw_c = max(-30, min(30, yaw_c))
                            pitch_c = max(-25, min(25, pitch_c))
                away = any(abs(f - s) < fps * 0.4 for s in phrase_starts) and rng.random() < 0.6
                if away:   # thinking glance at the start of a phrase
                    yaw = rng.choice((-1, 1)) * rng.uniform(10, 18)
                    pitch = rng.uniform(-10, -4)
                else:
                    yaw = yaw_c + rng.uniform(-3, 3) * k
                    pitch = pitch_c + rng.uniform(-2, 2) * k
                g = gaze(yaw, pitch)
                if prev_g is not None:
                    _set(meshes, prev_g, f - 1)      # hold, then snap in 2 frames (saccade)
                _set(meshes, g, f + 1)
                prev_g = g
            result["saccades"] = len(saccades)
        from .face_life import face_life
        peers = listen_to or (list(dict.fromkeys(s['target'] for s in look_at
                             if s.get('target') not in (None, 'camera', rig.name)))
                              if isinstance(look_at, (list, tuple)) else None)
        if not _defer_life:
            result['life'] = face_life(rig.name, f0, f1, intensity=min(2., life*k), seed=seed,
                                       listen_to=peers, eyes=eyes, brows=brows)
    sc.frame_set(f0)
    return result
