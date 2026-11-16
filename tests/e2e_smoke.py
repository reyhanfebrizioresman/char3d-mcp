"""End-to-end check: real MCP client -> MCP server (stdio) -> Blender engine.

    .venv/bin/python tests/e2e_smoke.py

Set CHAR3D_ENV_VISUALS=1 to render every environment in Eevee. By default the
office and screen-image cases provide a cheaper rendering smoke check.
"""
import asyncio
import json
import os
import sys
import textwrap

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CHAR3D_PORT", "9899")  # don't collide with a running engine
# Test-only introspection: inspect the actual Blender animation curves, including
# sibling face meshes, to prove speech and blinks survive expression generation.
os.environ["CHAR3D_ALLOW_PYTHON"] = "1"
# keep the test's render-speed measurements out of the user's real calibration
CALIB = os.path.join(ROOT, "output", "e2e_render_speed.json")
os.environ["CHAR3D_RENDER_CALIB"] = CALIB
if os.path.exists(CALIB):
    os.remove(CALIB)


def _synthetic_speech(path, rate=22050):
    """Deterministic speech-like test signal: voiced vowels, a hiss and pauses."""
    import math
    import struct
    import wave
    import random
    rnd = random.Random(1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    formants = {"a": (750, 1200), "e": (500, 1900), "o": (450, 850), "i": (300, 2300)}
    plan = ["a", "e", None, "o", "s", "i", None, "a"]
    out = []
    for part in plan:
        n = int(rate * 0.35)
        if part is None:
            out += [0.0] * int(rate * 0.2)
            continue
        if part == "s":
            out += [rnd.uniform(-0.25, 0.25) for _ in range(n)]
            continue
        f1, f2 = formants[part]
        for k in range(n):
            t = k / rate
            env = math.sin(math.pi * k / n)
            src = sum(math.sin(2 * math.pi * 120 * h * t) / h for h in range(1, 30))
            out.append(0.3 * env * (0.6 * math.sin(2 * math.pi * f1 * t) + 0.4 * math.sin(2 * math.pi * f2 * t)
                                    + 0.15 * src / 3))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, x)) * 32000)) for x in out))
    return path


def text_of(res):
    return [c.text for c in res.content if c.type == "text"]


def _tone(path, seconds=0.5, rate=22050):
    """Short deterministic sound used as a repeating music/voice/sfx fixture."""
    import math
    import struct
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 220 * i / rate)))
                               for i in range(int(rate * seconds))))
    return path


WEIGHT_STATE = """
import hashlib, json
state = [(o.name, o.data.name, [[(g.group, g.weight) for g in v.groups]
          for v in o.data.vertices]) for o in bpy.context.scene.objects if o.type == 'MESH']
result = dict(weights=hashlib.sha256(json.dumps(state).encode()).hexdigest(),
              meshes=sorted(m.name for m in bpy.data.meshes),
              keys=sorted(k.name for k in bpy.data.shape_keys),
              selected=sorted(o.name for o in bpy.context.selected_objects),
              active=bpy.context.view_layer.objects.active.name
                     if bpy.context.view_layer.objects.active else None)
"""


def _check_glb_weights(path, maximum):
    """Check the actual exported skin attributes, including weight normalization."""
    import struct
    with open(path, "rb") as f:
        raw = f.read()
    json_len = struct.unpack_from("<I", raw, 12)[0]
    gltf = json.loads(raw[20:20 + json_len])
    binary = raw[28 + json_len:]
    skinned = 0
    for mesh in gltf["meshes"]:
        for primitive in mesh["primitives"]:
            attrs = primitive["attributes"]
            if "JOINTS_0" not in attrs:
                continue
            assert not any(k.startswith("JOINTS_") and k != "JOINTS_0" for k in attrs), attrs
            acc = gltf["accessors"][attrs["WEIGHTS_0"]]
            view = gltf["bufferViews"][acc["bufferView"]]
            assert acc["componentType"] == 5126 and acc["type"] == "VEC4", acc
            offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            for i in range(acc["count"]):
                weights = struct.unpack_from("<4f", binary, offset + i * view.get("byteStride", 16))
                assert sum(w > 0 for w in weights) <= maximum, weights
                assert abs(sum(weights) - 1.0) < 1e-5, weights
            skinned += 1
    assert skinned, "no exported skin attributes"
    return skinned


FACE_CURVES = '''
from engine.commands.face import _basemesh, _face_meshes
from engine.commands.talk import _fcurves
result = {}
for mesh in _face_meshes(_basemesh("Dani_rig")):
    sk = mesh.data.shape_keys
    action = sk.animation_data.action if sk.animation_data else None
    result[mesh.name] = {
        fc.data_path: [[list(k.co), k.interpolation] for k in fc.keyframe_points]
        for fc in _fcurves(action)
    }
'''


async def check_navigation(call, nav, points=(), face=None, stationary=False):
    """Measure the final animation on the visible rig, including proxy-retarget results."""
    code = textwrap.dedent(f'''\
        import math
        from engine.commands.anim import semantic_map, _facing
        from engine.commands.footlock import _legs, _sole_points
        nav = {nav!r}
        rig = bpy.data.objects[nav['armature']]
        smap = semantic_map(rig)
        sc = bpy.context.scene
        saved = sc.frame_current
        mw = rig.matrix_world
        drift, rotation_drift = 0.0, 0.0
        floor_error = 0.0
        legs, _ = _legs(rig)
        for side, intervals in nav['foot_lock']['contacts'].items():
            sole = _sole_points(rig, legs[side], 0.0)
            for a, b in intervals:
                anchor, orientation = None, None
                for f in range(a, b + 1):
                    sc.frame_set(f)
                    foot = mw @ rig.pose.bones[smap['foot.' + side]].matrix
                    p, q = foot.translation, foot.to_quaternion()
                    anchor = p.copy() if anchor is None else anchor
                    orientation = q.copy() if orientation is None else orientation
                    drift = max(drift, (p - anchor).length)
                    change = orientation.rotation_difference(q).angle
                    rotation_drift = max(rotation_drift, min(change, 2*math.pi-change))
                    floor_error = max(floor_error, abs(min((foot @ p).z for p in sole)))
        rest = (mw @ rig.data.bones[smap['hips']].matrix_local).to_quaternion()
        forward = _facing(rig, smap).inverted() @ Vector((0, -1, 0))
        sc.frame_set(nav['frames'][0] - 1)
        mat = mw @ rig.pose.bones[smap['hips']].matrix
        fw = mat.to_quaternion() @ rest.inverted() @ forward
        previous_yaw = math.atan2(fw.x, -fw.y)
        roots, yaws = [], []
        for f in range(nav['frames'][0], nav['frames'][1] + 1):
            sc.frame_set(f)
            mat = mw @ rig.pose.bones[smap['hips']].matrix
            roots.append(mat.translation.copy())
            fw = mat.to_quaternion() @ rest.inverted() @ forward
            yaws.append(math.atan2(fw.x, -fw.y))
        angle = lambda a, b: (b - a + math.pi) % (2*math.pi) - math.pi
        rate = max(abs(angle(a, b)) for a, b in zip([previous_yaw, *yaws], yaws))
        rate *= sc.render.fps / sc.render.fps_base * 180 / math.pi
        waypoint_errors, waypoint_frames = [], []
        for x, y in {list(points)!r}:
            errors = [math.hypot(p.x-x, p.y-y) for p in roots]
            waypoint_errors.append(min(errors))
            waypoint_frames.append(nav['frames'][0] + errors.index(min(errors)))
        facing_error = 0.0
        if {face!r} is not None:
            target = Vector({face!r}) - roots[-1]
            facing_error = abs(angle(yaws[-1], math.atan2(target.x, -target.y)))
        motion = max(math.hypot(p.x-roots[0].x, p.y-roots[0].y) for p in roots)
        stop = max((p - roots[-1]).length for p in roots[-4:])
        stop_feet = 0.0
        for side in 'LR':
            anchor = None
            for f in range(nav['frames'][1] - 3, nav['frames'][1] + 1):
                sc.frame_set(f)
                p = (mw @ rig.pose.bones[smap['foot.' + side]].matrix).translation
                anchor = p.copy() if anchor is None else anchor
                stop_feet = max(stop_feet, (p - anchor).length)
        sc.frame_set(saved)
        result = dict(drift=drift, rotation_drift=rotation_drift, floor_error=floor_error,
                      turn_rate=rate, waypoint_errors=waypoint_errors,
                      waypoint_frames=waypoint_frames, first=list(roots[0]), last=list(roots[-1]),
                      facing_error=facing_error, motion=motion, stop=stop, stop_feet=stop_feet)
    ''')
    measured = json.loads(text_of(await call("run_blender_python", code=code))[0])["result"]
    assert measured["drift"] < 0.02, measured
    assert measured["rotation_drift"] < 0.02, measured
    assert measured["floor_error"] < 0.02, measured
    assert measured["turn_rate"] < 100.1, measured
    assert all(e < 0.08 for e in measured["waypoint_errors"]), measured
    assert measured["facing_error"] < 0.02 and measured["stop"] < 0.001, measured
    assert measured["stop_feet"] < 0.001, measured
    assert nav["foot_lock"]["max_ik_error_m"] < 0.02, nav
    assert all(nav["foot_lock"]["contacts"].values()), nav
    if stationary:
        assert measured["motion"] < 0.005, measured
    if points:
        import math
        assert math.dist(measured["last"][:2], points[-1]) < 0.01, measured
    return measured


