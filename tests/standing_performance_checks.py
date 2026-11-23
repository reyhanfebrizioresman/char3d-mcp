"""Focused Blender smoke test for the reusable walk-to-button workflow."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp_server.blender_client import BlenderClient, EngineError  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="char3d-standing-") as workspace:
        os.environ.setdefault("CHAR3D_PORT", "9983")
        os.environ["CHAR3D_WORKSPACE"] = workspace
        os.environ["CHAR3D_ALLOW_PYTHON"] = "1"
        engine = BlenderClient()
        try:
            check(engine)
        finally:
            engine.stop()


def check(engine):
    call = engine.call
    call("new_scene", fps=30, frame_end=2)
    call("create_human", name="StandTest", style="realistic")
    rig = call("auto_rig_humanoid", mesh="StandTest", rig_type="basic")["armature"]
    route = call("walk_path", armature=rig, points=[[0, -1.75]], start_frame=1, avoid=False)
    source = call("export_asset", path="generated-walk.bvh", objects=[rig])["path"]
    call("clear_animation", armature=rig)
    call("set_timeline", frame_end=2)
    walk = call("walk_approach", armature=rig, path=source, source_frames=route["frames"],
                contacts=route["foot_lock"]["contacts"], destination=[.13, -.75])
    walk_end = walk["frames"][1]
    assert walk["destination"] == [.13, -.75], walk
    assert walk["next_start_frame"] == walk_end + 1
    assert walk["footfalls"] == sorted(walk["footfalls"], key=lambda e: (e["frame"], e["side"]))
    assert walk["footfalls"]
    sound = call("auto_sfx", characters=[rig], kinds=["footsteps"], footfalls=walk["footfalls"], surface="tile")
    assert [e["frame"] for e in sound["touchdowns"]] == [e["frame"] for e in walk["footfalls"]]
    assert sound["counts"]["footsteps"] == len(walk["footfalls"])

    target = call("run_python", code=f"""
from engine.commands.anim import semantic_map
from engine.commands.performance import heading, UP
sc = bpy.context.scene
sc.frame_set({walk_end})
rig = bpy.data.objects[{rig!r}]
names = semantic_map(rig)
shoulder = rig.matrix_world @ rig.pose.bones[names['upper_arm.L']].head
forward, left = heading(rig)
result = list(shoulder + .27*forward + .025*left - .25*UP)
""")["result"]
    cap = call("add_primitive", kind="cube", name="GroundedButton",
               location=[target[0], target[1], target[2] - .018], size=.036)["name"]
    try:
        call("press_button", character=rig, button=cap, target=[50, 50, 3])
    except EngineError as error:
        assert "reach" in str(error)
    else:
        raise AssertionError("out-of-reach cap should fail")

    press = call("press_button", character=rig, button=cap, target=target,
                 start_frame=walk_end + 2, travel=.012, hold_seconds=.2)
    assert press["contact_error_m"] < .001, press
    assert press["contact_site"] == "hand"
    pressed, end, start = (press["frames"][key] for key in ("pressed", "end", "start"))
    checks = call("run_python", code=f"""
from engine.commands.anim import semantic_map
sc = bpy.context.scene
rig = bpy.data.objects[{rig!r}]
cap = bpy.data.objects[{cap!r}]
names = semantic_map(rig)
def sample(f):
    sc.frame_set(f)
    ankles = [rig.matrix_world @ rig.pose.bones[names['foot.' + side]].head for side in 'LR']
    return cap.matrix_world.translation.z, ankles
start_cap, stance = sample({start})
down, _ = sample({pressed})
end, _ = sample({end})
drift = max((a-b).length for f in range({start}, {end}+1) for a,b in zip(stance,sample(f)[1]))
result = (start_cap - down, start_cap - end, drift)
""")["result"]
    assert abs(checks[0] - .012) < .0001 and abs(checks[1]) < .0001 and checks[2] < .005, checks
    print("STANDING PERFORMANCE OK", len(walk["footfalls"]), "authored steps", press["contact_error_m"], "m contact error")


if __name__ == "__main__":
    main()
