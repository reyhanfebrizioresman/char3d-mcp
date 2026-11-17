"""Contact-driven procedural Foley, with owned/reusable timeline strips."""
import json
import math

import bpy
import numpy as np
from mathutils import Vector

from .. import context, sfx_synthesis as synth
from . import command
from .audio import _sound_strips, _strips, _key_volume, _volume_curve, add_audio
from .footlock import _legs, _sole_points, _detect_contacts, _intervals
from .terrain import GroundQuery
from .talk import _rig_of

KINDS = {"footsteps", "sit", "stand", "cloth", "ambience"}


def record_seat_event(rig, kind, seat, first, last):
    """Persist transition times; later seat bakes replace the future body keys."""
    events = json.loads(rig.get("c3d_seat_events", "[]"))
    events = [e for e in events if e["start"] < first]
    events.append({"kind": kind, "seat": seat, "start": first, "end": last,
                   "frame": last if kind == "sit" else first + max(1, (last - first) // 4)})
    rig["c3d_seat_events"] = json.dumps(events)


def _preset():
    sc = bpy.context.scene
    for owner in [sc] + [o for o in sc.objects if o.get("c3d_role") == "environment"]:
        for key in ("c3d_environment_preset", "c3d_env_preset", "char3d_environment_preset"):
            if owner.get(key):
                return str(owner[key])
    names = ("podcast_studio", "classroom", "office", "living_room", "news_desk", "stage",
             "city_street", "park", "cafe_terrace", "beach")
    return next((n for n in names if bpy.data.objects.get("Env_" + n)), "studio")


def _surface_label(label):
    label = label.lower()
    aliases = {"wood": ("wood", "timber", "parquet"), "concrete": ("concrete", "tile", "stone", "asphalt"),
               "carpet": ("carpet", "rug"), "grass": ("grass", "lawn"),
               "gravel": ("gravel", "pebble"), "sand": ("sand", "beach")}
    return next((k for k, words in aliases.items() if any(w in label for w in words)), None)


def _surface_at(point, preset):
    """Downward ray against ground/walkable meshes, honoring explicit surface tags."""
    sc = bpy.context.scene
    best, surface = -float("inf"), None
    deps = bpy.context.evaluated_depsgraph_get()
    for obj in sc.objects:
        if obj.type != "MESH" or obj.hide_render or not (
                obj.get("char3d_walkable") or any(w in obj.name.lower() for w in ("floor", "ground"))):
            continue
        ev = obj.evaluated_get(deps)
        inv = ev.matrix_world.inverted_safe()
        origin = point + Vector((0, 0, .15))
        direction = inv.to_3x3() @ Vector((0, 0, -1))
        hit, local, _normal, face = ev.ray_cast(inv @ origin, direction)
        if not hit:
            continue
        z = (ev.matrix_world @ local).z
        if z <= best:
            continue
        material = ""
        if 0 <= face < len(ev.data.polygons):
            index = ev.data.polygons[face].material_index
            if index < len(ev.material_slots) and ev.material_slots[index].material:
                material = ev.material_slots[index].material.name
        label = str(obj.get("char3d_surface", obj.get("c3d_surface", "")))
        label += " " + str(obj.get("char3d_terrain_surface", ""))
        surface = _surface_label(label) or _surface_label(material + " " + obj.name)
        best = z
    return surface or {"office": "carpet", "classroom": "concrete", "living_room": "wood",
                       "stage": "wood", "park": "grass", "beach": "sand",
                       "city_street": "concrete", "cafe_terrace": "concrete"}.get(preset, "wood")


def detect_motion(rig, first, last):
    """Sample evaluated heel/ball/toe and hips; share foot_lock's contact detector.

    Initial planted feet are silent. Motionless standing/seated holds produce no steps.
    Returns contacts and stored (or inferred) seat transitions.
    """
    sc = bpy.context.scene
    fps = sc.render.fps / sc.render.fps_base
    legs, smap = _legs(rig)
    if not legs or not smap.get("hips"):
        raise ValueError(f"{rig.name}: no recognisable humanoid hips/feet")
    floor = rig.matrix_world.translation.z
    ground = GroundQuery(floor)
    sole = {s: _sole_points(rig, leg, floor) for s, leg in legs.items()}
    pts = {s: [] for s in legs}
    hips = []
    deps = bpy.context.evaluated_depsgraph_get()
    for f in range(first, last + 1):
        sc.frame_set(f)
        ev = rig.evaluated_get(deps)
        mw = ev.matrix_world
        hips.append((mw @ ev.pose.bones[smap["hips"]].matrix).translation.copy())
        for s, leg in legs.items():
            fw = mw @ ev.pose.bones[leg["foot"]].matrix
            pts[s].append([fw @ p for p in sole[s]])
    n = len(hips)
    raw = []
    for i in range(n):
        a, b = max(0, i - 1), min(n - 1, i + 1)
        d = (hips[b] - hips[a]) / max(1, b - a)
        raw.append(Vector((d.x, d.y, 0)))
    win = max(1, round(.2 * fps))
    velocity = [sum(raw[max(0, i-win):i+win+1], Vector()) / len(raw[max(0, i-win):i+win+1])
                for i in range(n)]
    leg = next(iter(legs.values()))
    B, mw = rig.data.bones, rig.matrix_world
    length = sum((mw.to_3x3() @ (B[leg[b]].tail_local - B[leg[b]].head_local)).length
                 for b in ("thigh", "shin"))
    events = json.loads(rig.get("c3d_seat_events", "[]"))
    if not events:
        # Broad sustained hip drops/rises; reject gait bob and brief crouches/jumps.
        z = np.array([p.z for p in hips])
        standing = float(np.percentile(z, 90))
        for a, b in _intervals(z < standing - .22 * length, fill=2, min_len=max(6, round(.4 * fps))):
            if a > 0:
                events.append({"kind": "sit", "start": first+a, "end": first+a,
                               "frame": first+a, "seat": "inferred"})
            if b < n - 1:
                events.append({"kind": "stand", "start": first+b+1, "end": first+b+1,
                               "frame": first+b+1, "seat": "inferred"})
    contacts = []
    stationary = max((Vector((p.x-hips[0].x, p.y-hips[0].y, 0)).length for p in hips), default=0) < .18 * length
    for s in legs:
        intervals, _speed, _low = _detect_contacts(pts[s], velocity, fps, floor, .045 * length, ground)
        if stationary:
            heights = [min(p.z - ground.sample(p.x, p.y)[0] for p in points) for points in pts[s]]
            if max(heights) - min(heights) > .06 * length:
                # Treadmill/in-place clips slide their supporting sole backwards. The
                # stationary body cannot supply foot_lock's virtual travel direction;
                # repeated near-floor intervals still identify the support phases.
                intervals = _intervals([h < .045 * length for h in heights])
        for a, b in intervals:
            if a == 0:  # already planted before the sampled range
                continue
            # IK's broad near-floor tolerance anticipates support for blending. Foley
            # waits for the sole to settle at the contact's actual ground clearance.
            heights = [min(p.z - ground.sample(p.x, p.y)[0] for p in pts[s][i])
                       for i in range(a, b + 1)]
            threshold = min(heights) + .003 * length
            a += next((i for i, h in enumerate(heights) if h <= threshold), 0)
            if any(e["start"] <= first+a <= e["end"] for e in events):
                continue  # seat bakes gather/slide feet, rather than making gait steps
            point = min(pts[s][a], key=lambda p: p.z - ground.sample(p.x, p.y)[0])
            gait_speed = max(v.length * fps for v in raw[max(0, a-6):min(n, a+4)])
            # In-place walk/mocap speed comes from the preceding swing, not root travel.
            swing = max(((pts[s][i][1] - pts[s][i-1][1]).length * fps
                         for i in range(max(1, a-8), a+1)), default=0)
            if gait_speed < .06 and swing < .12:
                continue
            contacts.append({"frame": first+a, "end": first+b, "side": s,
                             "point": list(point), "speed_m_s": round(max(gait_speed, swing * .4), 4)})
    return sorted(contacts, key=lambda e: (e["frame"], e["side"])), events


def _remove_owned(sc, first, last, characters, kinds):
    removed = []
    if sc.sequence_editor is None:
        return removed
    strips = _strips(sc.sequence_editor)
    for strip in list(_sound_strips(sc)):
        if not strip.get("char3d_auto_sfx") or strip.get("char3d_sfx_kind") not in kinds:
            continue
        if strip.get("char3d_sfx_character", "") not in characters | {""}:
            continue
        if strip.frame_final_start > last or strip.frame_final_end <= first:
            continue
        if strip.get("char3d_sfx_kind") != "ambience" and strip.frame_final_start < first:
            continue
        # Ambience spanning a cropped edit keeps both unaffected portions.
        a, b = int(strip.frame_final_start), int(strip.frame_final_end)
        pieces = [(a, first), (last + 1, b)] if strip.get("char3d_sfx_kind") == "ambience" else []
        for lo, hi in pieces:
            if hi <= lo:
                continue
            copy = strips.new_sound(strip.name + "_keep", strip.sound.filepath, strip.channel, int(strip.frame_start))
            copy.frame_final_start, copy.frame_final_end = lo, hi
            copy.volume = strip.get("char3d_volume", strip.volume)
            for key in strip.keys():
                copy[key] = strip[key]
            _key_volume(copy)
        curve = _volume_curve(strip)
        if curve:
            curve.keyframe_points.clear()
        removed.append(strip.name)
        strips.remove(strip)
    return removed


@command("auto_sfx")
def auto_sfx(characters=None, kinds=None, surface="auto", volume=1.0, seed=0,
             frame_start=None, frame_end=None, clear=False):
    """Replace owned Foley in range; sit includes stand, cloth is optional, clear only removes."""
    default = sorted(KINDS) if clear else ["footsteps", "sit", "ambience"]
    kinds = list(dict.fromkeys(default if kinds is None else kinds))
    if any(k not in KINDS for k in kinds):
        raise ValueError(f"kinds must be drawn from {sorted(KINDS)}")
    if "sit" in kinds and "stand" not in kinds:
        kinds.append("stand")
    surface = {"tile": "concrete", "concrete/tile": "concrete"}.get(surface, surface)
    if surface != "auto" and surface not in synth.SURFACES:
        raise ValueError(f"surface must be auto, tile or one of {list(synth.SURFACES)}")
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("volume must be finite and nonnegative")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    sc = bpy.context.scene
    first = int(sc.frame_start if frame_start is None else frame_start)
    last = int(sc.frame_end if frame_end is None else frame_end)
    if first < sc.frame_start or last > sc.frame_end or last < first or last - first > 24000:
        raise ValueError("range must be within the scene and at most 24000 frames")
    rigs = ([_rig_of(n) for n in characters] if characters is not None else
            [o for o in sc.objects if o.type == "ARMATURE" and not o.hide_render and not o.name.startswith("__")])
    rigs = list({r.name: r for r in rigs}.values())
    selected = {r.name for r in rigs}
    if characters is None and clear:
        selected |= {s.get("char3d_sfx_character", "") for s in _sound_strips(sc)}
    removed = _remove_owned(sc, first, last, selected, set(kinds))
    result = {"frames": [first, last], "strips": [], "counts": {k: 0 for k in sorted(KINDS)},
              "removed": removed, "touchdowns": [], "seed": seed, "sample_rate": synth.RATE}
    if clear or not kinds:
        return result
    saved_frame, saved_end = sc.frame_current, sc.frame_end
    fps = sc.render.fps / sc.render.fps_base
    preset = _preset()
    directory = context.resolve("sfx/generated", "imports")

    def add(samples, frame, kind, character="", gain=1.0, **metadata):
        path, digest = synth.write_cached(samples, directory)
        # Pack nonoverlapping sounds on channels rather than exhausting 128 channels.
        end = min(last + 1, frame + math.ceil(len(samples) / synth.RATE * fps))
        se = sc.sequence_editor or sc.sequence_editor_create()
        used = {s.channel for s in _strips(se) if s.frame_final_start < end and s.frame_final_end > frame}
        channel = next((c for c in range(1, 129) if c not in used), None)
        if channel is None:
            raise ValueError("auto_sfx needs a free sequencer channel")
        info = add_audio(path, frame, volume * gain, channel, name=f"SFX_{kind}_{character}_{frame}", kind="sfx")
        strip = _strips(se)[info["strip"]]
        strip.frame_final_end = min(int(strip.frame_final_end), last + 1)
        strip["char3d_auto_sfx"] = True
        strip["char3d_sfx_kind"], strip["char3d_sfx_character"] = kind, character
        strip["char3d_sfx_hash"] = digest
        result["strips"].append({"name": strip.name, "kind": kind, "character": character,
                                  "frame": frame, "end": int(strip.frame_final_end)-1,
                                  "path": path, "hash": digest, "volume": round(volume * gain, 5), **metadata})
        result["counts"][kind] += 1
        return strip

    hidden = [o for o in sc.objects if o.type == "MESH" and not o.hide_viewport
              and any(m.type == "ARMATURE" for m in o.modifiers)]
    try:
        for obj in hidden:
            obj.hide_viewport = True
        for rig in rigs:
            if not rig.animation_data or not rig.animation_data.action:
                continue
            if not set(kinds) & {"footsteps", "cloth", "sit", "stand"}:
                continue
            # A short preroll prevents a cropped range's first planted foot becoming a new step.
            steps, seats = detect_motion(rig, max(sc.frame_start, first - round(fps)), last)
            for event in steps:
                f = event["frame"]
                if not first <= f <= last:
                    continue
                event = dict(event, character=rig.name)
                result["touchdowns"].append(event)
                sc.frame_set(f)
                material = _surface_at(Vector(event["point"]), preset) if surface == "auto" else surface
                rng = synth.rng_for(seed, rig.name, f, event["side"], "footsteps")
                gain = min(1.25, .50 + .28 * event["speed_m_s"]) * rng.uniform(.9, 1.1)
                if "footsteps" in kinds:
                    add(synth.footstep(material, rng), f, "footsteps", rig.name, gain,
                        side=event["side"], surface=material, speed_m_s=event["speed_m_s"])
                if "cloth" in kinds:
                    add(synth.movement("cloth", False, synth.rng_for(seed, rig.name, f, "cloth")),
                        f, "cloth", rig.name, .22)
            for event in seats:
                f, kind = event["frame"], event["kind"]
                if first <= f <= last and kind in kinds:
                    soft = "sofa" in event["seat"].lower()
                    add(synth.movement(kind, soft, synth.rng_for(seed, rig.name, f, kind)),
                        f, kind, rig.name, .75, seat=event["seat"])
        if "ambience" in kinds:
            samples = synth.ambience(preset, synth.rng_for(seed, preset, "ambience"))
            duration = max(1, round(len(samples) / synth.RATE * fps))
            for frame in range(first, last + 1, duration):
                strip = add(samples, frame, "ambience", preset=preset)
                strip["char3d_audio_start"], strip["char3d_audio_end"] = first, last + 1
                strip["char3d_fade_in"] = strip["char3d_fade_out"] = min(.5, (last-first+1) / fps / 4)
                _key_volume(strip)
    finally:
        for obj in hidden:
            obj.hide_viewport = False
        sc.frame_end = saved_end
        sc.frame_set(saved_frame)
    return result
