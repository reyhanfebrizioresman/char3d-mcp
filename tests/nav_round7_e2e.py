import asyncio, json, os, sys, textwrap
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tests"))
sys.path.insert(0, str(ROOT))
(ROOT/"output"/"renders").mkdir(parents=True, exist_ok=True)
import e2e_smoke as E
from e2e_smoke import *  # noqa
globals().update({k: v for k, v in vars(E).items() if k.startswith("_") and not k.startswith("__")})
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=str(ROOT), env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        async def call(tool, **args):
            res = await s.call_tool(tool, args)
            if res.isError:
                raise RuntimeError(tool + " failed: " + str(E.text_of(res)))
            return res
        if "nav" in sys.argv:
            await _sitting_checks(call)
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

            print("NAV OK", flush=True)
        if "avoid" in sys.argv:
            await check_obstacle_avoidance(call, "basic")
            print("AVOID OK", flush=True)
        if "terrain" in sys.argv:
            await check_terrain(call, "basic")
            await check_terrain_contact_detection(call)
            print("TERRAIN OK", flush=True)
        await call("engine_shutdown")
asyncio.run(main())
