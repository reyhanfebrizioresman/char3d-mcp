"""Build a screenplay by composing the registered engine commands in-process."""
import json
import math
import random
import time
from contextlib import contextmanager

import bpy
from mathutils import Vector

from . import command, dispatch
from ..script_plan import parse_script


def _appearance(char, catalog, seed, warnings):
    """Resolve deferred asset names and accessories only against installed assets."""
    from .mpfb import _outfit_clothes
    from ..script_plan import CLOTHES

    ident = char["id"]
    args = {k: v for k, v in char.items() if k not in ("id", "assets", "accessories", "voice", "pitch", "pitch_offset", "rate")}
    args["seed"] = seed
    assets = catalog["assets"]
    metadata = catalog.get("clothing_metadata", {})
    rng = random.Random(seed)
    additions = []
    for asset in char.get("assets", []):
        if asset in assets.get("hair", []):
            args["hair"] = asset
        elif asset in assets.get("beards", []):
            args["beard"] = asset
        elif asset in assets.get("clothes", []):
            additions.append(asset)
        else:
            warnings.append(f"{ident}: unavailable catalog asset omitted: {asset!r}")
    if additions:
        args["clothes"] = list(dict.fromkeys(args.get("clothes", []) + additions))
        additions = []
    if "clothes" not in args and not args.get("outfit"):
        sex = "female" if char["gender"] < 0.5 else "male"
        args["clothes"] = [f"{sex}_casualsuit{rng.randint(1, 2):02d}", "shoes01"]
    for kind in ("hair", "clothes"):
        if kind not in args:
            continue  # Absent clothes allows create_realistic_human's outfit picker.
        chosen = [args[kind]] if kind == "hair" and args[kind] else args[kind] or []
        valid = [a for a in chosen if a in assets.get(kind, [])]
        if chosen != valid:
            warnings.append(f"{ident}: unavailable {kind} omitted: {sorted(set(chosen) - set(valid))}")
        args[kind] = (valid[0] if valid else None) if kind == "hair" else valid
    beard = args.get("beard")
    if beard is True:
        pool = sorted(assets.get("beards", []))
        args["beard"] = rng.choice(pool) if pool else None
        if not pool:
            warnings.append(f"{ident}: no installed beard/moustache; install optional MPFB packs")
    elif beard and beard not in assets.get("beards", []):
        warnings.append(f"{ident}: unavailable beard omitted: {beard!r}")
        args["beard"] = None
    for category in char.get("accessories", []):
        sex = "female" if char["gender"] < 0.5 else "male"
        pool = sorted(n for n, m in metadata.items() if m["category"] == category
                      and m["gender"] in (sex, "unisex"))
        if pool:
            additions.append(rng.choice(pool))
        else:
            warnings.append(f"{ident}: no installed {category}; install optional MPFB packs")
    if args.get("outfit") and not any(n not in CLOTHES and m["category"] in ("top", "bottom", "dress", "suit")
                                      for n, m in metadata.items()):
        warnings.append(f"{ident}: optional outfit packs unavailable; using installed system suits")
    if additions:
        if "clothes" not in args:
            args["clothes"], notes = _outfit_clothes(metadata, args["outfit"], char["gender"], seed)
            warnings.extend(f"{ident}: {note}" for note in notes)
        args["clothes"] = list(dict.fromkeys(args["clothes"] + additions))
    return args


@contextmanager
def _bones_only():
    """Defer skin evaluation during skeleton-only commands; restore even on failure.

    Seat contact, bounds and lights still see evaluated meshes. Secondary motion uses
    rest geometry and sampled bones, so it can also defer skin evaluation. This is the
    same viewport optimization used by walk_path's terrain bake, scoped to this build.
    """
    hidden = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_viewport
              and any(m.type == "ARMATURE" for m in o.modifiers)]
    try:
        for obj in hidden:
            obj.hide_viewport = True
        yield
    finally:
        for obj in hidden:
            obj.hide_viewport = False
        if hidden:
            bpy.context.view_layer.update()