async def check_terrain(call, kind="basic"):
    """Check the visible rig on a full course, using an independent analytic surface."""
    import math
    await call("scene_info")
    await call("new_scene")
    mpfb = kind.startswith("mpfb")
    rotated = kind.endswith("rigify")
    angle = 27 if rotated else 0
    origin = [1.7, 0.4, 0] if rotated else [0, 0, 0]
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def point(x, y):
        return [origin[0]+c*x-s*y, origin[1]+s*x+c*y]

    if mpfb:
        await call("create_realistic_human", name="Climber", face=False,
                   rig="rigify" if rotated else "game_engine", location=origin,
                   hair="ponytail01")
        if rotated:
            await call("transform_object", name="Climber_rig", rotation_deg=[0, 0, angle])
    else:
        await call("create_human", name="Climber", height=1.75)
        await call("auto_rig_humanoid", mesh="Climber", rig_type="rigify" if rotated else "basic")
        await call("transform_object", name="Climber_rig", location=origin, rotation_deg=[0, 0, angle])
    for name, terrain, y, length, height, rotation in (
            ("Stairs", "stairs", -.6, 1.4, .85, 0),
            ("Landing", "platform", -2, .8, .85, 0),
            ("Ramp", "ramp", -5, 2.2, .85, 180)):
        await call("add_terrain", kind=terrain, name=name, location=point(0, y)+[0],
                   rotation_z=rotation+angle, length=length, height=height,
                   **({"steps": 5} if terrain == "stairs" else {}))
    visibility_code = '''
result = dict(visibility={o.name: o.hide_viewport for o in bpy.context.scene.objects},
              constraints=[(o.name, p.name, c.name, c.mute) for o in bpy.context.scene.objects
                           if o.type == 'ARMATURE' for p in o.pose.bones for c in p.constraints],
              drivers=[(o.name, fc.data_path, fc.array_index, fc.mute)
                       for o in bpy.context.scene.objects if o.type == 'ARMATURE' and o.animation_data
                       for fc in o.animation_data.drivers])
'''
    visibility = json.loads(text_of(await call("run_blender_python", code=visibility_code))[0])["result"]
    nav = json.loads(text_of(await call("walk_path", armature="Climber_rig",
                                        points=[point(0, -5.6), point(1.05, -6.3)],
                                        face_end=point(0, -6.3)))[0])
    restored = json.loads(text_of(await call("run_blender_python", code=visibility_code))[0])["result"]
    assert restored == visibility, "terrain bake must restore visibility, constraints and drivers"
    code = textwrap.dedent(f'''\
        import math
        from engine.commands.anim import semantic_map, _facing
        from engine.commands.footlock import _legs, _sole_points
        from engine.commands.terrain import GroundQuery
        rig = bpy.data.objects['Climber_rig']
        sc = bpy.context.scene
        mw = rig.matrix_world
        smap = semantic_map(rig)
        legs, _ = _legs(rig)
        soles = {{side: _sole_points(rig, leg, 0) for side, leg in legs.items()}}
        planted = {{side: {{f for a,b in nav['foot_lock']['contacts'][side] for f in range(a,b+1)}}
                   for side in 'LR'}}
        c, s = {c!r}, {s!r}
        origin = {origin!r}
        def surface(p):
            x, y = p.x-origin[0], p.y-origin[1]
            x, y = c*x+s*y, -s*x+c*y
            if abs(x) > .60001: return 0.0
            if -2 < y <= -.6: return .17*(1+min(4,int((-.6-y)/.28)))
            if -2.8 <= y <= -2: return .85
            if -5 <= y < -2.8: return .85*(y+5)/2.2
            return 0.0
        query = GroundQuery()
        ray_error = max(abs(query.sample(*p)[0]-surface(Vector((*p,0))))
                        for p in [{point(0,-.74)!r}, {point(0,-1.86)!r},
                                  {point(0,-3.9)!r}, {point(0,-5.4)!r}])
        drift = contact_error = penetration = rotation_drift = 0.0
        clearance = 10.0
        roots, yaws = [], []
        rest = (mw @ rig.data.bones[smap['hips']].matrix_local).to_quaternion()
        left = (mw @ rig.data.bones[smap['thigh.L']].head_local -
                mw @ rig.data.bones[smap['thigh.R']].head_local)
        forward = Vector((left.y,-left.x,0)).normalized()
        for side in 'LR':
            for a,b in nav['foot_lock']['contacts'][side]:
                anchor = rotation = None
                for f in range(a,b+1):
                    sc.frame_set(f)
                    foot = mw @ rig.pose.bones[smap['foot.'+side]].matrix
                    p, q = foot.translation, foot.to_quaternion()
                    anchor = p.copy() if anchor is None else anchor
                    rotation = q.copy() if rotation is None else rotation
                    drift = max(drift,(p-anchor).length)
                    change = rotation.rotation_difference(q).angle
                    rotation_drift = max(rotation_drift,min(change,2*math.pi-change))
                    contact_error = max(contact_error,max(abs((foot@v).z-surface(foot@v)) for v in soles[side]))
        for f in range(nav['frames'][0],nav['frames'][1]+1):
            sc.frame_set(f)
            hips = mw @ rig.pose.bones[smap['hips']].matrix
            roots.append(hips.translation.copy())
            fw = hips.to_quaternion() @ rest.inverted() @ forward
            yaws.append(math.atan2(fw.x,-fw.y))
            for side in 'LR':
                foot = mw @ rig.pose.bones[smap['foot.'+side]].matrix
                gaps = [(foot@v).z-surface(foot@v) for v in soles[side]]
                penetration = max(penetration,-min(gaps))
                if all(f+j not in planted[side] for j in (-2,-1,0,1,2)):
                    clearance = min(clearance,min(gaps))
        turn_rate = max(abs((b-a+math.pi)%(2*math.pi)-math.pi) for a,b in zip(yaws,yaws[1:]))
        turn_rate *= sc.render.fps/sc.render.fps_base*180/math.pi
        facing_error = abs((yaws[-1]-math.atan2(-c,s)+math.pi)%(2*math.pi)-math.pi)
        fps = sc.render.fps/sc.render.fps_base
        local = [(c*(p.x-origin[0])+s*(p.y-origin[1]),
                  -s*(p.x-origin[0])+c*(p.y-origin[1])) for p in roots]
        def speed_between(near, far):
            indices = [i for i, (x,y) in enumerate(local) if far <= y <= near]
            a, b = indices[0], indices[-1]
            return sum(math.hypot(roots[i+1].x-roots[i].x,roots[i+1].y-roots[i].y)
                       for i in range(a,b))*fps/(b-a)
        arrived = next(i for i,p in enumerate(roots)
                       if math.hypot(p.x-{point(1.05,-6.3)[0]!r},
                                     p.y-{point(1.05,-6.3)[1]!r}) < .005)
        result = dict(drift=drift, rotation_drift=rotation_drift, contact_error=contact_error,
                      penetration=penetration, clearance=clearance, ray_error=ray_error,
                      hips_jump=max(abs(a.z-b.z) for a,b in zip(roots,roots[1:])),
                      hips_rise=max(p.z for p in roots)-min(p.z for p in roots),
                      turn_rate=turn_rate, facing_error=facing_error,
                      stair_speed=speed_between(-.9,-1.8),
                      flat_speed=speed_between(-5.1,-5.5),
                      stationary_end=(len(roots)-1-arrived)/fps)
    ''')
    measured = json.loads(text_of(await call("run_blender_python",
                                             code=f"nav = {nav!r}\n"+code))[0])["result"]
    assert measured["ray_error"] < 1e-5, measured
    assert measured["contact_error"] < .015, measured
    assert measured["drift"] < .02 and measured["rotation_drift"] < .02, measured
    assert measured["penetration"] < .01 and measured["clearance"] >= .02, measured
    assert measured["hips_jump"] < .04 and measured["hips_rise"] > .7, measured
    assert measured["turn_rate"] < 100.1, measured
    assert measured["facing_error"] < .02, measured
    assert measured["flat_speed"] >= 1.0, measured
    assert .35 <= measured["stair_speed"] <= .9, measured
    assert measured["stationary_end"] <= 2.5, measured
    assert nav["frames"][1]-nav["frames"][0]+1 <= 300, nav
    assert nav["foot_lock"]["max_penetration_m"] < .01, nav
    assert nav["foot_lock"]["min_swing_clearance_m"] >= .02, nav
    assert all(nav["foot_lock"]["ground_heights"].values()), nav
    if kind == "basic":
        fingerprint = '''
import hashlib, json
from engine.commands.talk import _fcurves
rig = bpy.data.objects['Climber_rig']
curves = sorted((fc.data_path, fc.array_index,
                 [tuple(k.co) for k in fc.keyframe_points])
                for fc in _fcurves(rig.animation_data.action))
result = hashlib.sha256(json.dumps(curves).encode()).hexdigest()
'''
        first = json.loads(text_of(await call("run_blender_python", code=fingerprint))[0])["result"]
        await call("clear_animation", armature="Climber_rig")
        nav = json.loads(text_of(await call("walk_path", armature="Climber_rig",
                                            points=[point(0, -5.6), point(1.05, -6.3)],
                                            face_end=point(0, -6.3)))[0])
        second = json.loads(text_of(await call("run_blender_python", code=fingerprint))[0])["result"]
        assert first == second, "terrain keys must be deterministic"
    print(f"terrain ({kind}): contact {measured['contact_error']:.6f} m | "
          f"drift {measured['drift']:.6f} m | penetration {measured['penetration']:.6f} m | "
          f"clearance {measured['clearance']:.4f} m | hips/frame {measured['hips_jump']:.4f} m | "
          f"yaw {measured['turn_rate']:.3f} deg/s | "
          f"flat {measured['flat_speed']:.3f} m/s | stairs {measured['stair_speed']:.3f} m/s | "
          f"frames {nav['frames'][1]-nav['frames'][0]+1} | end {measured['stationary_end']:.3f} s | "
          f"bake {nav['terrain']['bake_seconds']:.3f} s")
    if kind in ("basic", "mpfb"):
        import shutil
        # Keep the stairs and full character in frame from the entrance side.
        images = await call("render_frames", frames=[80, 110], view="right", size=512)
        for frame, item in zip((80, 110), text_of(images)):
            shutil.copyfile(json.loads(item)["path"],
                            os.path.join(ROOT, "output", "renders", f"terrain_{kind}_right_f{frame:04d}.png"))
        await call("set_lighting", preset="studio", subject=["Climber_rig"])
        await call("camera_shot", name="TerrainCheck", subject=["Climber_rig"], shot="full",
                   move="tracking", angle=145, elevation=8, start_frame=80, end_frame=140)
        images = await call("render_frames", frames=[110], camera="scene", engine_name="eevee", size=512)
        shutil.copyfile(json.loads(text_of(images)[0])["path"],
                        os.path.join(ROOT, "output", "renders", f"terrain_{kind}_eevee_f0110.png"))
        await call("save_project", path=f"e2e_terrain_{kind}.blend")
        await call("export_asset", path=f"e2e_terrain_{kind}.glb")
    # Rerunning a lock on an already terrain-aware walk must retain ramp pitch/height.
    lk = json.loads(text_of(await call("lock_feet", armature="Climber_rig", terrain=True,
                                       contacts=nav["foot_lock"]["contacts"]))[0])
    assert lk["max_penetration_m"] < .01 and lk["max_ik_error_m"] < .02, lk
    if kind == "basic":
        await call("clear_animation", armature="Climber_rig")
        run = json.loads(text_of(await call("walk_path", armature="Climber_rig", clip="run",
                                            points=[point(0, -5.6), point(1.05, -6.3)],
                                            face_end=point(0, -6.3)))[0])
        running = json.loads(text_of(await call("run_blender_python",
                                               code=f"nav = {run!r}\n"+code))[0])["result"]
        assert run["terrain"]["gait"] == "run/walk", run
        assert running["flat_speed"] > measured["flat_speed"]*1.25, running
        assert .35 <= running["stair_speed"] <= .9, running
        assert running["contact_error"] < .015 and running["penetration"] < .01, running
        assert running["clearance"] >= .02 and running["hips_jump"] < .04, running
        assert running["turn_rate"] < 100.1, running
        print(f"terrain run: flat {running['flat_speed']:.3f} m/s | "
              f"stairs {running['stair_speed']:.3f} m/s | gait {run['terrain']['gait']} | "
              f"bake {run['terrain']['bake_seconds']:.3f} s")
    removed = json.loads(text_of(await call("clear_terrain"))[0])["removed"]
    assert sorted(removed) == ["Landing", "Ramp", "Stairs"], removed
    assert not json.loads(text_of(await call("clear_terrain"))[0])["removed"]


async def check_terrain_contact_detection(call):
    """Automatic local-ground detection, slope pitch, opt-out and single-step geometry."""
    await call("new_scene")
    await call("create_human", name="SlopeWalker", height=1.75)
    await call("auto_rig_humanoid", mesh="SlopeWalker")
    await call("add_terrain", kind="ramp", location=[0, .5, 0], length=2, height=.3)
    await call("animate", armature="SlopeWalker_rig", clip="idle", cycles=1, foot_lock=False)
    flat = json.loads(text_of(await call("lock_feet", armature="SlopeWalker_rig",
                                         frame_end=24, terrain=False))[0])
    assert "ground_heights" not in flat, flat
    await call("clear_animation", armature="SlopeWalker_rig")
    await call("animate", armature="SlopeWalker_rig", clip="idle", cycles=1, foot_lock=False)
    slope = json.loads(text_of(await call("lock_feet", armature="SlopeWalker_rig", frame_end=24))[0])
    assert all(v["contacts"] for v in slope["feet"].values()), slope
    assert slope["max_penetration_m"] < .01 and slope["max_ik_error_m"] < .02, slope
    code = '''
from engine.commands.footlock import _legs, _sole_points
r = bpy.data.objects['SlopeWalker_rig']; mw = r.matrix_world
legs, _ = _legs(r); error = angle = 0.0
normal = Vector((0,.15,1)).normalized()
for f in range(1,25):
    bpy.context.scene.frame_set(f)
    for leg in legs.values():
        foot = mw @ r.pose.bones[leg['foot']].matrix
        rest = mw @ r.data.bones[leg['foot']].matrix_local
        up = foot.to_quaternion() @ rest.to_quaternion().inverted() @ Vector((0,0,1))
        angle = max(angle, up.angle(normal))
        for v in _sole_points(r,leg,0):
            p = foot @ v
            error = max(error, abs(p.z - .15*(.5-p.y)))
result = dict(error=error, angle=angle)
'''
    measured = json.loads(text_of(await call("run_blender_python", code=code))[0])["result"]
    assert measured["error"] < .015 and measured["angle"] < .01, measured
    await call("clear_terrain")
    step = json.loads(text_of(await call("add_terrain", kind="step", location=[10,10,0]))[0])
    assert step["height"] == .17 and step["length"] == .28 and step["walkable"], step
    sample = json.loads(text_of(await call("run_blender_python", code="""
from engine.commands.terrain import GroundQuery
q = GroundQuery()
result = [q.sample(10,9.86)[0], q.sample(0,0)[0]]
"""))[0])["result"]
    assert abs(sample[0]-.17) < 1e-5 and sample[1] == 0, sample
    await call("clear_terrain")
    await call("clear_animation", armature="SlopeWalker_rig")
    await call("add_terrain", kind="ramp", location=[0,-.5,0], length=2, height=.3)
    await call("add_terrain", kind="platform", location=[0,-2.5,0], length=1, height=.3)
    stop = json.loads(text_of(await call("walk_path", armature="SlopeWalker_rig",
                                         points=[[0,-3]], clip="run"))[0])
    assert stop["clip"] == "run" and stop["terrain"]["gait"].startswith("run"), stop
    code = f'''
r = bpy.data.objects['SlopeWalker_rig']; heights = []
for f in range({stop['frames'][1]}-5, {stop['frames'][1]}+1):
    bpy.context.scene.frame_set(f)
    heights.append((r.matrix_world @ r.pose.bones['hips'].matrix).translation.z)
rest = (r.matrix_world @ r.data.bones['hips'].matrix_local).translation.z
result = [min(heights)-rest, max(heights)-min(heights)]
'''
    height, motion = json.loads(text_of(await call("run_blender_python", code=code))[0])["result"]
    assert height > .25 and motion < .001, (height, motion)
    await call("clear_terrain")
    print(f"terrain lock: automatic contacts, terrain=False, ramp pitch {measured['angle']:.6f} rad | "
          f"sole error {measured['error']:.6f} m | single step + elevated stop + ramp running OK")


async def isolate_mpfb(session):
    """Keep MPFB's logs, caches and writable asset data inside this test workspace.

    MPFB otherwise opens logs in Blender's portable install, which can be read-only in
    a worktree sandbox. Configure its supported user-data preference before enabling it.
    """
    code = textwrap.dedent(f'''\
        import addon_utils
        import importlib
        import os
        import shutil
        module = 'bl_ext.user_default.mpfb'
        if any(m.__name__ == module for m in addon_utils.modules()):
            source = os.path.join(bpy.utils.extension_path_user(module), 'data')
            home = {os.path.join(ROOT, 'output', 'mpfb_test')!r}
            os.makedirs(home, exist_ok=True)
            data = os.path.join(home, 'data')
            if os.path.isdir(source) and not os.path.isdir(data):
                shutil.copytree(source, data)
            cls = importlib.import_module(module + '._preferences').MpfbPreferences
            if 'bl_rna' not in cls.__dict__:
                bpy.utils.register_class(cls)
            addon = bpy.context.preferences.addons.get(module)
            if addon is None:
                addon = bpy.context.preferences.addons.new()
                addon.module = module
            addon.preferences.mpfb_user_data = home
    ''')
    res = await session.call_tool("run_blender_python", {"code": code})
    assert not res.isError, text_of(res)


