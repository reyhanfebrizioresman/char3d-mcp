"""Conversations between characters: staging, turn-taking performance and coverage cameras.

The MCP `dialog` tool lip-syncs each line (audio or text) back to back, then calls
dialog_direct, which layers on top of the lip sync:
  * gaze — everyone looks at whoever is talking; the talker looks at the person they
    answer (talk_motion with a look_at schedule), listeners nod on the talker's stressed
    words (listen_to),
  * gestures — talk_gestures per character, driven only by their own voice,
  * blinks, a light base expression, an idle body clip when the rig has no animation,
  * cameras — an establishing two-shot, then a clean single of each speaker, cut a few
    frames before they start talking, all from the same side (180° rule).
"""
import math

import bpy
from mathutils import Vector

from . import command
from .talk import _rig_of


def _facing_az(rig):
    """World azimuth (deg) the character faces: 0 = -Y (towards the default camera)."""
    d = rig.matrix_world.to_3x3() @ Vector((0.0, -1.0, 0.0))
    return math.degrees(math.atan2(d.x, -d.y))


@command("stage_dialog")
def stage_dialog(characters, layout="angled", distance=1.3, cheat_deg=35.0, center=(0.0, 0.0)):
    """Place 2-4 characters for a conversation, facing each other but opened towards the
    camera side (-Y). layout: angled (TV 'cheat'), face_to_face, side_by_side."""
    if layout not in ("angled", "face_to_face", "side_by_side"):
        raise ValueError("layout must be angled, face_to_face or side_by_side")
    rigs = [_rig_of(c) for c in characters]
    if not 2 <= len(rigs) <= 4:
        raise ValueError("stage_dialog needs 2 to 4 characters")
    n = len(rigs)
    cx, cy = float(center[0]), float(center[1])
    pos = []
    for i in range(n):
        u = (i - (n - 1) / 2)
        x = cx + u * float(distance)
        bulge = 0.0 if n == 2 else 1 - (2 * abs(u) / (n - 1)) ** 2
        pos.append((x, cy + 0.35 * float(distance) * bulge))
    gx = sum(p[0] for p in pos) / n
    gy = sum(p[1] for p in pos) / n
    out = []
    for rig, (x, y) in zip(rigs, pos):
        if layout == "side_by_side":
            az = 12.0 * math.copysign(1.0, gx - x) if abs(gx - x) > 1e-6 else 0.0
        else:
            az = math.degrees(math.atan2(gx - x, -(gy - y)))       # towards the group centre
            if layout == "angled" and abs(az) > cheat_deg:
                az -= math.copysign(float(cheat_deg), az)
        rig.rotation_mode = "XYZ"
        rig.location.x, rig.location.y = x, y
        rig.rotation_euler.z = math.radians(az)
        out.append({"character": rig.name, "location": [round(x, 3), round(y, 3)],
                    "facing_deg": round(az, 1)})
    bpy.context.view_layer.update()
    return {"layout": layout, "characters": out, "fps": bpy.context.scene.render.fps}


def _merge_turns(turns):
    """Consecutive lines of the same speaker become one turn."""
    out = []
    for t in sorted(turns, key=lambda t: int(t["start"])):
        if out and out[-1]["speaker"] == t["speaker"]:
            out[-1]["end"] = max(out[-1]["end"], int(t["end"]))
        else:
            out.append({"speaker": t["speaker"], "start": int(t["start"]), "end": int(t["end"])})
    return out


def _addressee(turns, i, speaker, others):
    """Who the speaker of turn i talks to: the previous different speaker, else the next."""
    for j in list(range(i - 1, -1, -1)) + list(range(i + 1, len(turns))):
        if turns[j]["speaker"] != speaker:
            return turns[j]["speaker"]
    return others[0] if others else None


def _look_schedule(char, turns, others, f0, f1):
    """[{frame_start, frame_end, target}] for one character over the whole scene."""
    sched = []
    for i, t in enumerate(turns):
        a = f0 if i == 0 else t["start"]
        b = f1 if i == len(turns) - 1 else turns[i + 1]["start"] - 1
        target = t["speaker"] if t["speaker"] != char else _addressee(turns, i, char, others)
        if target and b >= a:
            sched.append({"frame_start": a, "frame_end": b, "target": target})
    return sched