def _skeleton(command_name, params):
    with _bones_only():
        return dispatch(command_name, params)


@command("script_to_scene")
def script_to_scene(script, name=None, environment=None, lighting="studio", camera="mixed",
                    subtitles=True, language="auto", seed=0, build=True, sound=True, look=None,
                    body_language=True, character_seeds=None):
    """Parse only, or build 1-4 talking characters and sequential physical beats. Never save."""
    from .anim import CLIPS, POSES
    from .dialog import line_frames, _look_schedule
    from .environment import PRESETS, PROPS
    from .lighting import PRESETS as LIGHTS
    from .semantic import load_words
    from .walk import _start as navigation_start
    from .interaction import preserve_interactions
    from .motion import preserve_motion, dialog_body, script_faces
    from ..motion_library import MOTIONS, FLOOR

    started = time.perf_counter()
    timings = {}

    @contextmanager
    def timed(stage):
        t = time.perf_counter()
        yield
        timings[stage] = round(time.perf_counter() - t + timings.get(stage, 0), 4)

    sc = bpy.context.scene
    with timed("parse"):
        plan = parse_script(script, name=name, environment=environment, seed=seed, fps=sc.render.fps, look=look)
        if camera not in ("mixed", "singles", "two_shot", "none"):
            raise ValueError("camera must be mixed, singles, two_shot or none")
        if plan["environment"] and plan["environment"] not in PRESETS:
            raise ValueError(f"unknown environment: {plan['environment']}")
        if lighting not in LIGHTS:
            raise ValueError(f"unknown lighting: {lighting}")
        if language not in ("auto", "id", "ms", "en", None):
            raise ValueError("language must be auto, id, ms or en")
    warnings = list(plan["warnings"])
    characters, shots = {}, []
    result = {"plan": plan, "characters": characters, "frames": plan["estimated_frames"],
              "shots": shots, "duration_s": round(plan["estimated_frames"][1] / sc.render.fps, 3),
              "warnings": warnings, "timings": timings}
    if not build:
        timings["total"] = round(time.perf_counter() - started, 4)
        return result

    # Validate known action names and audio readability before adding any objects.
    for beat in plan["beats"]:
        action = beat.get("do")
        valid_pose = beat.get("name") in POSES or (action == "gesture" and beat.get("name") in CLIPS)
        if action in ("pose", "gesture") and not valid_pose:
            warnings.append(f"Unknown pose/gesture {beat['name']!r}; using relaxed")
            beat["name"] = "relaxed"
        if "say" in beat:
            beat["speech_frames"] = line_frames(beat, sc.render.fps)
    sc.name = plan["name"]
    with timed("characters"):
        try:
            catalog = dispatch("mpfb_assets", {})
            realistic = bool(catalog["assets"].get("skins"))
        except RuntimeError:
            catalog, realistic = {}, False
        if not realistic:
            warnings.append("MPFB unavailable: using mannequins without facial animation; install scripts/install_mpfb.sh")
        for i, char in enumerate(plan["characters"]):
            ident = char["id"]
            objname = ident
            suffix = 1
            while objname in bpy.data.objects or f"{objname}_rig" in bpy.data.objects:
                objname = f"{ident}_{suffix}"
                suffix += 1
            if realistic:
                args = _appearance(char, catalog, (character_seeds or {}).get(ident, seed + i * 101), warnings)
                h = dispatch("create_realistic_human", {"name": objname, **args})
                warnings.extend(f"{ident}: {note}" for note in h.get("warnings", []))
                rig = h["armature"]
            else:
                h = dispatch("create_human", {"name": objname, "style": "realistic",
                    "gender": "female" if char["gender"] < 0.5 else "male", "arm_angle": 35})
                r = dispatch("auto_rig_humanoid", {"mesh": h["name"]})
                if not r["ok"]:
                    raise RuntimeError(f"rig failed: {r}")
                rig = r["armature"]
            characters[ident] = {"rig": rig, "mesh": h["name"], "realistic": realistic}
            if realistic and character_seeds is not None:
                characters[ident]["appearance"] = {**args,
                    **{k: h[k] for k in ("skin", "hair", "clothes", "beard", "outfit", "seed")}}
            _skeleton("apply_pose", {"armature": rig, "pose": "relaxed", "keyframe": True, "frame": 1})
    cast = [c["rig"] for c in characters.values()]
    prefix = f"{cast[0]}_Script"
    with timed("staging"):
        sc.frame_set(1)
        if len(cast) > 1:
            # Open torsos toward coverage while leaving a natural head/eye turn to peers.
            dispatch("stage_dialog", {"characters": cast, "cheat_deg": 55.0})
        if plan["environment"]:
            dispatch("set_environment", {"preset": plan["environment"], "subject": cast, "variant": abs(int(seed))})

    props, occupied, assigned_seats, body_started, looks, titles, lines = {}, set(), {}, set(), [], [], []
    preferred_seats = {}
    fps = sc.render.fps

    def initial_idle(ident, end):
        if ident in body_started:
            return
        body_started.add(ident)
        length = end - 1
        if length >= 4:
            # A brief breathing settle then a held posture. Speech supplies continuous
            # head/arm motion; retargeting a whole-scene idle adds dense body keys with
            # no useful change during conversation, and is costly on clothed MPFB rigs.
            period = min(24, length)
            _skeleton("animate", {"armature": characters[ident]["rig"], "clip": "idle",
                                "start_frame": 1, "cycles": 1, "speed": 96 * fps / 24 / period,
                                "amplitude": 0.15, "blend_frames": 0})

    def resolve(target, ident, seat=False):
        def seat_anchor(obj):
            anchor = obj.get("c3d_seat_anchor")
            if anchor:
                return anchor
            if obj.type == "EMPTY":
                first = next((o for o in obj.children_recursive if "c3d_seat_centers" in o), None)
                if first is not None:
                    return first.name
            return obj.name

        if target in characters:
            return characters[target]["rig"], 0
        previous = preferred_seats.get((ident, target)) if seat else None
        if previous and previous not in occupied:
            return previous
        if seat and target in props:
            anchor = seat_anchor(bpy.data.objects[props[target]])
            if (anchor, 0) not in occupied:
                return anchor, 0
        if target in props and not seat:
            return props[target], 0
        obj = bpy.data.objects.get(target)
        if obj:
            return seat_anchor(obj) if seat else obj.name, 0
        rig = bpy.data.objects[characters[ident]["rig"]]
        position = navigation_start(rig, sc.frame_current + 1)[1]
        candidates = []
        for o in sc.objects:
            if seat and "c3d_seat_centers" in o and (target in ("chair", "seat") or target in o.name.lower()):
                for i in range(len(json.loads(o["c3d_seat_centers"]))):
                    if (o.name, i) not in occupied:
                        candidates.append(((o.matrix_world.translation - position).length, o.name, i))
            elif not seat and o.get("c3d_prop_kind") == target:
                candidates.append(((o.matrix_world.translation - position).length, o.name, 0))
        if candidates:
            from .seating import _seat
            from .gaze import head_frame
            peers = [head_frame(bpy.data.objects[n])[0] for n in cast if n != rig.name]
            suitable = []
            for candidate in sorted(candidates):
                _, name, index = candidate
                if not seat or not peers:
                    suitable.append(candidate)
                    continue
                center, front, _, _ = _seat(name, index)
                other = min(peers, key=lambda p: (p-center).length)
                delta = other - center
                hidden = abs(delta.x) < 0.55 and delta.y < -0.15
                away = front.xy.dot(delta.xy) < 0
                if not hidden and not away:
                    suitable.append(candidate)
            if suitable:
                _, name, index = suitable[0]
                return name, index
            if seat and peers:
                from .navigation import footprints, _distance, Planner
                from .terrain import GroundQuery
                ground = GroundQuery()
                raw = footprints(rig, set(), ground, sc.frame_current)
                other = min(peers, key=lambda p: (p-position).length)
                front = Vector((other.x-position.x, other.y-position.y, 0)).normalized()
                if front.length < 1e-6:
                    front = Vector((1, 0, 0))
                side = Vector((-front.y, front.x, 0))
                location = None
                # Search the conversation's open floor, leaving room for both the
                # chair footprint and the approach. Never mutate on planning failure.
                for back in (0.1, 0.4, 0.7, 1.0):
                    for offset in (0, -0.4, 0.4, -0.8, 0.8):
                        point = position - front * back + side * offset
                        if any(float(_distance([list(point.xy)], poly)[0]) < 0.48 for _, poly in raw):
                            continue
                        approach = point + front * 0.45
                        route = [position.copy(), approach]
                        planner = Planner(rig, route, ground, set(), sc.frame_current)
                        try:
                            path = planner.plan(route, lambda r: [], escape=True)
                        except ValueError:
                            continue
                        if (path[-1]-approach).length > 0.08:
                            continue
                        location = point
                        break
                    if location is not None:
                        break
                if location is None:
                    raise ValueError(f"No clear guest-chair position for {ident}; specify an explicit seat")
                location.z = ground.sample(location.x, location.y)[0]
                rotation = math.degrees(math.atan2(front.x, -front.y))
                added = dispatch("add_prop", {"kind": "chair", "location": list(location), "rotation_z": rotation})
                props[target] = added["root"]
                note = f"{ident}: added guest chair {added['root']} facing the conversation; matching seats hide the sitter or face away"
                warnings.append(note)
                plan.setdefault("guest_chairs", []).append({"character": ident, "root": added["root"],
                    "location": list(location), "rotation_z": rotation, "reason": note})
                return seat_anchor(bpy.data.objects[added["root"]]), 0
        kind = "chair" if target == "seat" else target
        if kind not in PROPS:
            raise ValueError(f"unknown scene target: {target!r}")
        location = list(position)
        if seat:
            location[1] += 0.25
        added = dispatch("add_prop", {"kind": kind, "location": location})
        props[target] = added["root"]
        return seat_anchor(bpy.data.objects[added["root"]]) if seat else added["root"], 0

    with timed("body"):
        dispatch("set_timeline", {"frame_start": 1, "frame_end": 2})
        frame = 1
        for beat in plan["beats"]:
            start, end = frame, frame
            if "say" in beat:
                end = start + beat["speech_frames"] - 1
                ln = {"speaker": characters[beat["say"]]["rig"], "start_frame": start,
                      **{k: beat[k] for k in ("text", "audio", "words", "emotion", "body_emotion") if k in beat}}
                lines.append(ln)
                frame = end + 1 + round(0.35 * fps)
            elif "title" in beat:
                end = start + beat["estimated_frames"][1] - beat["estimated_frames"][0]
                titles.append(beat)
                frame = end + 1
            elif beat["do"] == "pause":
                end = start + max(1, round(beat["seconds"] * fps)) - 1
                frame = end + 1
            else:
                ident, action = beat["who"], beat["do"]
                rig = characters[ident]["rig"]
                initial_idle(ident, start - 1)
                sc.frame_set(max(1, start - 1))
                report = {}
                if action == "interact":
                    initial_idle(beat["with"], start - 1)
                    args = {"a": rig, "b": characters[beat["with"]]["rig"],
                            "kind": beat["kind"], "start_frame": start,
                            **{k: beat[k] for k in ("approach", "hold_seconds", "side") if k in beat}}
                    if beat.get("prop"):
                        prop, _ = resolve(beat["prop"], ident)
                        args["prop"] = prop
                        if bpy.data.objects[prop].get("c3d_hold_character") != rig:
                            dispatch("hold_prop", {"character": rig, "prop": prop,
                                "hand": beat.get("side", "right"), "start_frame": start})
                    report = dispatch("interact", args)
                    end = report["frames"]["end"]
                elif action == "walk":
                    target = beat["to"]
                    walk_args = {"armature": rig, "start_frame": start}
                    if isinstance(target, str):
                        obj, _ = resolve(target, ident, seat=target in ("chair", "seat", "sofa", "bench", "stool"))
                        target_obj = bpy.data.objects[obj]
                        point = (navigation_start(target_obj, start)[1] if target_obj.type == "ARMATURE"
                                 else target_obj.matrix_world.translation)
                        target = list(point.xy)
                        # Stop in front of a seat instead of walking through its back.
                        anchor = bpy.data.objects.get(target_obj.get("c3d_seat_anchor", ""))
                        if anchor is None and "c3d_seat_centers" in target_obj:
                            anchor = target_obj
                        if anchor is not None:
                            # Stop in front of the seat (its own front direction) and let
                            # obstacle avoidance ignore only that piece of furniture.
                            front = (anchor.matrix_world.to_3x3()
                                     @ Vector(anchor.get("c3d_seat_front", (0.0, -1.0, 0.0))))
                            front.z = 0.0
                            front = front.normalized() if front.length > 1e-6 else Vector((0, -1, 0))
                            target = [target[0] + 0.45 * front.x, target[1] + 0.45 * front.y]
                            walk_args["ignore"] = sorted(
                                {o.name for o in bpy.data.objects
                                 if o is anchor or o.get("c3d_seat_anchor") == anchor.name})
                        elif target_obj.type != "ARMATURE":
                            target[1] -= 0.45
                    report = _skeleton("walk_path", {**walk_args, "points": [target[:2]]})
                elif action in ("sit", "stand"):
                    dispatch("set_timeline", {"frame_end": start + 20})
                    args = {"character": rig, "start_frame": start}
                    if action == "sit":
                        occupied.discard(assigned_seats.pop(ident, None))
                        seat, index = resolve(beat["on"], ident, seat=True)
                        preferred_seats[ident, beat["on"]] = (seat, index)
                        occupied.add((seat, index))
                        assigned_seats[ident] = (seat, index)
                        args.update(seat=seat, seat_index=index)
                    else:
                        occupied.discard(assigned_seats.pop(ident, None))
                    report = dispatch("sit_on" if action == "sit" else "stand_up", args)
                    end = report["transition_end"]
                elif action == "hold":
                    prop, _ = resolve(beat["prop"], ident)
                    report = dispatch("hold_prop", {"character": rig, "prop": prop,
                        "hand": beat.get("hand", "right"), "start_frame": start})
                    end = start + 11
                elif action in ("pose", "gesture"):
                    if action == "gesture" and beat["name"] in CLIPS:
                        meta = MOTIONS.get(beat["name"], {})
                        for kind in meta.get("required_props", []):
                            from .motion import held_prop, held_props
                            if held_prop(bpy.data.objects[rig], kind, start) is None:
                                prop, _ = resolve(kind, ident)
                                obj = bpy.data.objects[prop]
                                if obj.get("c3d_hold_character") and obj.get("c3d_hold_release", start+1) > start:
                                    prop = dispatch("add_prop", {"kind": kind})["root"]
                                occupied_hands = {o["c3d_hold_hand"] for o in held_props(bpy.data.objects[rig], start)}
                                hand = next((h for h in ("right", "left") if h not in occupied_hands), None)
                                if hand is None:
                                    raise ValueError(f"{ident}: release a held prop before {beat['name']}")
                                dispatch("hold_prop", {"character": rig, "prop": prop, "hand": hand, "start_frame": start})
                        if meta.get("required_seat") and not bpy.data.objects[rig].get("c3d_seat_active"):
                            seat, index = resolve("chair", ident, seat=True)
                            dispatch("set_timeline", {"frame_end": start+20})
                            dispatch("sit_on", {"character": rig, "seat": seat, "seat_index": index, "start_frame": start})
                            start += 21
                        if beat["name"] == "type":
                            from .motion import prepare_typing
                            beat["created_props"] = prepare_typing(bpy.data.objects[rig])
                        args = {"armature": rig, "clip": beat["name"], "start_frame": start, "cycles": 1,
                                **{k: beat[k] for k in ("cycles", "bpm", "speed", "amplitude", "phase") if k in beat}}
                        if beat["name"] == "punch" and isinstance(beat.get("at"), str) and beat["at"] in characters:
                            partner = characters[beat["at"]]["rig"]
                            initial_idle(beat["at"], start-1)
                            turn = _skeleton("turn_to", {"armature": rig, "target": partner, "start_frame": start, "avoid": False})
                            args["start_frame"] = turn["next_start_frame"]
                        # Floor grounding measures evaluated skin, so keep it visible.
                        report = (dispatch if beat["name"] in FLOOR else _skeleton)("animate", args)
                        if beat["name"] == "punch" and isinstance(beat.get("at"), str) and beat["at"] in characters:
                            reaction = _skeleton("animate", {"armature": partner, "clip": "hit_react",
                                "start_frame": args["start_frame"]+round(report["cycle_frames"]*.18), "cycles": 1})
                            report["reaction"] = reaction
                            report["frames"][1] = max(report["frames"][1], reaction["frames"][1])
                    else:
                        _skeleton("apply_pose", {"armature": rig, "pose": beat["name"], "frame": start, "keyframe": True})
                        _skeleton("apply_pose", {"armature": rig, "pose": beat["name"], "frame": start + 23, "keyframe": True})
                        end = start + 23
                elif action == "look":
                    target = beat["at"]
                    if isinstance(target, str) and target != "camera":
                        target, _ = resolve(target, ident)
                    elif not isinstance(target, str):
                        marker = bpy.data.objects.new(prefix + "LookTarget", None)
                        sc.collection.objects.link(marker)
                        marker.location = tuple(target) if len(target) == 3 else (*target, 1.5)
                        target = marker.name
                    looks.append({"who": rig, "target": target, "frame_start": start})
                    end = start + 23
                if action not in ("sit", "stand", "hold", "pose", "look", "interact") and "frames" in report:
                    end = report["frames"][1]
                beat["result"] = report
                frame = end + 1
            beat["frames"] = [start, end]
            dispatch("set_timeline", {"frame_end": max(sc.frame_end, end)})
        final = max(2, frame - 1)
        for ident in characters:
            initial_idle(ident, final)
        dispatch("set_timeline", {"frame_start": 1, "frame_end": final})

    with timed("speech"):
        turns = []
        expression_results = {}
        for line in lines:
            start = line.pop("start_frame")
            d = dispatch("dialog", {"lines": [line], "characters": cast, "stage": False,
                         "start_frame": start, "language": language, "perform": False})
            turns.extend(d["lines"])
            warnings.extend(d["warnings"])
        for ident, char in characters.items():
            if not char["realistic"]:
                continue
            rig = char["rig"]
            dispatch("set_expression", {"character": rig, "expression": "smile", "strength": 0.35, "frame": 1, "keyframe": True})
            cues = [{"frame": b["frames"][0], "expression": b["emotion"], "strength": 0.65}
                    for b in plan["beats"] if b.get("say") == ident and b.get("emotion")]
            if cues or load_words(bpy.data.objects[char["mesh"]], 1, final):
                expression_results[rig] = dispatch("auto_expression", {"character": rig, "frame_start": 1, "frame_end": final,
                                              "language": language, "cues": cues})
            script_faces(rig, ident, plan["beats"])
    def make_cameras():
        with timed("cameras"):
            if turns and camera != "none":
                coverage = dispatch("dialog_direct", {"turns": turns, "characters": cast, "camera": camera,
                    "expression": None, "blink": False, "motion": False, "gestures": None, "idle": False,
                    "frame_start": 1, "frame_end": final, "shot_prefix": prefix,
                    "two_shot_angle": 20.0 if plan["environment"] == "office" else 0.0,
                    "shot": "medium_close" if plan["environment"] == "office" else "medium",
                    "single_angle_bias": 25.0,
                    "single_angle_limits": [-40.0, 80.0] if plan["environment"] == "office" else None})
                shots.extend(coverage.get("shots", []))
            else:
                # Even camera='none' builds a renderable scene, without editorial cuts.
                shot = dispatch("camera_shot", {"subject": cast, "shot": "medium_full", "angle": 0,
                    "start_frame": 1, "end_frame": final, "name": prefix + "Wide"})
                shots.append(shot)

    def interaction_shots():
        """Contact beats get a side-on two-shot: a speaker single would show the
        partner's back. Cuts back to the dialog coverage at its next shot."""
        from .gaze import head_frame
        for i, beat in enumerate(plan["beats"]):
            if beat.get("do") != "interact" or "frames" not in beat:
                continue
            lo, hi = beat["frames"]
            later = [s["frames"][0] for s in shots if s.get("frames") and s["frames"][0] > lo]
            hi = min([hi] + [f - 1 for f in later])
            if hi - lo < 12:
                continue
            pair = [characters[beat["who"]]["rig"], characters[beat["with"]]["rig"]]
            sc.frame_set((lo + hi) // 2)
            heads = [head_frame(bpy.data.objects[r])[0] for r in pair]
            axis = heads[1] - heads[0]
            normal = Vector((axis.y, -axis.x, 0))
            if normal.length < 1e-6:
                normal = Vector((0, -1, 0))
            normal.normalize()
            # Stay on the side of the coverage camera active at the beat (180 deg rule).
            cover = next((s for s in reversed(shots) if s.get("frames") and s["frames"][0] <= lo), None)
            cam = bpy.data.objects.get(cover["camera"]) if cover else None
            mid = (heads[0] + heads[1]) / 2
            ref = (cam.matrix_world.translation - mid) if cam else Vector((0, -1, 0))
            if normal.dot(Vector((ref.x, ref.y, 0))) < 0:
                normal = -normal
            angle = math.degrees(math.atan2(normal.x, -normal.y))
            shot = dispatch("camera_shot", {"subject": pair,
                "shot": "full",
                "angle": angle, "elevation": 6.0, "start_frame": lo, "end_frame": hi,
                "name": prefix + f"Interact{i:02d}"})
            shots.append(shot)
            back = hi + 1
            if cam is not None and back <= sc.frame_end and not any(m.frame == back for m in sc.timeline_markers):
                marker = sc.timeline_markers.new(f"{cam.name}_after{i:02d}", frame=back)
                marker.camera = cam
        shots.sort(key=lambda s: (s.get("frames") or [0])[0])

    if len(cast) == 1 or any(cue["target"] == "camera" for cue in looks):
        make_cameras()
        if len(cast) > 1:
            # Explicit camera glances need a provisional camera to sample. Final
            # coverage replaces these shots after the head performance is baked.
            shots.clear()
    with timed("performance"), _bones_only(), preserve_interactions(plan["beats"]), preserve_motion(plan["beats"]):
        if body_language:
            result["body_language"] = dialog_body(turns, cast, language, expression_results)
        for i, (ident, char) in enumerate(characters.items()):
            rig = char["rig"]
            if char["realistic"]:
                dispatch("auto_blink", {"character": rig, "frame_start": 1, "frame_end": final, "seed": seed + i * 13})
            # Each layer samples the untouched body once for the entire range. Calling
            # it per turn would sample the preceding turn's held keys as the next base,
            # accumulating head/arm offsets on characters without intervening body keys.
            others = [n for n in cast if n != rig]
            schedule = _look_schedule(rig, turns, others, 1, final) if turns else []
            for cue in looks:
                if cue["who"] == rig:
                    a = cue["frame_start"]
                    schedule = [dict(s, frame_end=min(s["frame_end"], a - 1))
                                for s in schedule if s["frame_start"] < a]
                    schedule.append({"frame_start": a, "frame_end": final, "target": cue["target"]})
            if turns or schedule:
                dispatch("talk_motion", {"character": rig, "frame_start": 1, "frame_end": final,
                    "look_at": schedule or None, "look_at_camera": not others, "seed": seed + 11 * i,
                    "listen_to": others[0] if len(others) == 1 else None})
            own_turns = [t for t in turns if t["speaker"] == rig]
            if own_turns:
                args = {"character": rig, "frame_start": 1, "frame_end": final,
                        "style": "calm", "seed": seed + i * 17}
                if not char["realistic"]:
                    args["cues"] = [{"frame": (t["start"] + t["end"]) // 2, "gesture": "you"}
                                    for t in own_turns]
                try:
                    dispatch("talk_gestures", args)
                except ValueError as exc:
                    if "no speech found" not in str(exc):
                        raise
                    warnings.append(f"{ident}: no speech signal; gestures skipped")
    if len(cast) > 1:
        make_cameras()
        if camera != "none":
            with timed("cameras"):
                interaction_shots()
    with timed("lighting"):
        dispatch("set_lighting", {"preset": lighting, "subject": cast})
    if "weather" in plan:
        with timed("weather"):
            result["weather"] = dispatch("set_weather", {"kind": plan["weather"], "seed": abs(int(seed))})
    if plan["look"] is not None:
        from ..cinematic import look_spec
        with timed("look"):
            cfg = look_spec(plan["look"])
            result["look"] = dispatch("cinematic_look", {"preset": cfg["preset"],
                **({"intensity": cfg["intensity"], "haze": cfg["haze"], "god_rays": cfg["rays"],
                    "bloom": cfg["bloom"], "dof": cfg["dof"], "particles": cfg["particles"],
                    "grade": cfg["grade"], "sun": {k: cfg[k] for k in ("elevation", "azimuth")}}
                   if cfg["preset"] != "none" else {})})
    with timed("graphics"):
        words_available = any(load_words(bpy.data.objects[c["mesh"]], 1, final) for c in characters.values())
        if subtitles and words_available:
            dispatch("add_subtitles", {"style": "classic"})
        else:
            dispatch("remove_subtitles", {})
            if subtitles:
                warnings.append("No word times available; subtitles disabled")
        if plan["title"]:
            dispatch("add_title", {"text": plan["title"], "style": "lower_third", "size": 0.7, "start_s": 0,
                "duration_s": min(2, final / fps), "name": prefix + "Title"})
        for i, beat in enumerate(titles):
            dispatch("add_title", {"text": beat["title"], "subtitle": beat.get("subtitle"), "style": "center",
                "start_s": (beat["frames"][0] - 1) / fps,
                "duration_s": (beat["frames"][1] - beat["frames"][0] + 1) / fps, "name": prefix + f"Title{i}"})
    with timed("secondary_motion"), _bones_only():
        for char in characters.values():
            dispatch("secondary_motion", {"character": char["rig"], "parts": ["hair", "clothes"],
                                          "frame_start": 1, "frame_end": final})
    dispatch("set_timeline", {"frame_start": 1, "frame_end": final})
    if sound:
        with timed("sound"):
            result["sfx"] = dispatch("auto_sfx", {"characters": cast, "seed": seed})
    else:
        result["sfx"] = {"strips": [], "counts": {}}
    sc.frame_set(1)
    warnings[:] = list(dict.fromkeys(warnings))
    timings["total"] = round(time.perf_counter() - started, 4)
    result.update(frames=[1, final], duration_s=round(final / fps, 3), lines=turns)
    return result