async def _sitting_checks(call):
    """Seat contacts, facing, planted holds, layered gestures and exported palm attachments."""
    import struct
    import math
    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])
    def exported_tilt(path, prop, start_frame=1):
        """Sample actual glTF quaternion outputs, in its +Y-up coordinate system."""
        with open(path, 'rb') as stream:
            raw = stream.read()
        length = struct.unpack_from('<I', raw, 12)[0]
        gltf = json.loads(raw[20:20+length])
        node = next(i for i,n in enumerate(gltf['nodes']) if n.get('name') == prop)
        def values(index):
            a = gltf['accessors'][index]
            view = gltf['bufferViews'][a['bufferView']]
            width = {'SCALAR':1, 'VEC4':4}[a['type']]
            assert a['componentType'] == 5126
            offset = 28+length+view.get('byteOffset',0)+a.get('byteOffset',0)
            stride = view.get('byteStride',width*4)
            return [struct.unpack_from('<'+'f'*width,raw,offset+i*stride) for i in range(a['count'])]
        tilts = []
        for animation in gltf['animations']:
            for channel in animation['channels']:
                if channel['target'] == {'node':node, 'path':'rotation'}:
                    sampler = animation['samplers'][channel['sampler']]
                    for t,q in zip(values(sampler['input']),values(sampler['output'])):
                        if t[0] >= start_frame/24-1e-5:
                            tilts.append(math.degrees(math.acos(max(-1,min(1,1-2*(q[0]**2+q[2]**2))))))
        assert tilts, 'cup rotation animation missing'
        assert max(tilts) <= 15, tilts
        return max(tilts)
    measure = '''
import math
from mathutils import Vector
from engine.commands.anim import semantic_map
r = bpy.data.objects['SeatTester_rig']
s = semantic_map(r)
mw = r.matrix_world
front = Vector(FRONT)
center = Vector(CENTER)
floor = FLOOR
rest_left = mw @ r.data.bones[s['thigh.L']].head_local - mw @ r.data.bones[s['thigh.R']].head_local
rest_front = Vector((rest_left.y, -rest_left.x, 0)).normalized()
root_rest = mw @ r.data.bones[s['hips']].matrix_local
soles = {}
for side in 'LR':
    foot = r.data.bones[s['foot.'+side]]
    toe = r.data.bones[s['toe.'+side]]
    inv = (mw @ foot.matrix_local).inverted()
    points = [mw @ foot.head_local, mw @ toe.head_local, mw @ toe.tail_local]
    soles[side] = [inv @ Vector((p.x, p.y, mw.translation.z)) for p in points]
result = []
for f in FRAMES:
    bpy.context.scene.frame_set(f)
    bpy.context.view_layer.update()
    hip = mw @ r.pose.bones[s['hips']].matrix
    direction = hip.to_quaternion() @ root_rest.to_quaternion().inverted() @ rest_front
    direction.z = 0
    feet = {side: mw @ r.pose.bones[s['foot.'+side]].matrix for side in 'LR'}
    # Independent evaluated-surface probe behind the hip, excluding forward knees.
    import numpy as np
    lows=[]
    left=Vector((-front.y,front.x,0))
    pelvis=sum(((mw@r.pose.bones[s['thigh.'+side]].matrix).translation for side in 'LR'),Vector())/2
    for obj in r.children_recursive:
        if obj.type!='MESH' or obj.hide_render or obj.get('c3d_role')=='environment':
            continue
        ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh=ev.to_mesh()
        co=np.empty(len(mesh.vertices)*3)
        mesh.vertices.foreach_get('co',co)
        mat=np.asarray(ev.matrix_world)
        pts=co.reshape(-1,3)@mat[:3,:3].T+mat[:3,3]
        d=pts-np.asarray(pelvis)
        use=(abs(d@np.asarray(left))<0.22)&(d@np.asarray(front)<0.045)&(d@np.asarray(front)>-0.18)&(d[:,2]>-0.23)&(d[:,2]<0.10)
        if use.any(): lows.append(float(pts[use,2].min()))
        ev.to_mesh_clear()
    slopes=[]
    for side in 'LR':
        v=(mw@r.pose.bones[s['shin.'+side]].matrix).translation-(mw@r.pose.bones[s['thigh.'+side]].matrix).translation
        slopes.append(abs(math.degrees(math.atan2(v.z,math.hypot(v.x,v.y)))))
    result.append(dict(hip=list(hip.translation), angle=math.degrees(direction.angle(front)),
        thigh_slope=max(slopes), standing_rest_z=root_rest.translation.z+floor-mw.translation.z,
        feet={side:list(m.translation) for side,m in feet.items()}, buttock=min(lows),
        sole=[(feet[side] @ p).z-floor for side in 'LR' for p in soles[side]]))
'''
    max_contact = max_sole = max_drift = max_angle = max_palm = max_thigh = max_tilt = 0.0
    timings = []
    for kind in ('basic', 'rigify', 'game_engine', 'mpfb_rigify'):
        await call('new_scene', frame_end=65)
        if kind in ('basic', 'rigify'):
            await call('create_human', name='SeatTester', location=[-0.4, 0.2, 0])
            await call('auto_rig_humanoid', mesh='SeatTester', rig_type=kind)
        else:
            await call('create_realistic_human', name='SeatTester', rig='rigify' if kind=='mpfb_rigify' else kind,
                       face=False, hair='short01', clothes=['male_casualsuit01'])
        await call('transform_object', name='SeatTester_rig', location=[-0.4, 0.2, 0], rotation_deg=[0, 0, 23])
        await call('apply_pose', armature='SeatTester_rig', pose='relaxed')
        for seat_kind, index, rotation in (('chair', 0, 30), ('sofa', 1, -47)):
            await call('clear_animation', armature='SeatTester_rig')
            await call('set_timeline', frame_end=65)
            prop = await data('add_prop', kind=seat_kind, location=[0.4, 0.5, 0], rotation_z=rotation)
            # Resolve by a non-seat furniture part as well as by root.
            name = prop['objects'][-1] if seat_kind=='chair' else prop['root']
            sit = await data('sit_on', character='SeatTester_rig', seat=name, seat_index=index, start_frame=1)
            assert abs(sit['contact_error_m']) < 0.02, sit
            timings.append(sit['bake_seconds'])
            max_contact = max(max_contact, abs(sit['contact_error_m']))
            angle = math.radians(rotation)
            front = [math.sin(angle), -math.cos(angle), 0]
            center = [0.4, 0.5, sit['seat_surface_z']]
            code = measure.replace('FRONT', repr(front)).replace('CENTER', repr(center)).replace('FLOOR', repr(sit['floor'])).replace('FRAMES', '[21, 35, 55]')
            samples = (await data('run_blender_python', code=code))['result']
            for row in samples:
                assert abs(row['buttock']-sit['seat_surface_z']) < 0.02, (kind,seat_kind,row)
                max_thigh=max(max_thigh,row['thigh_slope'])
                assert row['thigh_slope'] < 45, (kind,seat_kind,row)
                max_angle = max(max_angle, row['angle'])
                assert row['angle'] < 10, (kind, seat_kind, row)
                max_sole = max(max_sole, max(abs(z) for z in row['sole']))
                assert max(abs(z) for z in row['sole']) < 0.015, (kind, seat_kind, row)
                for side in 'LR':
                    drift = math.dist(row['feet'][side], samples[0]['feet'][side])
                    max_drift = max(max_drift, drift)
                    assert drift < 0.001, row
            await call('talk_gestures', character='SeatTester_rig', frame_start=25, frame_end=55,
                       cues=[{'frame':40, 'gesture':'good'}])
            after = (await data('run_blender_python', code=code))['result']
            assert all(math.dist(a['hip'], b['hip']) < 1e-5 for a,b in zip(samples,after)), after
            if seat_kind=='sofa':
                cup = await data('add_prop', kind='cup')
                await call('hold_prop', character='SeatTester_rig', prop=cup['objects'][-1], start_frame=25)
                # Animate AFTER attachment, to prove it is live rather than an early bake.
                await call('talk_gestures', character='SeatTester_rig', frame_start=25, frame_end=55,
                           hands='right', cues=[{'frame':40, 'gesture':'up'}])
                held_code = f'''
import math
from mathutils import Vector
from engine.commands.anim import semantic_map
r = bpy.data.objects['SeatTester_rig']
o = bpy.data.objects[{cup['root']!r}]
b = semantic_map(r)['hand.R']
from engine.commands.fingers import HandRig
finger_names=[n for chain in HandRig(r).fingers.get('R',{{}}).values() for n in chain]
import json
p = Vector(json.loads(o['c3d_hold_palm']))
result = []
for f in range(25, 46):
    bpy.context.scene.frame_set(f)
    bpy.context.view_layer.update()
    result.append(dict(distance=(o.matrix_world.translation-(r.matrix_world@r.pose.bones[b].matrix@p)).length,
                       tilt=math.degrees((o.matrix_world.to_3x3()@Vector((0,0,1))).angle(Vector((0,0,1)))),
                       position=list(o.matrix_world.translation),
                       fingers=[x for n in finger_names for row in
                                (r.pose.bones[n].parent.matrix.inverted()@r.pose.bones[n].matrix) for x in row]))
'''
                held = (await data('run_blender_python', code=held_code))['result']
                max_palm = max(max_palm, max(x['distance'] for x in held))
                assert max(x['distance'] for x in held) < 0.03, held
                max_tilt = max(max_tilt, max(x['tilt'] for x in held))
                assert max(x['tilt'] for x in held) <= 15, (kind, held)
                assert all(max((abs(a-b) for a,b in zip(x['fingers'],held[0]['fingers'])), default=0)<1e-4
                           for x in held), (kind, held)
                assert max(math.dist(x['position'],held[0]['position']) for x in held) > 0.01, held
                await call('release_prop', character='SeatTester_rig', prop=cup['root'], frame=56)
                released = (await data('run_blender_python', code=held_code.replace('range(25, 46)', 'range(56, 66)')))['result']
                assert max(math.dist(x['position'],released[0]['position']) for x in released) < 1e-5, released
                if kind == 'game_engine':
                    exported = await data('export_asset', path='e2e_held_cup.glb', objects=['SeatTester_rig'])
                    max_tilt = max(max_tilt, exported_tilt(exported['path'], cup['root'], 25))
                    with open(exported['path'],'rb') as f:
                        raw=f.read()
                    length=struct.unpack_from('<I',raw,12)[0]
                    gltf=json.loads(raw[20:20+length])
                    node=next(i for i,n in enumerate(gltf['nodes']) if n.get('name')==cup['root'])
                    channels=[c for a in gltf['animations'] for c in a['channels'] if c['target']['node']==node]
                    assert any(c['target']['path']=='translation' for c in channels), channels
                    binary_offset=20+length+8
                    def accessor(index):
                        a=gltf['accessors'][index]
                        view=gltf['bufferViews'][a['bufferView']]
                        width={'SCALAR':1,'VEC3':3,'VEC4':4}[a['type']]
                        assert a['componentType']==5126
                        offset=binary_offset+view.get('byteOffset',0)+a.get('byteOffset',0)
                        stride=view.get('byteStride',width*4)
                        return [struct.unpack_from('<'+'f'*width,raw,offset+i*stride) for i in range(a['count'])]
                    for animation in gltf['animations']:
                        for channel in animation['channels']:
                            if channel['target']=={'node':node,'path':'translation'}:
                                sampler=animation['samplers'][channel['sampler']]
                                times=accessor(sampler['input'])
                                values=accessor(sampler['output'])
                                tail=[v for t,v in zip(times,values) if t[0]>=56/24]
                                assert len(tail)>1 and max(math.dist(v,tail[0]) for v in tail)<1e-5, tail
                                assert max(math.dist(v,values[0]) for v in values)>0.01
            stand = await data('stand_up', character='SeatTester_rig')
            assert stand['frames'][0] == 66, stand
            standing_code=code.replace('[21, 35, 55]', '[86]')
            standing = (await data('run_blender_python', code=standing_code))['result'][0]
            assert abs(standing['hip'][2]-standing['standing_rest_z']) < 0.02, standing
            assert max(abs(z) for z in standing['sole']) < 0.015, standing
            # Restore scene length for the next independent seat case.
            await call('set_timeline', frame_end=65)
        if kind=='basic':
            await data('add_primitive',kind='cube',name='SeatMesh',location=[0,0,0.23],size=1)
            await call('transform_object',name='SeatMesh',scale=[0.6,0.5,0.46])
            bench=await data('add_prop',kind='bench',location=[2,0,0])
            stool=await data('add_prop',kind='stool',location=[-2,0,0])
            for seat_name,index,hands in (('SeatMesh',0,'lap'),(bench['root'],1,'none'),(stool['root'],0,'thighs'),(prop['root'],1,'armrests')):
                await call('clear_animation',armature='SeatTester_rig')
                await call('set_timeline',frame_end=12)
                extra=await data('sit_on',character='SeatTester_rig',seat=seat_name,seat_index=index,hands=hands,start_frame=1,transition_frames=3)
                assert abs(extra['contact_error_m'])<0.02,extra
        print('sitting rig:', kind, 'chair + sofa[1], stand, layered gestures, live cup/release OK')
    # Other handheld kinds, bounded hold and explicit placement.
    for kind in ('phone', 'book', 'handheld_microphone', 'bench', 'stool'):
        prop = await data('add_prop', kind=kind)
        assert prop['objects'], prop
    phone = await data('add_prop', kind='phone')
    phone_hold = await data('hold_prop', character='SeatTester_rig', prop=phone['root'], hand='left', start_frame=25, end_frame=40)
    assert phone_hold['upright'] is False, phone_hold
    placed = await data('release_prop', character='SeatTester_rig', prop=phone['root'], frame=41, place_at=[1, 2, 0.8])
    assert placed['location']==[1, 2, 0.8], placed
    for args in ({'seat_index':99}, {'hands':'armrests'}, {'transition_frames':0}):
        try:
            await call('sit_on', character='SeatTester_rig', seat=prop['root'], **args)
        except RuntimeError:
            pass
        else:
            raise AssertionError(('invalid sit accepted',args))
    # Original demo order: attach first, then walk, sit with hands on thighs, gesture.
    await call('new_scene', frame_end=110)
    await call('create_realistic_human', name='SeatTester', rig='game_engine', face=False)
    await call('apply_pose', armature='SeatTester_rig', pose='relaxed')
    cup = await data('add_prop', kind='cup')
    attached = await data('hold_prop', character='SeatTester_rig', prop=cup['root'], start_frame=1)
    assert attached['upright'] is True, attached
    await call('walk_path', armature='SeatTester_rig', points=[[0,-0.45]], start_frame=1)
    chair = await data('add_prop', kind='chair', location=[0,-0.45,0])
    await call('sit_on', character='SeatTester_rig', seat=chair['root'], start_frame=65, hands='thighs')
    await call('talk_gestures', character='SeatTester_rig', frame_start=86, frame_end=110,
               hands='right', cues=[{'frame':98, 'gesture':'up'}])
    all_frames = held_code.replace('range(25, 46)', 'range(1, 111)')
    samples = (await data('run_blender_python', code=all_frames))['result']
    assert max(x['tilt'] for x in samples) <= 15, samples
    assert max(x['distance'] for x in samples) < 0.03, samples
    assert all(max(abs(a-b) for a,b in zip(x['fingers'],samples[0]['fingers']))<1e-4 for x in samples), samples
    max_tilt = max(max_tilt, max(x['tilt'] for x in samples))
    max_palm = max(max_palm, max(x['distance'] for x in samples))
    exported = await data('export_asset', path='e2e_upright_walk_sit.glb', objects=['SeatTester_rig'])
    max_export_tilt = exported_tilt(exported['path'], cup['root'])
    restored = (await data('run_blender_python', code=all_frames))['result']
    assert max(math.dist(a['position'],b['position']) for a,b in zip(samples,restored)) < 1e-5
    # Explicit opt-out keeps the original rigid palm frame; the microphone opts in.
    await call('release_prop', character='SeatTester_rig', prop=cup['root'], frame=111)
    rigid = await data('add_prop', kind='cup')
    rigid_hold = await data('hold_prop', character='SeatTester_rig', prop=rigid['root'], start_frame=111, upright=False)
    assert rigid_hold['upright'] is False, rigid_hold
    rigid_sample = (await data('run_blender_python', code=all_frames.replace(repr(cup['root']),repr(rigid['root']))
                               .replace('range(1, 111)', 'range(111, 112)')))['result'][0]
    assert rigid_sample['tilt'] > 15 and rigid_sample['distance'] < 0.03, rigid_sample
    mic = await data('add_prop', kind='handheld_microphone')
    mic_hold = await data('hold_prop', character='SeatTester_rig', prop=mic['root'], hand='left', start_frame=1)
    assert mic_hold['upright'] is True, mic_hold
    mic_samples = (await data('run_blender_python', code=all_frames.replace(repr(cup['root']),repr(mic['root']))
                              .replace("['hand.R']", "['hand.L']").replace("get('R',", "get('L',")))['result']
    assert max(x['tilt'] for x in mic_samples) <= 15, mic_samples
    await call('clear_environment')
    cleaned = (await data('run_blender_python', code="""
r=bpy.data.objects['SeatTester_rig']
result=[c.name for pb in r.pose.bones for c in pb.constraints if c.name.startswith('char3d_grip:')]
"""))['result']
    assert not cleaned, cleaned
    print(f'upright cup: 110 walk/sit/gesture frames tilt={max_tilt:.4f}deg palm={max_palm:.6f}m '
          f'glb tilt={max_export_tilt:.4f}deg; live finger grip, release, opt-out, mic OK')
    print(f'sitting/holding: contact={max_contact:.5f}m sole={max_sole:.5f}m drift={max_drift:.6f}m '
          f'facing={max_angle:.3f}deg thigh={max_thigh:.2f}deg palm={max_palm:.6f}m bake={min(timings):.3f}..{max(timings):.3f}s; glb OK')