@command("dialog_direct")
def dialog_direct(turns, characters=None, camera="mixed", shot="medium", two_shot="medium_full",
                  move="static", lead_frames=4, gestures="presenter", expression="smile",
                  expression_strength=0.3, blink=True, motion=True, idle=True,
                  frame_start=None, frame_end=None, shot_prefix="Dialog", two_shot_angle=0.0,
                  single_angle_bias=-25.0, single_angle_limits=None):
    """Perform lip-synced dialog lines: gaze, listener nods, gestures, blinks and cameras.

    turns: [{"speaker": rig name, "start": frame, "end": frame}] (from lip sync).
    camera: mixed (two-shot first, then singles), singles, two_shot, none.
    Positive single_angle_bias covers the speaker from the listener's side;
    the default negative bias opens singles toward the scene front (-Y).
    single_angle_limits optionally clamps that azimuth to a set's clear camera aisle.
    """
    from .anim import animate
    from .camera import camera_shot
    from .face import auto_blink, set_expression
    from .gesture import talk_gestures
    from .talk import talk_motion

    if camera not in ("mixed", "singles", "two_shot", "none"):
        raise ValueError("camera must be mixed, singles, two_shot or none")
    if not turns:
        raise ValueError("no turns")
    sc = bpy.context.scene
    turns = [dict(t, speaker=_rig_of(t["speaker"]).name) for t in turns]
    merged = _merge_turns(turns)
    names = [_rig_of(c).name for c in characters] if characters else []
    for t in merged:
        if t["speaker"] not in names:
            names.append(t["speaker"])
    rigs = {n: _rig_of(n) for n in names}
    f0 = int(frame_start if frame_start is not None else max(sc.frame_start, merged[0]["start"] - 12))
    f1 = int(frame_end if frame_end is not None else merged[-1]["end"] + 18)
    sc.frame_end = max(sc.frame_end, f1)
    report = {"frames": [f0, f1], "turns": merged, "characters": names}

    if idle:
        idled = []
        for n, rig in rigs.items():
            ad = rig.animation_data
            if ad is None or ad.action is None:
                animate(n, "idle", start_frame=f0, cycles=max(1, math.ceil((f1 - f0 + 1) / 96)))
                idled.append(n)
        report["idle_added"] = idled

    if expression:
        for n in names:
            try:
                set_expression(n, expression, strength=float(expression_strength), frame=f0,
                               keyframe=True)
            except (ValueError, RuntimeError):
                pass      # no face shapes (mannequin)

    shots = []
    if camera != "none":
        plan = []                     # (start, speaker or None for a two-shot)
        if camera == "two_shot":
            plan = [(f0, None)]
        else:
            for i, t in enumerate(merged):
                cut = f0 if i == 0 else max(f0 + 1, t["start"] - int(lead_frames))
                single = not (camera == "mixed" and i == 0 and len(names) > 1)
                plan.append((cut, t["speaker"] if single else None))
        plan = [p for k, p in enumerate(plan) if k == 0 or p[0] > plan[k - 1][0]]
        for k, (a, who) in enumerate(plan):
            b = (plan[k + 1][0] - 1) if k + 1 < len(plan) else f1
            if b <= a:
                continue
            if who is None:
                angle, subj, size = float(two_shot_angle), names, two_shot
            else:
                az = _facing_az(rigs[who])
                bias = float(single_angle_bias)
                angle = (az - math.copysign(min(-bias, abs(az)), az) if bias <= 0 else
                         az + math.copysign(bias, az)) if abs(az) > 1e-3 else 0.0
                if single_angle_limits is not None:
                    angle = max(float(single_angle_limits[0]), min(float(single_angle_limits[1]), angle))
                subj, size = [who], shot
            r = camera_shot(subject=subj, shot=size, move=move, start_frame=a, end_frame=b,
                            angle=angle, elevation=3.0, intensity=0.35, name=f"{shot_prefix}{k + 1:02d}")
            shots.append({"camera": r.get("camera", f"Dialog{k + 1:02d}"), "frames": [a, b],
                          "subject": "two_shot" if who is None else who,
                          "angle": round(angle, 1)})
        report["shots"] = shots

    for i, (n, rig) in enumerate(rigs.items()):
        others = [m for m in names if m != n]
        if blink:
            try:
                auto_blink(n, f0, f1, seed=7 + 13 * i)
            except (ValueError, RuntimeError):
                pass
        if motion:
            sched = _look_schedule(n, merged, others, f0, f1)
            r = talk_motion(n, f0, f1, look_at=sched, look_at_camera=False, seed=3 + 11 * i,
                            listen_to=others[0] if len(others) == 1 else None)
            report.setdefault("motion", {})[n] = {"listener_nods": len(r.get("listener_nods", [])),
                                                  "emphasis": len(r.get("emphasis_frames", []))}
        if gestures:
            try:
                g = talk_gestures(n, f0, f1, style=gestures, seed=5 + 17 * i)
                report.setdefault("gestures", {})[n] = {
                    "beats": len(g.get("gestures", [])),
                    "semantic": [s["word"] for s in g.get("semantic", [])]}
            except ValueError:
                pass          # this character never speaks
    sc.frame_set(f0)
    return report


