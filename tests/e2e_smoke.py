"""End-to-end check: real MCP client -> MCP server (stdio) -> Blender engine.

    .venv/bin/python tests/e2e_smoke.py
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
# Inspect baked world-space contacts, rather than trusting the planner's IK report.
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


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        assert "char3d" in (init.instructions or ""), "server instructions missing"
        tools = {t.name for t in (await s.list_tools()).tools}
        print("tools:", sorted(tools))

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
                                            frame_start=1, frame_end=36, wait=True))[0])
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
                                           frame_start=1, frame_end=36, wait=True))[0])
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

        # realistic humans (skipped when MPFB is not installed)
        mp = await s.call_tool("mpfb_assets", {})
        if mp.isError:
            assert "MPFB is not installed" in " ".join(text_of(mp)), text_of(mp)
            print("mpfb: not installed, skipped")
        else:
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
            bl = json.loads(text_of(await call("auto_blink", character="Dani_rig",
                                               frame_start=1, frame_end=200))[0])
            assert len(bl["blinks"]) >= 1, bl
            an = json.loads(text_of(await call("animate", armature="Dani_rig", clip="nod",
                                               cycles=1))[0])
            assert an["via"] == "proxy-retarget", an
            print("mpfb rigify+face:", vr["bones_total"], "bones,", len(ex["meshes"]),
                  "face meshes, lip sync", ls["mouth_shapes"], "shapes")

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
                    text="aa ee oo ss aa", add_sound=False))[0])
                assert la["mode"] == timing and la["mouth_shapes"] >= 4, la
            print("audio lip sync: audio/text modes OK")
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
        v = json.loads(text_of(await call("render_video", path="e2e_audio.mp4", quality="draft",
                                          wait=True))[0])
        assert v["status"] == "done" and v["has_audio"], v
        import av
        with av.open(v["path"]) as c:
            kinds = sorted(st.type for st in c.streams)
        assert kinds == ["audio", "video"], kinds
        print("audio: strip + AAC video OK")

        guide = await s.read_resource("char3d://guide")
        assert "Working loop" in guide.contents[0].text
        await call("engine_shutdown")
        print("saved:", text_of(saved))
        print("E2E OK")


if __name__ == "__main__":
    asyncio.run(main())