async def _graphics_checks(call):
    """Decode real draft movies to check graphics timing, mixing and exact frame counts."""
    import av
    import numpy as np

    def frames(path):
        with av.open(path) as movie:
            return [f.to_ndarray(format="rgb24") for f in movie.decode(video=0)]

    def save_png(path, pixels):
        with av.open(path, "w", format="image2") as image:
            stream = image.add_stream("png", rate=1)
            stream.width, stream.height = pixels.shape[1], pixels.shape[0]
            stream.pix_fmt = "rgb24"
            for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                image.mux(packet)
            for packet in stream.encode():
                image.mux(packet)

    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[0])

    async def video(path, start=1, end=48, **args):
        v = await data("render_video", path=path, quality="draft", width=640, height=360,
                       frame_start=start, frame_end=end, wait=True, **args)
        assert v["status"] == "done" and "warning" not in v, v
        decoded = frames(v["path"])
        assert len(decoded) == end - start + 1, (v, len(decoded))
        return v, decoded

    await call("new_scene", frame_end=48)
    await call("add_primitive", kind="monkey", name="Blue", location=[-2, 0, 1])
    await call("add_primitive", kind="cube", name="Orange", location=[2, 0, 1])
    await call("set_material", objects=["Blue"], color=[0.03, 0.2, 0.9])
    await call("set_material", objects=["Orange"], color=[0.95, 0.18, 0.02])
    await call("set_lighting", preset="studio", ground=False)
    await call("camera_shot", subject=["Blue"], shot="full", angle=0,
               start_frame=1, end_frame=24, name="BlueShot")
    await call("camera_shot", subject=["Orange"], shot="full", angle=30,
               start_frame=25, end_frame=48, name="OrangeShot")
    _, plain = await video("e2e_graphics_plain.mp4")
    await call("add_transition", kind="fade_in", duration_s=0.25, name="intro")
    await call("add_transition", shot="OrangeShot", duration_s=0.5, name="cut")
    await call("add_transition", kind="fade_out", duration_s=0.25, name="outro")
    await call("add_title", text="Ana Putri", subtitle="Character artist", style="lower_third",
               start_s=0.25, duration_s=1.5, name="speaker")
    for args in ({"at_frame": 26}, {"shot": "BlueShot"},
                 {"at_frame": 25, "shot": "OrangeShot"},
                 {"at_frame": 25, "kind": "fade_black"}, {"duration_s": -1}):
        try:
            await call("add_transition", **args)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"invalid transition accepted: {args}")
    assert len((await data("list_graphics"))["graphics"]) == 4
    project = await data("save_project", path="e2e_graphics.blend")
    await call("remove_graphics", all=True)
    await call("open_project", path=project["path"])
    assert len((await data("list_graphics"))["graphics"]) == 4
    assert (await data("render_options", quality="draft"))["handle_frames"] == 12
    preview = await data("render_frames", frames=[17], camera="scene", size=320)
    assert preview["titles"] is True, preview
    title_image = frames(preview["path"])[0]
    bare = await data("render_frames", frames=[17], camera="scene", size=320, graphics=False)
    bare_image = frames(bare["path"])[0]
    assert np.abs(title_image.astype(float) - bare_image).mean() > 1
    # Captions, title and transitions must all survive the same composition pass.
    await call("add_subtitles", style="classic", position="top",
               lines=[{"text": "Graphics on the timeline", "start": 0.4, "end": 1.7}])
    v, mixed = await video("e2e_graphics.mp4")
    assert v["graphics"] == {"titles": 1, "transitions": 3, "handle_frames": 12}, v
    assert v["subtitles"]["captions"] == 1, v
    assert mixed[0].mean() < 3 and mixed[-1].mean() < 3, (mixed[0].mean(), mixed[-1].mean())
    assert mixed[7].mean() > 15
    roi = np.s_[65:110, 100:220, :]
    diff = lambda a, b: np.abs(a[roi].astype(float) - b[roi]).mean()
    # Full outgoing camera at the cut, both pictures halfway, incoming at the end.
    assert diff(mixed[24], plain[23]) < 6, diff(mixed[24], plain[23])
    assert diff(mixed[29], plain[29]) > 8 and diff(mixed[29], plain[23]) > 8
    assert diff(mixed[35], plain[35]) < 6, diff(mixed[35], plain[35])
    tag_roi = np.s_[125:165, 15:95, :]
    tag_diff = lambda i: np.abs(mixed[i][tag_roi].astype(float) - plain[i][tag_roi]).mean()
    assert tag_diff(6) < 4 and tag_diff(13) > 5 and tag_diff(41) < 4
    for frame in (1, 17, 25, 30, 36, 48):
        save_png(os.path.join(ROOT, "output", "renders", f"e2e_graphics_f{frame:04d}.png"), mixed[frame - 1])
    _, cropped = await video("e2e_graphics_crop.mp4", start=29, end=38)
    assert diff(cropped[0], mixed[28]) < 6, diff(cropped[0], mixed[28])
    await call("remove_subtitles")
    await call("remove_graphics", name="speaker")
    # Color dips and their alias, plus non-1 scene starts, must use local movie frames.
    await call("set_timeline", frame_start=5)
    for kind in ("fade_black", "fade_white", "dip_black"):
        await call("remove_graphics", all=True)
        await call("add_transition", at_frame=25, kind=kind, duration_s=0.5, name="dip")
        _, dipped = await video(f"e2e_{kind}.mp4", start=19, end=30, subtitles=False)
        mean = dipped[6].mean()  # scene frame 25: exact color at the cut
        assert mean > 250 if kind == "fade_white" else mean < 3, (kind, mean)
    await call("remove_graphics", name="all")
    await call("add_transition", kind="fade_in", duration_s=0.25)
    _, fade_only = await video("e2e_fade_only.mp4", start=5, end=10)
    assert fade_only[0].mean() < 3 and fade_only[-1].mean() > 15
    await call("remove_graphics", all=True)
    for style in ("center", "corner"):
        await call("add_title", text="A new chapter", subtitle="Video graphics", style=style,
                   name="card", animation="fade" if style == "center" else "none",
                   start_s=0, duration_s=1)
        result = await data("render_frames", frames=[17], camera="scene", size=320)
        assert result["titles"] is True
    # Title-only composition, with captions disabled, no transition trigger to hide bugs.
    assert len((await data("list_graphics"))["graphics"]) == 1
    _, titled = await video("e2e_title_only.mp4", start=17, end=18, subtitles=False)
    assert np.abs(titled[0].astype(float) - plain[16]).mean() > 1
    assert (await data("remove_graphics", all=True))["graphics"] == []
    print("graphics: 48/48 frames | fade in/out black | crossfade 12 handles | lower third + captions | crop + color dips + title-only OK")