def line_frames(line, fps):
    """Use the lip-sync commands' duration rules before authoring any body motion."""
    from .face import text_tokens
    if line.get("audio"):
        from .audio import load_audio, _resolve
        samples, rate = load_audio(_resolve(line["audio"]))
        if not len(samples):
            raise ValueError("audio file is empty")
        return math.ceil(len(samples) * fps / rate) + 2
    return int(round(1 + len(text_tokens(line["text"])) * fps / 14.0)) + 3


@command("dialog")
def dialog(lines, characters=None, stage=True, layout="angled", distance=1.3,
           start_frame=1, gap_s=0.35, camera="mixed", shot="medium",
           gestures="presenter", expression="smile", language=None, perform=True):
    """In-process dialog for scene orchestration. Audio accepts pre-transcribed `words`.

    perform=False authors only speech, leaving performance/cameras for a later pass.
    Mannequins retain real word times and sound but cannot animate a missing face.
    Whisper preparation belongs in the MCP process, never inside Blender.
    """
    from .face import _basemesh, _ensure_face, lip_sync, text_tokens
    from .audio import lip_sync_audio, add_audio, load_audio, analyze, _resolve, _words_from_text, _strips
    from .semantic import store_words, text_word_frames

    if not lines or any(not ln.get("speaker") or not (ln.get("text") or ln.get("audio")) for ln in lines):
        raise ValueError("each dialog line needs speaker and text or audio")
    cast = characters or list(dict.fromkeys(ln["speaker"] for ln in lines))
    if stage and len(cast) > 1:
        stage_dialog(cast, layout=layout, distance=distance)
    sc = bpy.context.scene
    fps, frame, turns, warnings = sc.render.fps, int(start_frame), [], []
    for ln in lines:
        frame += round(float(ln.get("delay_s", 0)) * fps)
        base = _basemesh(ln["speaker"])
        try:
            _ensure_face(base)
            face = True
        except (ValueError, RuntimeError):
            face = False
        if face:
            if ln.get("audio"):
                r = lip_sync_audio(ln["speaker"], ln["audio"], start_frame=frame,
                                   words=ln.get("words"), text=ln.get("text"), language=language)
            else:
                r = lip_sync(ln["speaker"], ln["text"], start_frame=frame, language=language)
            a, b = r["frames"]
        else:
            a, b = frame, frame + line_frames(ln, fps) - 1
            if ln.get("audio"):
                samples, rate = load_audio(_resolve(ln["audio"]))
                feat = analyze(samples, rate, fps)
                words = ln.get("words") or _words_from_text(ln.get("text", ""), feat, fps)
                word_frames = [(w["word"], a + float(w["start"]) * fps,
                                a + float(w["end"]) * fps) for w in words]
                sound = add_audio(ln["audio"], start_frame=a)
                _strips(sc.sequence_editor)[sound["strip"]]["char3d_speaker"] = _rig_of(ln["speaker"]).name
            else:
                word_frames = text_word_frames(ln["text"], a, fps / 14.0, text_tokens)
            store_words(base, word_frames, a, b)
            warnings.append(f"{ln['speaker']}: no face shapes; speech timing/audio only")
        turns.append({"speaker": ln["speaker"], "start": a, "end": b, "text": ln.get("text")})
        frame = b + 1 + round(float(ln.get("pause_s", gap_s)) * fps)
    sc.frame_end = max(sc.frame_end, turns[-1]["end"])
    report = dialog_direct(turns, characters=cast, camera=camera, shot=shot,
                           gestures=gestures, expression=expression) if perform else {
                               "frames": [int(start_frame), turns[-1]["end"]], "shots": []}
    return {**report, "lines": turns, "next_start_frame": max(frame, report["frames"][1] + 1),
            "warnings": list(dict.fromkeys(warnings))}