async def _secondary_motion_checks(call):
    """Measure evaluated skin/bones, untouched body curves, and exported animation."""
    import struct

    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[0])

    async def inspect(code):
        return (await data('run_blender_python', code=code))['result']

    await call('new_scene', frame_end=100)
    await call('create_realistic_human', name='Spring', gender=0.0, hair='ponytail01',
               clothes=['female_sportsuit01'], location=[1.2, .3, 0], face=False)
    await call('transform_object', name='Spring_rig', rotation_deg=[0, 0, 32])
    snapshot = '''
import hashlib, json
from engine.commands.talk import _fcurves
r = bpy.data.objects['Spring_rig']
def curves(hair):
    act = r.animation_data.action if r.animation_data else None
    return [(fc.data_path, fc.array_index, [(list(k.co), k.interpolation) for k in fc.keyframe_points])
            for fc in _fcurves(act) if ('hair_' in fc.data_path) == hair]
def digest(hair):
    return hashlib.sha256(json.dumps(curves(hair)).encode()).hexdigest()
'''
    await inspect(snapshot + '''
o = bpy.data.objects['Spring.ponytail01']
dg = bpy.context.evaluated_depsgraph_get()
bpy.app.driver_namespace['secondary_rest'] = [v.co.copy() for v in o.evaluated_get(dg).data.vertices]
result = len(o.data.vertices)
''')
    rest = await data('secondary_motion', character='Spring', gravity=0, frame_end=1)
    assert rest['chains'] == 1 and len(rest['bones']) == 4, rest
    error = await inspect('''
o = bpy.data.objects['Spring.ponytail01']
after = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
result = max((v.co-p).length for v,p in zip(after.data.vertices, bpy.app.driver_namespace['secondary_rest']))
''')
    assert error < .001, error
    await call('render_frames', frames=[1], objects=['Spring_rig'], view='right', size=512)
    await call('animate', armature='Spring_rig', clip='run', cycles=3)
    body = await inspect(snapshot + 'result = digest(False)')
    baked = await data('secondary_motion', character='Spring_rig')
    measured = await inspect(snapshot + '''
from engine.commands.secondary import _closest
st = json.loads(r['char3d_secondary'])
saved = bpy.context.scene.frame_current
offsets, clearance = [], 1.0
for f in range(1,101):
    bpy.context.scene.frame_set(f)
    ch = st['chains'][0]
    transform = r.matrix_world @ r.pose.bones[ch['parent']].matrix @ r.data.bones[ch['parent']].matrix_local.inverted()
    tail = r.matrix_world @ r.pose.bones[ch['bones'][-1]].tail
    offsets.append((tail - transform @ Vector(ch['points'][-1])).length)
    for name in ch['bones']:
        a = r.matrix_world @ r.pose.bones[name].head
        b = r.matrix_world @ r.pose.bones[name].tail
        for c in st['colliders']:
            mat = r.matrix_world @ r.pose.bones[c['bone']].matrix @ r.data.bones[c['bone']].matrix_local.inverted()
            ca, cb = mat @ Vector(c['a']), mat @ Vector(c['b'])
            for u in (.25,.5,.75,1):
                p = a.lerp(b,u)
                clearance = min(clearance, (p - _closest(p,ca,cb)).length - c['radius'] - ch['radius'])
bpy.context.scene.frame_set(saved)
result = dict(peak=max(offsets), running=max(offsets[6:48]), settled=offsets[77],
              clearance=clearance, hair=digest(True), body=digest(False),
              bones=len(r.data.bones), groups=len(bpy.data.objects['Spring.ponytail01'].vertex_groups))
''')
    assert measured['running'] > .03, measured
    assert measured['settled'] < .015 and measured['clearance'] > -.001, measured
    assert measured['body'] == body, measured
    # Target, not a flaky wall-clock assertion on a shared CPU: report measured timing.
    await call('secondary_motion', character='Spring_rig')
    again = await inspect(snapshot + "result = dict(hair=digest(True), body=digest(False), bones=len(r.data.bones), groups=len(bpy.data.objects['Spring.ponytail01'].vertex_groups))")
    assert all(again[k] == measured[k] for k in again), (measured, again)
    exported = await data('export_asset', path='hair.glb', objects=['Spring_rig'], max_influences=4)
    raw = open(exported['path'], 'rb').read()
    gltf = json.loads(raw[20:20 + struct.unpack_from('<I', raw, 12)[0]])
    joints = {gltf['nodes'][i]['name'] for skin in gltf['skins'] for i in skin['joints']}
    animated = {gltf['nodes'][c['target']['node']]['name'] for a in gltf['animations']
                for c in a['channels'] if c['target']['path'] == 'rotation'}
    assert set(baked['bones']) <= joints & animated, (joints, animated)
    _check_glb_weights(exported['path'], 4)
    await call('render_frames', frames=[2, 8, 25, 78], objects=['Spring_rig'], view='right', size=512)
    await call('save_project', path='e2e_secondary.blend')
    # Inclusive partial replacement leaves every key outside its range untouched.
    outside_code = snapshot + "result = [(p,i,[k for k in ks if not 30 <= k[0][0] <= 40]) for p,i,ks in curves(True)]"
    outside = await inspect(outside_code)
    await call('secondary_motion', character='Spring_rig', frame_start=30, frame_end=40, wind=[2, 0, 0])
    assert await inspect(outside_code) == outside
    await call('secondary_motion', character='Spring_rig', frame_start=30, frame_end=40, clear=True)
    assert await inspect(outside_code) == outside
    neutral = await inspect(snapshot + '''
bpy.context.scene.frame_set(35)
result = max(r.pose.bones[n].rotation_quaternion.rotation_difference(Quaternion()).angle
             for ch in json.loads(r['char3d_secondary'])['chains'] for n in ch['bones'])
'''.replace('Quaternion()', '__import__("mathutils").Quaternion()'))
    assert neutral < .0001, neutral
    await call('secondary_motion', character='Spring_rig', clear=True)
    assert await inspect(snapshot + 'result = sum(len(k) for p,i,k in curves(True))') == 0
    assert await inspect(snapshot + 'result = digest(False)') == body
    print(f"secondary ponytail: rest {error * 1000:.6f} mm | running lag {measured['running']:.6f} m | "
          f"settled +1s {measured['settled']:.6f} m | clearance {measured['clearance']:.6f} m | "
          f"100f {baked['bake_seconds']:.4f}s | deterministic/range/clear/body/glb OK")

    # MPFB Rigify: actual deform head attachment, hidden collection, talking/nodding.
    await call('new_scene', frame_end=80)
    await call('create_realistic_human', name='LongSpring', gender=0.0, rig='rigify', hair='long01')
    await call('animate', armature='LongSpring_rig', clip='nod', cycles=2)
    await call('lip_sync', character='LongSpring_rig', text='Mari kita berbicara bersama', language='id')
    await call('camera_shot', subject=['LongSpring_rig'], shot='medium', end_frame=80)
    await call('auto_blink', character='LongSpring_rig')
    await call('talk_motion', character='LongSpring_rig')
    long = await data('secondary_motion', character='LongSpring_rig')
    assert 3 <= long['chains'] <= 6 and long['max_tip_offset_m'] > .01, long
    assert await inspect('''
r = bpy.data.objects['LongSpring_rig']
import json
st = json.loads(r['char3d_secondary'])
result = (not r.data.collections['Secondary motion'].is_visible and
          all(r.data.bones[c['parent']].use_deform for c in st['chains']) and
          all([bc.name for bc in r.data.bones[n].collections] == ['Secondary motion']
              for c in st['chains'] for n in c['bones']))
''')
    await call('render_frames', frames=[12, 45], objects=['LongSpring_rig'], view='right', size=512)
    await call('export_asset', path='hair_rigify.glb', objects=['LongSpring_rig'], max_influences=4)
    await call('create_realistic_human', name='ShortSpring', hair='short02', face=False)
    short = await data('secondary_motion', character='ShortSpring_rig', parts=['hair', 'clothes'])
    assert not short['bones'] and len(short['skipped']) == 2, short
    print(f"secondary long/Rigify: {long['chains']} chains | tip {long['max_tip_offset_m']:.6f} m | "
          f"80f {long['bake_seconds']:.4f}s | hidden deform chains + export | short02/clothes skipped")

    # Name-hinted user hair on both mannequin rigs, with moved/rotated armatures.
    for kind in ('basic', 'rigify'):
        await call('new_scene', frame_end=40)
        await call('create_human', name='HairUser', style='realistic')
        await call('auto_rig_humanoid', mesh='HairUser', rig_type=kind)
        await call('transform_object', name='HairUser_rig', location=[1, -2, 0], rotation_deg=[0, 0, 47])
        await inspect('''
from engine.commands.anim import semantic_map
from engine.commands.secondary import _deform_head
r = bpy.data.objects['HairUser_rig']
parent = _deform_head(r, semantic_map(r))
p = r.data.bones[parent].head_local
verts = [(p.x+x, p.y+.13, p.z+.02-i*.07) for i in range(6) for x in (-.025, 0, .025)]
faces = [(i*3+j,i*3+j+1,(i+1)*3+j+1,(i+1)*3+j) for i in range(5) for j in range(2)]
mesh = bpy.data.meshes.new('UserHair')
mesh.from_pydata(verts, [], faces)
o = bpy.data.objects.new('UserHair', mesh)
bpy.context.scene.collection.objects.link(o)
o.parent = r
o.vertex_groups.new(name=parent).add(list(range(len(verts))), 1., 'REPLACE')
o.modifiers.new('Skin', 'ARMATURE').object = r
result = o.name
''')
        await call('animate', armature='HairUser_rig', clip='nod', cycles=1)
        custom = await data('secondary_motion', character='HairUser_rig')
        assert custom['bones'] and custom['max_tip_offset_m'] > .005, custom
        assert custom['meshes'] == ['UserHair'], custom
        print(f"secondary user hair ({kind}): {custom['chains']} chains | moved/rotated rig OK")


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        assert "char3d" in (init.instructions or ""), "server instructions missing"
        tools = {t.name for t in (await s.list_tools()).tools}
        print("tools:", sorted(tools))
        assert "auto_expression" in tools

        async def call(tool, **args):
            res = await s.call_tool(tool, args)
            if res.isError:
                raise RuntimeError(f"{tool} failed: {text_of(res)}")
            if tool == "new_scene":
                await isolate_mpfb(s)
            return res

        print("status:", text_of(await call("engine_status")))
        await call("new_scene")
        await call("add_primitive", kind="monkey", name="Hero", location=[0, 0, 1])
        await call("transform_object", name="Hero", rotation_deg=[0, 0, 0])
        exp = json.loads(text_of(await call("export_asset", path="e2e_hero.glb", objects=["Hero"]))[0])
        await call("new_scene")
        imp = json.loads(text_of(await call("import_model", path=exp["path"]))[0])
        assert imp["imported"][0]["name"] == "Hero", imp
        prev = await call("render_preview", view="front", width=256, height=256)
        kinds = [c.type for c in prev.content]
        assert "image" in kinds, kinds
        sheet = await call("render_views", views=["front", "right"], size=128)
        assert [c.type for c in sheet.content].count("image") == 2
        saved = await call("save_project", path="e2e.blend")
        # phase 2: character -> rig -> pose -> export
        await call("new_scene")
        await call("create_human", name="Hero", style="stylized")
        for rig_type in ("basic", "rigify"):
            rep = json.loads(text_of(await call("auto_rig_humanoid", mesh="Hero",
                                                rig_type=rig_type))[0])
            assert rep["ok"] and rep["unweighted_vertices"] == 0, rep
            assert rep["max_influences"] <= 4, rep
        await call("set_pose", armature="Hero_rig",
                   bones={"upper_arm_fk.L": [0, 0, 60], "shin_fk.R": [-45, 0, 0]})
        posed = await call("render_preview", view="three_quarter", width=256, height=256)
        assert "image" in [c.type for c in posed.content]
        glb = json.loads(text_of(await call("export_asset", path="e2e_hero_rigged.glb"))[0])
        assert glb["bytes"] > 10000, glb
        one = json.loads(text_of(await call("export_asset", path="e2e_hero_one_weight.glb",
                                            objects=["Hero_rig"], max_influences=1))[0])
        assert one["vertices_limited"] > 0, one
        _check_glb_weights(one["path"], 1)
        invalid = await s.call_tool("export_asset", {"path": "invalid.glb", "max_influences": 0})
        assert invalid.isError, invalid
        print("phase 2 rig:", rep["rig_type"], rep["deform_bones"], "deform bones")

        # phase 3: poses, clips, chaining, BVH round-trip mocap, animated glb
        await call("new_scene")
        await call("create_human", name="Walker", style="stylized")
        await call("auto_rig_humanoid", mesh="Walker")
        w = json.loads(text_of(await call("animate", armature="Walker_rig", clip="walk", cycles=1))[0])
        a = json.loads(text_of(await call("animate", armature="Walker_rig", clip="wave",
                                          start_frame=w["next_start_frame"], cycles=1))[0])
        assert a["frames"][0] == w["frames"][1] + 1, (w, a)
        fl = w["foot_lock"]["contacts"]
        assert fl["L"] and fl["R"], w
        assert a["crossfade"]["blend_frames"] >= 4, a      # wave blends in from the walk
        assert a["foot_lock"]["contacts"]["L"], a          # feet planted through the blend
        cut = json.loads(text_of(await call("animate", armature="Walker_rig", clip="nod",
                                            start_frame=a["next_start_frame"], cycles=1,
                                            blend_frames=0))[0])
        assert "crossfade" not in cut, cut
        lk = json.loads(text_of(await call("lock_feet", armature="Walker_rig", frame_start=1,
                                           frame_end=w["frames"][1]))[0])
        assert lk["feet"]["L"]["contacts"] and lk["max_ik_error_m"] < 0.01, lk
        bvh = json.loads(text_of(await call("export_asset", path="e2e_walk.bvh",
                                            objects=["Walker_rig"]))[0])
        await call("create_human", name="Pro", style="realistic", location=[2, 0, 0])
        await call("auto_rig_humanoid", mesh="Pro", rig_type="rigify")
        await call("apply_pose", armature="Pro_rig", pose="cheer")
        mo = json.loads(text_of(await call("import_mocap", path=bvh["path"], armature="Pro_rig",
                                           start_frame=1))[0])
        assert mo["bones"] >= 18, mo
        assert mo["foot_lock"]["contacts"]["L"] and mo["foot_lock"]["contacts"]["R"], mo
        frames = await call("render_frames", frames=[1, 9], view="right", size=128, objects=["Pro"])
        assert [c.type for c in frames.content].count("image") == 2
        anim_glb = json.loads(text_of(await call("export_asset", path="e2e_walker.glb",
                                                 objects=["Walker_rig"]))[0])
        import struct
        raw = open(anim_glb["path"], "rb").read()
        gltf = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
        assert len(gltf.get("animations", [])) == 1, gltf.get("animations")
        print("phase 3: mocap bones", mo["bones"], "| glb animations", len(gltf["animations"]),
              "| foot contacts", fl)

        # phase 4: lighting, two shots, scene-camera check, draft video
        await call("set_lighting", preset="studio", subject=["Walker"])
        s1 = json.loads(text_of(await call("camera_shot", subject=["Walker"], shot="full",
                                           move="tracking_side", start_frame=1, end_frame=20))[0])
        await call("camera_shot", subject=["Walker"], shot="medium", move="crash_zoom",
                   start_frame=s1["next_start_frame"], end_frame=36)
        shots = json.loads(text_of(await call("list_shots"))[0])["shots"]
        assert [x["camera"] for x in shots][:2] == ["Shot1", "Shot2"], shots
        look = await call("render_frames", frames=[1, 30], camera="scene", size=160)
        assert [c.type for c in look.content].count("image") == 2
        vid = json.loads(text_of(await call("render_video", path="e2e.mp4", quality="draft",
                                            width=320, height=180, frame_start=1, frame_end=36,
                                            wait=True))[0])
        assert vid["status"] == "done" and vid["bytes"] > 1000, vid
        opts = json.loads(text_of(await call("render_options", quality="final", vertical=True))[0])
        sizes = {o["resolution"]: o["size"] for o in opts["options"]}
        assert sizes["1080p"] == "1080x1920" and sizes["4k"] == "2160x3840", opts
        times = [o["total_s"] for o in opts["options"]]
        assert times == sorted(times) and times[0] > 0, opts
        vid2 = json.loads(text_of(await call("render_video", path="e2e_480.mp4", quality="draft",
                                             resolution="480p", frame_start=1, frame_end=6,
                                             wait=True))[0])
        assert vid2["status"] == "done" and vid2["size"] == [854, 480], vid2
        # subtitles: explicit lines -> preview frame with caption, burned-in video + .srt
        sub = json.loads(text_of(await call("add_subtitles", style="tiktok", lines=[
            {"text": "Halo semua, ini tes subtitle.", "start": 0.1, "end": 1.4}]))[0])
        assert sub["captions"] == 2 and sub["preview"][0]["text"] == "Halo semua,", sub
        capf = await call("render_frames", frames=[8], camera="scene", size=200)
        assert json.loads(text_of(capf)[0])["caption"] is True
        vs = json.loads(text_of(await call("render_video", path="e2e_subs.mp4", quality="draft",
                                           width=320, height=180, frame_start=1, frame_end=36,
                                           wait=True))[0])
        assert vs["status"] == "done" and vs["subtitles"]["captions"] == 2, vs
        assert "warning" not in vs and os.path.exists(vs["subtitles"]["srt"]), vs
        import av
        with av.open(vs["path"]) as mv:
            assert mv.streams.video[0].frames == 36, mv.streams.video[0].frames
        await call("remove_subtitles")
        # speed calibration: finished renders teach workbench speed, a test frame eevee
        assert vid["learned_speed"]["engine"] == "workbench", vid
        cal = json.loads(text_of(await call("render_options", quality="preview",
                                            calibrate=True))[0])
        assert cal["test_frame"]["engine"] == "eevee" and cal["test_frame"]["measured_s"] > 0, cal
        assert cal["machine_speed"]["measurements"] >= 1, cal
        speeds = json.load(open(CALIB))
        assert {"workbench", "eevee"} <= set(speeds), speeds
        print("phase 4: shots", len(shots), "| video", vid["progress"], vid["bytes"], "bytes",
              "| options final 1080p", next(o["total"] for o in opts["options"]
                                            if o["resolution"] == "1080p"),
              "| test frame", cal["test_frame"], "| preview 1080p",
              next(o["total"] for o in cal["options"] if o["resolution"] == "1080p"))

        # Sets/props through MCP: ownership, replacement, scaling, validation and isolation.
        presets = ("podcast_studio", "classroom", "office", "stage", "living_room", "news_desk")
        props = ("chair", "desk", "table", "microphone", "laptop", "plant", "lamp", "screen",
                 "bookshelf", "sofa", "whiteboard")
        assert {"set_environment", "add_prop", "clear_environment"} <= tools
        before = json.loads(text_of(await call("scene_info"))[0])
        keep = {o["name"] for o in before["objects"]}
        presenter = next(o for o in before["objects"] if o["name"] == "Walker_rig")
        ground_z = next(o["location"][2] for o in before["objects"] if o["name"] == "c3d_ground")
        for preset in presets:
            env = json.loads(text_of(await call("set_environment", preset=preset,
                                                subject=["Walker_rig"], variant=1))[0])
            info = json.loads(text_of(await call("scene_info"))[0])
            objects = {o["name"]: o for o in info["objects"]}
            assert env["collection"] == "char3d_env" and len(env["objects"]) > 15, env
            assert env["lights"] and all("char3d_env" in objects[n]["collections"]
                                         for n in env["objects"]), env
            assert keep <= set(objects), keep - set(objects)
            assert objects["Walker_rig"]["location"] == presenter["location"]
            if preset == "stage":
                assert objects["c3d_ground"]["location"][2] < ground_z - 0.05, objects["c3d_ground"]
            else:
                assert objects["c3d_ground"]["location"][2] == ground_z, objects["c3d_ground"]
            if preset != presets[0]:
                assert env["replaced"] > 0, env
        removed = json.loads(text_of(await call("clear_environment"))[0])
        assert removed["count"] == len(env["objects"]), removed
        # Unit-sized props transform as one group; all eleven kinds must be constructible.
        for i, kind in enumerate(props):
            prop = json.loads(text_of(await call("add_prop", kind=kind, location=[i*2, 3, 0.2],
                                                 rotation_z=90, scale=0.5))[0])
            info = json.loads(text_of(await call("scene_info"))[0])
            objects = {o["name"]: o for o in info["objects"]}
            root = objects[prop["root"]]
            assert root["location"] == [i*2, 3, 0.2] and root["scale"] == [0.5]*3, root
            assert root["rotation_deg"][2] == 90, root
            assert all(objects[n]["parent"] == prop["root"] for n in prop["objects"][1:]), prop
            if kind == "lamp":
                assert prop["lights"], prop
        prop_names = set(objects)
        # Invalid inputs must not discard existing sets/props.
        for name, args in (("set_environment", {"preset": "office", "scale": 0}),
                           ("set_environment", {"preset": "office", "variant": -1}),
                           ("set_environment", {"preset": "office", "color_theme": "invalid"}),
                           ("set_environment", {"preset": "office", "screen_image": "missing.png"}),
                           ("add_prop", {"kind": "chair", "scale": -1})):
            err = await s.call_tool(name, args)
            assert err.isError, (name, args)
        info = json.loads(text_of(await call("scene_info"))[0])
        assert {o["name"] for o in info["objects"]} == prop_names
        assert json.loads(text_of(await call("clear_environment"))[0])["count"] > 50
        assert json.loads(text_of(await call("clear_environment"))[0])["count"] == 0
        after = json.loads(text_of(await call("scene_info"))[0])
        assert {o["name"] for o in after["objects"]} == keep
        print("environments: 6 presets, 11 props, collection/replace/clear/validation OK")
        await _sitting_checks(call)
        await _graphics_checks(call)
        # Floor routes: rounded bend, sharp reversal, final facing and chained stepping turn.
        for kind in ("basic", "rigify"):
            await call("new_scene")
            await call("create_human", name="Navigator", location=[0.4, 0.2, 0])
            await call("auto_rig_humanoid", mesh="Navigator", rig_type=kind)
            if kind == "basic":
                # Enter from a moving gait whose final support is the right foot.
                await call("animate", armature="Navigator_rig", clip="walk", cycles=1)
            points = [[0.4, -3.0], [1.6, -3.0], [0.6, -2.8]]
            nav = json.loads(text_of(await call("walk_path", armature="Navigator_rig",
                                                points=[points[0], *points],
                                                face_end=[-1, 1]))[0])
            measured = await check_navigation(call, nav, points, face=[-1, 1, 0])
            assert nav["via"] == ("direct" if kind == "basic" else "proxy-retarget"), nav
            assert nav["distance_m"] > 3.5 and nav["duration_seconds"] > 3, nav
            if kind == "basic":
                # Fixed floor references make the route readable in top-view frames.
                trail = textwrap.dedent(f'''\
                    rig = bpy.data.objects['Navigator_rig']
                    saved = bpy.context.scene.frame_current
                    path = []
                    for f in range({nav['frames'][0]}, {nav['frames'][1] + 1}):
                        bpy.context.scene.frame_set(f)
                        p = (rig.matrix_world @ rig.pose.bones['hips'].matrix).translation
                        path.append((p.x, p.y, 0.012, 1.0))
                    curve = bpy.data.curves.new('NavigationTrail', 'CURVE')
                    curve.dimensions, curve.bevel_depth = '3D', 0.009
                    spline = curve.splines.new('POLY')
                    spline.points.add(len(path) - 1)
                    for point, co in zip(spline.points, path):
                        point.co = co
                    bpy.context.scene.collection.objects.link(bpy.data.objects.new('NavigationTrail', curve))
                    bpy.context.scene.frame_set(saved)
                ''')
                await call("run_blender_python", code=trail)
                markers = ["NavigationTrail"]
                for i, p in enumerate([measured["first"][:2], *points]):
                    name = f"Waypoint{i}"
                    await call("add_primitive", kind="sphere", name=name,
                               location=[*p, 0.02], size=0.06)
                    markers.append(name)
                frames = sorted(set([nav["frames"][0], *measured["waypoint_frames"], nav["frames"][1]]))
                for view in ("top", "three_quarter"):
                    images = await call("render_frames", frames=frames, view=view, size=256,
                                        objects=["Navigator_rig", *markers] if view == "top"
                                        else ["Navigator_rig"])
                    assert sum(c.type == "image" for c in images.content) == len(frames)
                await call("save_project", path="e2e_walk_path.blend")
                await call("export_asset", path="e2e_walk_path.glb", objects=["Navigator_rig"])
            turn = json.loads(text_of(await call("turn_to", armature="Navigator_rig",
                                                 target=[2, -1, 1]))[0])
            assert turn["frames"][0] == nav["next_start_frame"], turn
            tm = await check_navigation(call, turn, face=[2, -1, 0], stationary=True)
            import math
            assert math.dist(tm["first"][:2], measured["last"][:2]) < 0.005, tm
            # A later route appends from that position; turn_to also accepts object names.
            again = json.loads(text_of(await call("walk_path", armature="Navigator_rig",
                                                  points=[[0.6, -2.8], [1.0, -2.8]],
                                                  speed=1.3, face_end="Navigator"))[0])
            assert again["frames"][0] == turn["next_start_frame"], again
            await check_navigation(call, again, [[1.0, -2.8]])
            object_turn = json.loads(text_of(await call("turn_to", armature="Navigator_rig",
                                                       target="Navigator"))[0])
            await check_navigation(call, object_turn, stationary=True)
            if kind == "basic":
                fast = json.loads(text_of(await call("walk_path", armature="Navigator_rig",
                                                     points=[[1.4, -2.8]], clip="run", speed=4))[0])
                await check_navigation(call, fast, [[1.4, -2.8]])
            print(f"walk_path ({kind}): distance {nav['distance_m']:.3f} m | "
                  f"planted drift {measured['drift']:.6f} m | turn_to drift {tm['drift']:.6f} m | "
                  f"peak yaw {measured['turn_rate']:.3f} deg/s")
            for bad in ({"points": []}, {"points": [[1, 2, 3]]},
                        {"points": [[0, 0]], "speed": 0},
                        {"points": [[0, 0]], "clip": "idle"},
                        {"points": [[0, 0]], "start_frame": -1},
                        {"points": [[1e9, 0]]},
                        {"points": [[0, 0]], "face_end": "missing-target"}):
                assert (await s.call_tool("walk_path", {"armature": "Navigator_rig", **bad})).isError
            assert (await s.call_tool("turn_to", {"armature": "Navigator_rig", "target": "camera"})).isError

        await check_terrain(call, "basic")
        await check_terrain_contact_detection(call)
        await check_terrain(call, "rigify")

        # realistic humans (skipped when MPFB is not installed)
        mp = await s.call_tool("mpfb_assets", {})
        if mp.isError:
            print("mpfb: unavailable, skipped:", text_of(mp))
        else:
            await _secondary_motion_checks(call)
            await check_terrain(call, "mpfb")
            await check_terrain(call, "mpfb_rigify")
            await call("new_scene")
            h = json.loads(text_of(await call("create_realistic_human", name="Rina", gender=0.0,
                                              age=30, hair="ponytail01", location=[1.25, 0.35, 0],
                                              clothes=["female_sportsuit01", "shoes03"]))[0])
            assert h["armature"] == "Rina_rig" and h["mapped_bones"] >= 20, h
            vr = json.loads(text_of(await call("validate_rig", mesh="Rina"))[0])
            assert vr["unweighted_vertices"] == 0, vr
            an = json.loads(text_of(await call("animate", armature="Rina_rig", clip="wave",
                                               cycles=1))[0])
            assert an["via"] == "proxy-retarget", an
            img = await call("render_preview", objects=["Rina_rig"], width=160, height=160)
            assert "image" in [c.type for c in img.content]
            print("mpfb:", h["skin"], h["height_m"], "m,", len(h["parts"]), "parts, wave OK")
            # Enter from a wave at an offset position, requiring an initial turn during
            # the crossfade. Starting on X=0 misses the blend's yaw-rate regression.
            # Face keys also move the scene frame before navigation samples the rig.
            await call("lip_sync", character="Rina_rig", text="Mari berjalan bersama", start_frame=1)
            await call("camera_shot", subject=["Rina_rig"], shot="full", start_frame=1, end_frame=400)
            run = json.loads(text_of(await call("walk_path", armature="Rina_rig", clip="run",
                                                points=[[0, -1.5], [1.2, -1.5], [0.2, -1.4]],
                                                speed=1.15, face_end="camera"))[0])
            assert run["via"] == "proxy-retarget" and run["frames"][0] == an["next_start_frame"], run
            planted = [{f for a, b in run["foot_lock"]["contacts"][side] for f in range(a, b + 1)}
                       for side in "LR"]
            assert any(f not in planted[0] and f not in planted[1]
                       for f in range(*run["frames"])), "run needs flight intervals"
            rm = await check_navigation(call, run, [[0, -1.5], [1.2, -1.5], [0.2, -1.4]])
            # Camera target is read at the final turn, and a following turn samples it too.
            ct = json.loads(text_of(await call("turn_to", armature="Rina_rig", target="camera"))[0])
            assert abs(ct["turn_degrees"]) < 1.0, ct
            await check_navigation(call, ct, stationary=True)
            images = await call("render_frames", frames=rm["waypoint_frames"] + [run["frames"][1]],
                                view="three_quarter", size=256, objects=["Rina_rig"])
            assert sum(c.type == "image" for c in images.content) == 4
            await call("save_project", path="e2e_walk_path_mpfb.blend")
            print(f"walk_path (MPFB game_engine/run): distance {run['distance_m']:.3f} m | "
                  f"planted drift {rm['drift']:.6f} m | camera facing OK | "
                  f"peak yaw {rm['turn_rate']:.3f} deg/s")
            # Every furnished set around a clothed, rigged, lip-synced MPFB presenter.
            # Render office by default; opt into all six for a full visual review.
            visual_presets = presets if os.environ.get("CHAR3D_ENV_VISUALS") == "1" else ("office",)
            await call("clear_animation", armature="Rina_rig")
            await call("apply_pose", armature="Rina_rig", pose="relaxed")
            await call("set_expression", character="Rina_rig", expression="smile", strength=0.4)
            await call("lip_sync", character="Rina_rig", text="Halo, selamat datang di studio.")
            await call("auto_blink", character="Rina_rig", frame_start=1, frame_end=72)
            await call("set_lighting", preset="studio", subject=["Rina_rig"])
            await call("camera_shot", subject=["Rina_rig"], shot="wide", angle=8,
                       elevation=6, start_frame=1, end_frame=24, name="EnvironmentWide")
            image_path = json.loads(text_of(prev)[0])["path"]
            for i, preset in enumerate(presets):
                env = json.loads(text_of(await call("set_environment", preset=preset,
                                                    subject=["Rina_rig"], variant=i % 2))[0])
                assert env["standing_position"][:2] == [1.25, 0.35], env
                # Omitted subject in set_lighting must still frame the character only,
                # and must preserve the set's independently owned practical lights.
                light = json.loads(text_of(await call("set_lighting", preset="studio"))[0])
                assert light["lights"]
                if preset in visual_presets:
                    look = await call("render_frames", frames=[1], camera="scene",
                                      engine_name="eevee", size=256)
                    assert [c.type for c in look.content].count("image") == 1
                info = json.loads(text_of(await call("scene_info"))[0])
                names = {o["name"] for o in info["objects"]}
                assert set(env["lights"]) <= names
                if preset in visual_presets:
                    paths = [json.loads(t)["path"] for t in text_of(look)]
                    print("environment visual:", preset, *paths)
            # Image mapping, root anchoring, scale and deterministic replacement.
            env = json.loads(text_of(await call("set_environment", preset="office",
                                                subject=["Rina_rig"], scale=1.2, variant=3,
                                                color_theme={"accent": [0.8, 0.1, 0.05]},
                                                screen_image=image_path))[0])
            assert env["screen_image"] == image_path and env["scale"] == 1.2, env
            assert any(n.endswith("_image") for n in env["objects"]), env
            image_look = await call("render_frames", frames=[1], camera="scene",
                                    engine_name="eevee", size=256)
            print("environment image visual:", *text_of(image_look))
            # Reusing the same image while replacing a set must retain its material data.
            repeated = json.loads(text_of(await call("set_environment", preset="office",
                                                     subject=["Rina_rig"], scale=1.2, variant=3,
                                                     screen_image=image_path))[0])
            assert repeated["objects"] == env["objects"] and repeated["unit_scale"] == env["unit_scale"]
            # Environment geometry must not affect implicit subject measurement on replacement.
            implicit = json.loads(text_of(await call("set_environment", preset="classroom"))[0])
            assert abs(implicit["unit_scale"] * 1.2 - env["unit_scale"]) < 0.001
            await call("clear_environment")
            print("environment MPFB: 6 sets,", len(visual_presets), "wide Eevee checks + screen image OK")
            # Limit on export only: actual glTF weights and exact scene restoration.
            before = json.loads(text_of(await call("run_blender_python", code=WEIGHT_STATE))[0])["result"]
            limited = json.loads(text_of(await call("export_asset", path="e2e_rina_4.glb",
                                                    objects=["Rina_rig"], max_influences=4))[0])
            after = json.loads(text_of(await call("run_blender_python", code=WEIGHT_STATE))[0])["result"]
            assert before == after, (before, after)
            assert limited["vertices_limited"] > 0, limited
            await call("run_blender_python", code="""
from unittest.mock import patch
from engine.commands.io import export_asset
with patch('engine.commands.io._export', side_effect=RuntimeError('simulated export failure')):
    try:
        export_asset('e2e_failed.glb', objects=['Rina_rig'], max_influences=4)
    except RuntimeError as exc:
        assert str(exc) == 'simulated export failure'
    else:
        raise AssertionError('expected export failure')
""")
            restored = json.loads(text_of(await call("run_blender_python", code=WEIGHT_STATE))[0])["result"]
            assert before == restored, (before, restored)
            skins = _check_glb_weights(limited["path"], 4)
            imported = json.loads(text_of(await call("import_model", path=limited["path"]))[0])
            imported_rig = next(o["name"] for o in imported["imported"] if o["type"] == "ARMATURE")
            look = await call("render_views", objects=[imported_rig], size=256, frame=9)
            assert [c.type for c in look.content].count("image") == 4
            await call("delete_objects", names=[o["name"] for o in imported["imported"]])
            print("export weights:", limited["vertices_limited"], "vertices limited |", skins,
                  "skinned primitives <= 4 | normalized | scene unchanged")
            # Rigify + face: expression, lip sync, blink
            await call("new_scene")
            d = json.loads(text_of(await call("create_realistic_human", name="Dani", gender=1.0,
                                              age=28, rig="rigify"))[0])
            assert d["face_rig"] and any("teeth" in p for p in d["parts"]), d
            vr = json.loads(text_of(await call("validate_rig", mesh="Dani"))[0])
            assert vr["ok"] and vr["rig_type"] == "rigify", vr
            ex = json.loads(text_of(await call("set_expression", character="Dani_rig",
                                               expression="laugh", frame=1, keyframe=True))[0])
            assert ex["active_units"].get("jawOpen", 0) > 0 and len(ex["meshes"]) >= 3, ex
            ls = json.loads(text_of(await call("lip_sync", character="Dani_rig",
                                               text="Halo semuanya", start_frame=5))[0])
            assert ls["mouth_shapes"] >= 8 and ls["next_start_frame"] > 20, ls
            assert ls["detail"] == "phoneme" and ls["language"] == "id", ls
            bl = json.loads(text_of(await call("auto_blink", character="Dani_rig",
                                               frame_start=1, frame_end=200))[0])
            assert len(bl["blinks"]) >= 1, bl
            an = json.loads(text_of(await call("animate", armature="Dani_rig", clip="nod",
                                               cycles=1, speed=6))[0])
            assert an["via"] == "proxy-retarget", an
            print("mpfb rigify+face:", vr["bones_total"], "bones,", len(ex["meshes"]),
                  "face meshes, lip sync", ls["mouth_shapes"], "shapes")
            # Slow, easy-to-inspect phonemes: closure m/b/p, rounded o/u, open a, f/v contact.
            await call("scene_info")
            await call("set_expression", character="Dani_rig", expression="smile",
                       strength=0.45, frame=40, keyframe=True, transition_frames=0)
            ph = json.loads(text_of(await call("lip_sync", character="Dani_rig",
                                               text="mama popo bubu fava", start_frame=40,
                                               chars_per_second=4, language="id"))[0])
            samples = {p: next(e for e in ph["phonemes"] if e["phoneme"] == p and e["frame"])
                       for p in ("m", "b", "p", "ow", "uw", "aa", "f", "v")}
            frames = {p: e["frame"] for p, e in samples.items()}
            values = json.loads(text_of(await call("run_blender_python", code=f'''
from engine.commands.face import _face_meshes
meshes = _face_meshes(bpy.data.objects["Dani"])
result = {{}}
for phone, frame in {frames!r}.items():
    bpy.context.scene.frame_set(frame)
    result[phone] = {{m.name: {{k.name: k.value for k in m.data.shape_keys.key_blocks
                             if k.name in ("p_b_m_21", "ow_08", "w_uw_07", "aa_02", "f_v_18", "jawOpen", "mouthClose", "mouthPucker")}}
                     for m in meshes}}
'''))[0])["result"]
            for p in ("m", "b", "p"):
                assert values[p]["Dani"]["p_b_m_21"] > 0.99, values[p]
                assert values[p]["Dani"]["jawOpen"] < 0.001, values[p]
                assert 0.09 < values[p]["Dani"]["mouthClose"] < 0.11, values[p]
                assert values[p]["Dani"]["aa_02"] < 0.001, values[p]
                assert values[p]["Dani"]["w_uw_07"] < 0.001, values[p]
            for p, vis in (("ow", "ow_08"), ("uw", "w_uw_07"), ("aa", "aa_02"),
                           ("f", "f_v_18"), ("v", "f_v_18")):
                assert values[p]["Dani"][vis] >= 0.89, values[p]
                assert values[p]["Dani"]["p_b_m_21"] < 0.001, values[p]
            for mesh_values in values["m"].values():
                if "p_b_m_21" in mesh_values:
                    assert mesh_values["p_b_m_21"] > 0.99, mesh_values
            assert values["uw"]["Dani"]["mouthPucker"] > 0.5, values["uw"]
            await call("set_lighting", preset="studio", subject=["Dani_rig"])
            await call("camera_shot", name="phoneme_closeup", subject=["Dani_rig"],
                       shot="close_up", angle=0, start_frame=40, end_frame=ph["frames"][1])
            look = await call("render_frames", frames=[frames[p] for p in ("m", "b", "p", "ow", "uw", "aa")],
                              camera="scene", engine_name="eevee", size=512)
            assert [c.type for c in look.content].count("image") == 6
            print("phoneme closeups:", frames, text_of(look))
            await call("save_project", path="e2e_phonemes.blend")
            legacy = json.loads(text_of(await call("lip_sync", character="Dani_rig",
                                                   text="hello world", detail="word", start_frame=200))[0])
            assert legacy["detail"] == "word" and not legacy["phonemes"], legacy
            english = json.loads(text_of(await call("lip_sync", character="Dani_rig",
                                                    text="hello people you’re", start_frame=250))[0])
            assert english["language"] == "en", english
            assert [e["phoneme"] for e in english["phonemes"][:4]] == ["h", "ax", "l", "ow"], english
            assert [e["phoneme"] for e in english["phonemes"] if e["word"] == "you’re"] == ["y", "ao", "r"], english
            fallback = json.loads(text_of(await call("run_blender_python", code='''
from engine.commands.face import ARKIT, lip_sync
mesh = bpy.data.meshes.new("ArkitFixture")
mesh.from_pydata([(0, 0, 0)], [], [])
obj = bpy.data.objects.new("ArkitFixture", mesh)
bpy.context.collection.objects.link(obj)
obj.shape_key_add(name="Basis")
for name in ARKIT:
    obj.shape_key_add(name=name)
r = lip_sync(obj.name, "mama fava", chars_per_second=4, language="id")
keys = obj.data.shape_keys.key_blocks
for phone, shape, minimum in (("m", "mouthClose", 0.99), ("aa", "jawOpen", 0.6),
                               ("f", "mouthRollLower", 0.79)):
    e = next(e for e in r["phonemes"] if e["phoneme"] == phone and e["frame"])
    bpy.context.scene.frame_set(e["frame"])
    assert keys[shape].value > minimum, (phone, shape, keys[shape].value)
bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.meshes.remove(mesh)
result = True
'''))[0])["result"]
            assert fallback, fallback
            print("phoneme lip sync: ID/EN, m/b/p closure, o/u rounding, a opening, f/v contact, legacy OK")

            # Sentence emotions: bilingual phrases, negation, punctuation and real
            # MPFB shape keys. Compare protected curves before/after, not just reports.
            await call("set_expression", character="Dani_rig", expression="neutral",
                       frame=1, keyframe=True)
            ls3 = json.loads(text_of(await call(
                "lip_sync", character="Dani_rig", start_frame=12, chars_per_second=22,
                text="Senang sekali! Sayang sekali. Wow amazing! Saya kesal. "
                     "Takut bahaya. Hmm mungkin? Tidak senang."))[0])
            face_end = ls3["frames"][1] + 24
            await call("set_timeline", frame_end=face_end)
            await call("auto_blink", character="Dani_rig", frame_end=face_end)

            async def face_curves():
                return json.loads(text_of(await call("run_blender_python", code=FACE_CURVES))[0])["result"]

            before = await face_curves()
            ae = json.loads(text_of(await call("auto_expression", character="Dani_rig"))[0])
            emotions = [e["emotion"] for e in ae["sentences"]]
            assert emotions == ["joy", "sad", "surprise", "anger", "fear", "thinking", "neutral"], ae
            assert len(ae["meshes"]) >= 3 and ae["frames"] == [1, face_end], ae
            assert ae["sentences"][-1]["relax_frame"] is not None, ae
            for event in ae["sentences"]:
                peak, hold = event["frames"]
                assert 1 <= peak <= hold <= face_end, event
                assert abs(event["sentence_frames"][0] - peak - 5) <= 0.6, event
            assert ae["sentences"][0]["strength"] > ae["sentences"][3]["strength"], ae
            after = await face_curves()
            paths = {f'key_blocks["{name}"].value' for name in ae["keyed_units"]}
            protected = 0
            for mesh, curves in before.items():
                for path, points in curves.items():
                    if path not in paths:
                        assert after[mesh][path] == points, (mesh, path)
                        protected += 1
            assert protected > 20, protected
            # Re-running replaces its layer instead of accumulating old expression keys.
            await call("auto_expression", character="Dani_rig")
            assert await face_curves() == after
            await call("auto_blink", character="Dani_rig", frame_end=face_end)
            blinked = await face_curves()
            for mesh, curves in after.items():
                for path in curves.keys() & paths:
                    assert blinked[mesh][path] == curves[path], (mesh, path)

            # Check evaluated weights and visemes during speech, also on brows/lashes.
            check = '''
from engine.commands.face import _basemesh, _face_meshes, VISEMES
mesh = _basemesh("Dani_rig")
sk = mesh.data.shape_keys.key_blocks
samples = []
for event in EVENTS[:6]:
    bpy.context.scene.frame_set(event["frames"][0])
    unit = {"joy": "cheekSquintLeft", "sad": "browInnerUp",
            "surprise": "eyeWideLeft", "anger": "browDownLeft",
            "fear": "eyeWideLeft", "thinking": "browInnerUp"}[event["emotion"]]
    value = sk[unit].value
    assert value > 0.05, (event, unit, value)
    for part in _face_meshes(mesh):
        key = part.data.shape_keys.key_blocks.get(unit)
        if key is not None:
            assert abs(key.value - value) < 1e-5, (part.name, unit)
    samples.append(round(value, 3))
bpy.context.scene.frame_set(EVENTS[-1]["frames"][0])
assert sk["mouthSmileLeft"].value < 1e-5     # negated joy has no smile
bpy.context.scene.frame_set(EVENTS[-1]["relax_frame"])
assert abs(sk["mouthSmileLeft"].value - 0.7 * 0.35) < 1e-5  # back to base in pause
assert sk["browInnerUp"].value < 1e-5
assert any(fc.evaluate(f) > 0.1 for fc in _fcurves(mesh.data.shape_keys.animation_data.action)
           if any(v in fc.data_path for v in VISEMES) for f in range(12, END))
result = samples
'''
            checked = json.loads(text_of(await call("run_blender_python", code=(
                "from engine.commands.talk import _fcurves\nEVENTS = " + repr(ae["sentences"])
                + "\nEND = " + str(face_end) + "\n" + check)))[0])
            await call("set_lighting", preset="studio", subject=["Dani_rig"])
            await call("camera_shot", subject=["Dani_rig"], shot="close_up",
                       start_frame=1, end_frame=face_end)
            # Render inside each sentence, while the mouth is also speaking.
            view_frames = [round(sum(e["sentence_frames"]) / 2) for e in ae["sentences"][:6]]
            faces = await call("render_frames", frames=view_frames, camera="scene",
                               engine_name="eevee", size=512)
            assert [c.type for c in faces.content].count("image") == 6
            print("auto_expression:", emotions, "| protected curves", protected,
                  "| evaluated weights", checked["result"], "| close_up frames", view_frames)
            await call("save_project", path="e2e_auto_expression.blend")

            # Explicit cues work without word times and stay within the requested range.
            cue_start, cue_end = face_end + 10, face_end + 60
            cued = json.loads(text_of(await call(
                "auto_expression", character="Dani", frame_start=cue_start, frame_end=cue_end,
                base="neutral", cues=[{"frame": cue_start + 10, "expression": "sad", "strength": 0.8}]))[0])
            assert cued["sentences"][0]["source"] == "cue", cued
            assert cued["sentences"][0]["frames"][0] == cue_start + 10, cued
            limited = await face_curves()
            for mesh, curves in blinked.items():
                for path, points in curves.items():
                    assert ([p for p in limited[mesh][path] if p[0][0] <= face_end]
                            == [p for p in points if p[0][0] <= face_end]), (mesh, path)
            # Far past every lip-synced line (the phoneme checks add words at 200 and 250).
            no_words = await s.call_tool("auto_expression", {"character": "Dani_rig",
                                        "frame_start": cue_end + 500, "frame_end": cue_end + 510})
            assert no_words.isError and "no word times" in str(text_of(no_words)), no_words
            forced = json.loads(text_of(await call(
                "auto_expression", character="Dani_rig",
                cues=[{"frame": ae["sentences"][0]["frames"][0], "expression": "sad", "strength": 0.9},
                      {"frame": ae["sentences"][0]["frames"][0] + 2,
                       "expression": "angry", "strength": 0.8}]))[0])
            assert forced["sentences"][0]["source"] == "cue", forced
            assert forced["sentences"][0]["expression"] == "sad", forced
            assert forced["sentences"][1]["source"] == "cue", forced
            assert forced["sentences"][1]["sentence"] == forced["sentences"][0]["sentence"], forced
            # Matcher edge cases exercise phrases, suffixes, language selection,
            # clause-scoped negation and the question-only fallback.
            lexicon = '''
from engine.commands.emotion import classify
def emotion(text, language="auto"):
    return classify([(w, i, i + 1) for i, w in enumerate(text.split())], language)[0]
for text, expected in [("Tidak senang.", "neutral"), ("not very happy!", "neutral"),
                       ("not sad but great!", "joy"), ("tidak marah, senang!", "joy"),
                       ("mantapnya!", "joy"), ("sayang sekali.", "sad"),
                       ("Unfortunately.", "sad"), ("coba pikir.", "thinking"),
                       ("Apa?", "thinking"), ("Hello.", "base")]:
    assert emotion(text) == expected, (text, emotion(text))
assert emotion("senang", "en") == "base"
assert emotion("seronok", "ms") == "joy"
assert emotion("happy", "en") == "joy"
result = "phrases, suffixes, negation, questions, id/ms/en OK"
'''
            lex = json.loads(text_of(await call("run_blender_python", code=lexicon))[0])
            print("auto_expression cues/ranges:", lex["result"])

        # audio: synthetic "speech" (vowels via formant filters, hiss, pauses) -> timeline,
        # lip sync from audio/text, and a draft video that must carry an AAC track
        wav = _synthetic_speech(os.path.join(ROOT, "output", "imports", "audio", "e2e_synth.wav"))
        await call("new_scene")
        await call("add_primitive", kind="monkey", name="Mic")
        mp = await s.call_tool("mpfb_assets", {})
        if not mp.isError:
            await call("create_realistic_human", name="Vo", gender=0.0, age=30, location=[1, 0, 0])
            for timing in ("audio", "text"):
                la = json.loads(text_of(await call(
                    "lip_sync_audio", character="Vo_rig", audio=wav, timing=timing,
                    text="Happy! Sorry. Wow! Afraid.", add_sound=False))[0])
                assert la["mode"] == timing and la["mouth_shapes"] >= 4, la
                if timing == "audio":
                    missing = await s.call_tool("auto_expression", {"character": "Vo_rig"})
                    assert missing.isError and "no word times" in str(text_of(missing)), missing
                else:
                    audio_face = json.loads(text_of(await call(
                        "auto_expression", character="Vo_rig", intensity=0.5,
                        base="neutral", base_strength=0, language="en"))[0])
                    assert [e["emotion"] for e in audio_face["sentences"]] == [
                        "joy", "sad", "surprise", "fear"], audio_face
                    assert audio_face["sentences"][0]["strength"] == 0.375, audio_face
                assert la["detail"] == ("audio" if timing == "audio" else "phoneme"), la
            # Whisper-shaped word intervals, without downloading an ASR model for synthetic audio.
            # Use the same engine command the Whisper MCP path calls, and inspect actual curves.
            aligned = json.loads(text_of(await call("run_blender_python", code=f'''
from engine.commands.audio import lip_sync_audio
from engine.commands.semantic import load_words
words = [{{"word": "mama", "start": 0.2, "end": 1.0}},
         {{"word": "buka", "start": 1.4, "end": 2.0}}]
r = lip_sync_audio("Vo_rig", {wav!r}, start_frame=9, words=words, language="ms", add_sound=False)
assert r["detail"] == "phoneme" and r["language"] == "ms"
for e in r["phonemes"]:
    w = next(w for w in words if w["word"] == e["word"])
    assert 9 + w["start"] * 24 - 0.001 <= e["start"] < e["end"] <= 9 + w["end"] * 24 + 0.001
    if e["phoneme"] in ("m", "b", "p") and e["frame"] is not None:
        bpy.context.scene.frame_set(e["frame"])
        assert bpy.data.objects["Vo"].data.shape_keys.key_blocks["p_b_m_21"].value > 0.99
assert len(load_words(bpy.data.objects["Vo"], 9, r["frames"][1])) == 2
bpy.context.scene.frame_set(38)  # pause between supplied words
assert all(k.value < 0.001 for k in bpy.data.objects["Vo"].data.shape_keys.key_blocks
           if k.name in ("p_b_m_21", "aa_02", "w_uw_07"))
result = {{"phonemes": len(r["phonemes"]), "bounded": True}}
'''))[0])["result"]
            assert aligned["bounded"] and aligned["phonemes"] >= 8, aligned
            old_audio = json.loads(text_of(await call("lip_sync_audio", character="Vo_rig", audio=wav,
                                                       timing="text", text="mama buka", detail="word",
                                                       start_frame=90, add_sound=False))[0])
            assert old_audio["detail"] == "word" and not old_audio["phonemes"], old_audio
            print("audio phonemes: word boundaries, quiet closure, stored words, legacy OK")
            print("audio lip sync: audio/text modes OK")
            print("auto_expression audio: text timing + intensity OK; audio-only needs cues")
            await call("add_audio", path=wav, start_frame=1)
            await call("animate", armature="Vo_rig", clip="idle", cycles=1)
            await call("camera_shot", subject=["Vo_rig"], shot="close_up", start_frame=1,
                       end_frame=60)
            tm = json.loads(text_of(await call("talk_motion", character="Vo_rig",
                                               frame_start=1, frame_end=60))[0])
            assert tm["driven_by"].startswith("audio:") and tm["saccades"] >= 1, tm
            rng = tm["head_range_deg"]
            assert max(abs(v) for pair in rng.values() for v in pair) < 25, rng
            print("talk_motion:", tm["driven_by"], "emphasis", len(tm["emphasis_frames"]),
                  "saccades", tm["saccades"])
            tg = json.loads(text_of(await call("talk_gestures", character="Vo_rig",
                                               frame_start=1, frame_end=60,
                                               style="energetic"))[0])
            assert tg["talking_frames"] > 10 and len(tg["arm_bones"]) == 4, tg
            assert tg["finger_bones"] == 30, tg
            hp = json.loads(text_of(await call("set_hand_pose", character="Vo_rig", shape="point",
                                               side="right", frame=70, keyframe=True))[0])
            assert hp["bones"] == 15 and hp["keyed"], hp
            print("talk_gestures (MPFB):", [g["type"] for g in tg["gestures"]])
            # meaning gestures from stored word times (lip_sync text)
            ls2 = json.loads(text_of(await call(
                "lip_sync", character="Vo_rig", start_frame=1,
                text="Saya punya dua ide besar, dan ini tidak sulit."))[0])
            tgs = json.loads(text_of(await call("talk_gestures", character="Vo_rig",
                                                frame_start=1, frame_end=ls2["frames"][1]))[0])
            kinds = [g["type"] for g in tgs["semantic"]]
            assert tgs["words_known"] >= 9 and "two" in kinds, tgs
            assert tgs["hand_bones"] == ["hand_l", "hand_r"] and tgs["max_palm_twist_deg"] > 10, tgs
            print("talk_gestures semantic:", [(g["word"], g["type"]) for g in tgs["semantic"]])
            # dialog: two characters, an audio line and text lines, staged + covered
            await call("remove_audio")
            await call("create_realistic_human", name="Ko", gender=1.0, age=35)
            dg = json.loads(text_of(await call("dialog", start_frame=200, lines=[
                {"speaker": "Vo_rig", "text": "Ko, kamu sudah lihat dua hasil render kemarin?"},
                {"speaker": "Ko_rig", "audio": wav},
                {"speaker": "Vo_rig", "text": "Bagus, kita lanjutkan besok saja ya."}]))[0])
            assert [t["speaker"] for t in dg["turns"]] == ["Vo_rig", "Ko_rig", "Vo_rig"], dg
            assert len(dg["shots"]) == 3 and dg["shots"][0]["subject"] == "two_shot", dg["shots"]
            assert dg["shots"][1]["subject"] == "Ko_rig" and dg["idle_added"] == ["Ko_rig"], dg
            assert sum(m["listener_nods"] for m in dg["motion"].values()) >= 1, dg["motion"]
            assert "dua" in dg["gestures"]["Vo_rig"]["semantic"], dg["gestures"]
            print("dialog:", [(s_["subject"], s_["frames"]) for s_ in dg["shots"]],
                  "| nods", {k: m["listener_nods"] for k, m in dg["motion"].items()})
            await call("remove_audio")
        aa = json.loads(text_of(await call("add_audio", path=wav, start_frame=1))[0])
        assert aa["seconds"] > 2, aa
        await call("create_human", name="Mq", style="stylized", location=[-1.2, 0, 0])
        await call("auto_rig_humanoid", mesh="Mq", rig_type="rigify")
        tgm = json.loads(text_of(await call("talk_gestures", character="Mq_rig",
                                            frame_start=1, frame_end=50))[0])
        assert tgm["talking_frames"] > 10, tgm
        print("talk_gestures (rigify mannequin):", tgm["arm_bones"])
        tgc = json.loads(text_of(await call("talk_gestures", character="Mq_rig", frame_start=1,
                                            frame_end=50, semantic=False,
                                            cues=[{"frame": 25, "gesture": "stop"}]))[0])
        assert [g["type"] for g in tgc["semantic"]] == ["stop"], tgc
        print("talk_gestures cue on mannequin OK")
        await call("camera_shot", shot="medium", start_frame=1, end_frame=aa["frames"][1])
        await call("add_title", text="Audio + graphics", style="corner", duration_s=2)
        await call("add_transition", kind="fade_in", duration_s=0.25)
        v = json.loads(text_of(await call("render_video", path="e2e_audio.mp4", quality="draft",
                                          width=256, height=144, frame_start=1,
                                          frame_end=aa["frames"][1], wait=True))[0])
        assert v["status"] == "done" and v["has_audio"], v
        import av
        with av.open(v["path"]) as c:
            kinds = sorted(st.type for st in c.streams)
        assert kinds == ["audio", "video"], kinds
        assert v["graphics"]["titles"] == 1 and v["graphics"]["transitions"] == 1, v
        print("audio: strip + AAC video with graphics OK")

        # Music: continuous repeats, fades over the whole track, voice/word ducking.
        # A brief pause between voices merges; sfx and muted voices never duck music.
        await call("remove_audio")
        await call("set_timeline", frame_start=1, frame_end=144, fps=24)
        tone = _tone(os.path.join(ROOT, "output", "imports", "audio", "e2e_tone.wav"))
        music = json.loads(text_of(await call("add_audio", path=tone, kind="music", volume=0.6,
                                              loop=True, fade_in=0.25, fade_out=0.5))[0])
        other_music = json.loads(text_of(await call("add_audio", path=tone, kind="music",
                                                    volume=0.1))[0])
        assert music["frames"] == [1, 144] and len(music["strips"]) == 12, music
        voices = []
        for frame in (25, 43, 97):
            voice = json.loads(text_of(await call("add_audio", path=tone, start_frame=frame))[0])
            assert voice["kind"] == "voice", voice
            voices.append(voice["strip"])
        muted = json.loads(text_of(await call("add_audio", path=tone, start_frame=73))[0])
        await call("add_audio", path=tone, kind="sfx", start_frame=73)
        setup = f"""
from engine.commands.audio import _sound_strips
from engine.commands.semantic import store_words
for obj in bpy.context.scene.objects:
    if 'char3d_words' in obj:
        del obj['char3d_words']
store_words(bpy.data.objects['Mic'], [('word', 113, 117)], 113, 117)
for st in _sound_strips(bpy.context.scene):
    if st.name == {muted['strip']!r}:
        st.mute = True
    if st.name == {voices[1]!r}:
        del st['char3d_audio_kind']  # old projects' untagged strips are voice
"""
        await call("run_blender_python", code=setup)
        duck = json.loads(text_of(await call("duck_music", music_strip=music["strips"][3]))[0])
        assert set(duck["strips"]) == set(music["strips"]), duck
        assert duck["speech_ranges"] == [[25.0, 55.0], [97.0, 117]], duck
        inspect = f"""
from engine.commands.audio import _sound_strips, _volume_curve
from engine.commands.talk import _audio_activity
assert set(_audio_activity(1, 144)[1]) == set({voices!r})
music = [st for st in _sound_strips(bpy.context.scene) if st.name in {music['strips']!r}]
assert all(st.get('char3d_audio_kind') == 'music' for st in music)
spans = sorted((int(st.frame_final_start), int(st.frame_final_end)) for st in music)
assert spans[0][0] == 1 and spans[-1][1] == 145
assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
samples = {{}}
for frame in [1, 7, 19, 23, 30, 60, 73, 96, 103, 128, 139, 145]:
    st = next((st for st in music if st.frame_final_start <= frame < st.frame_final_end), music[-1])
    fc = _volume_curve(st)
    assert fc and all(k.interpolation == 'LINEAR' and -1e-6 <= k.co.y <= 0.60001
                      for k in fc.keyframe_points)
    samples[str(frame)] = fc.evaluate(frame)
other = next(st for st in _sound_strips(bpy.context.scene) if st.name == {other_music['strip']!r})
assert _volume_curve(other) is None  # only the selected loop group was changed
result = samples
"""
        samples = json.loads(text_of(await call("run_blender_python", code=inspect))[0])["result"]
        floor = 0.6 * 10 ** (-12 / 20)
        assert abs(samples["1"]) < 1e-6 and abs(samples["145"]) < 1e-6, samples
        for frame in (7, 19, 73, 128):
            assert abs(samples[str(frame)] - 0.6) < 1e-5, samples
        for frame in (30, 103):
            assert abs(samples[str(frame)] - floor) < 1e-5, samples
        for frame in (23, 60, 96):
            assert floor < samples[str(frame)] < 0.6, samples
        assert abs(samples["139"] - 0.3) < 1e-5, samples
        await call("duck_music", music_strip=music["strip"])
        repeated = json.loads(text_of(await call("run_blender_python", code=inspect))[0])["result"]
        assert samples == repeated, (samples, repeated)  # no cumulative attenuation
        listing = json.loads(text_of(await call("list_audio"))[0])["strips"]
        assert {st["kind"] for st in listing} == {"music", "voice", "sfx"}, listing
        await call("camera_shot", shot="medium", start_frame=1, end_frame=144)
        check = await call("render_frames", frames=[7, 30, 73], camera="scene", size=256)
        assert [c.type for c in check.content].count("image") == 3
        await call("save_project", path="e2e_music.blend")
        mv = json.loads(text_of(await call("render_video", path="e2e_music.mp4", quality="draft",
                                           width=256, height=144, frame_start=1, frame_end=144,
                                           wait=True))[0])
        assert mv["status"] == "done" and mv["has_audio"], mv
        energy = {"normal": [], "ducked": []}
        with av.open(mv["path"]) as movie:
            assert movie.streams.audio[0].codec_context.name == "aac"
            for frame in movie.decode(audio=0):
                # These windows contain music only; the second is ducked by word times.
                for label, a, b in (("normal", 85 / 24, 90 / 24), ("ducked", 110 / 24, 116 / 24)):
                    if a <= frame.time and frame.time + frame.samples / frame.sample_rate <= b:
                        energy[label].append(float((frame.to_ndarray().astype("float64") ** 2).mean()))
        normal = (sum(energy["normal"]) / len(energy["normal"])) ** 0.5
        quiet = (sum(energy["ducked"]) / len(energy["ducked"])) ** 0.5
        assert normal > 0.001 and 0.15 < quiet / normal < 0.4, (normal, quiet)
        # Removing speech restores the original volume while keeping the fades.
        for name in voices:
            await call("remove_audio", name=name)
        words_only = json.loads(text_of(await call("duck_music"))[0])
        assert words_only["speech_ranges"] == [[113, 117]], words_only
        await call("run_blender_python", code="del bpy.data.objects['Mic']['char3d_words']")
        reset = json.loads(text_of(await call("duck_music"))[0])
        assert reset["speech_ranges"] == [] and other_music["strip"] in reset["strips"], reset
        print("music: 12 continuous loops | fades + -12 dB duck curves OK | rerun stable | AAC draft OK")

        guide = await s.read_resource("char3d://guide")
        assert "Working loop" in guide.contents[0].text
        await call("new_scene")
        empty_env = json.loads(text_of(await call("set_environment", preset="living_room"))[0])
        assert empty_env["unit_scale"] == 1 and empty_env["standing_position"] == [0, 0, 0]
        await call("clear_environment")
        assert not json.loads(text_of(await call("scene_info"))[0])["objects"]
        await call("engine_shutdown")
        print("saved:", text_of(saved))
        print("E2E OK")


if __name__ == "__main__":
    asyncio.run(main())
