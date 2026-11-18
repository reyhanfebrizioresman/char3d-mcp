"""Two short motion drafts, with reproducible timings, on isolated engine 9991."""
import json
from fractions import Fraction
import os
from pathlib import Path
import sys
import time

import av

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp_server.blender_client import BlenderClient  # noqa: E402
from motion_visuals import isolate  # noqa: E402

os.environ["CHAR3D_PORT"] = "9991"
os.environ["CHAR3D_ALLOW_PYTHON"] = "1"
os.environ["CHAR3D_WORKSPACE"] = str(ROOT/"output")
os.environ["CHAR3D_RENDER_CALIB"] = str(ROOT/"output"/"motion_render_speed.json")
os.environ.setdefault("OMP_NUM_THREADS", "4")


def main():
    client = BlenderClient()
    call = client.call
    report = {}
    def movie(path, end):
        # render_video starts a second Blender worker. For the shared-RAM
        # verification run, render in the one engine and encode with PyAV.
        call("run_python", code="bpy.context.scene.render.resolution_x=480\nbpy.context.scene.render.resolution_y=270\nresult=True")
        target = ROOT/"output"/"renders"/path
        target.parent.mkdir(parents=True, exist_ok=True)
        frames = list(range(1, end+1, 2))
        container = av.open(str(target), mode="w")
        stream = container.add_stream("libx264", rate=12)
        stream.width, stream.height, stream.pix_fmt = 480, 270, "yuv420p"
        stream.options = {"crf": "24", "preset": "fast"}
        try:
            for i in range(0, len(frames), 12):
                rendered = call("render_frames", frames=frames[i:i+12], camera="scene", size=480,
                                engine="workbench", prefix=f"{target.stem}_draft", subtitles=False)
                for index, item in enumerate(rendered["frames"], start=i):
                    with av.open(item["path"]) as source:
                        frame = next(source.decode(video=0))
                    frame.pts = index
                    frame.time_base = Fraction(1, 12)
                    for packet in stream.encode(frame):
                        container.mux(packet)
                print(f"RENDER {path}: {min(i+12, len(frames))}/{len(frames)}", flush=True)
            for packet in stream.encode():
                container.mux(packet)
        finally:
            container.close()
        return {"path": str(target), "fps": 12, "frames": len(frames)}
    try:
        print(call("scene_info"), flush=True)
        call("new_scene", frame_end=2)
        isolate(call)
        script = {"title": "Gerak dan cerita", "characters": [
            {"id": "Ana", "gender": 0, "age": 28, "hair": "bob01", "clothes": ["female_casualsuit01", "shoes01"]},
            {"id": "Budi", "gender": 1, "age": 32, "hair": "short02", "clothes": ["male_casualsuit01", "shoes01"]}],
            "beats": [{"say": "Ana", "text": "Aku sedih sekali.", "emotion": "sad"},
                      {"do": "gesture", "who": "Ana", "name": "cry", "speed": 1.5},
                      {"say": "Budi", "text": "Mari kita bergerak!", "emotion": "happy"},
                      {"do": "gesture", "who": "Budi", "name": "laugh", "speed": 1.5},
                      {"do": "gesture", "who": "Ana", "name": "dance_casual", "bpm": 100},
                      {"do": "gesture", "who": "Budi", "name": "drink", "speed": 1.5},
                      {"do": "gesture", "who": "Ana", "name": "kneel", "speed": 1.5}]}
        tick = time.perf_counter()
        scene = call("script_to_scene", script=script, camera="none", subtitles=False, sound=False)
        report["scene_build_s"] = round(time.perf_counter()-tick, 3)
        # Keep physical actions in a full two-shot throughout the draft.
        cast = [c["rig"] for c in scene["characters"].values()]
        call("camera_shot", name="MotionDemo", subject=cast, shot="full", angle=0,
             start_frame=1, end_frame=scene["frames"][1], avoid_occlusion=False)
        call("set_lighting", preset="studio", subject=cast)
        call("save_project", path="motion_scene.blend")
        call("export_asset", path="motion_scene.glb", max_influences=4)
        tick = time.perf_counter()
        result = movie("motion_scene_draft.mp4", scene["frames"][1])
        report["scene"] = dict(path=result["path"], render_s=round(time.perf_counter()-tick, 3),
                               frames=scene["frames"], duration_s=scene["duration_s"], warnings=scene["warnings"],
                               output_fps=result["fps"], output_frames=result["frames"])
        print("SCENE DRAFT", report["scene"], flush=True)

        call("new_scene", frame_end=2)
        isolate(call)
        rig = call("create_realistic_human", name="Dancer", gender=1, hair="short02",
                   clothes=["male_casualsuit01", "shoes01"])["armature"]
        first = call("animate", armature=rig, clip="dance_energetic", bpm=72, cycles=2)
        second = call("animate", armature=rig, clip="dance_energetic", bpm=132, cycles=2, start_frame=first["next_start_frame"])
        call("set_timeline", frame_start=1, frame_end=second["frames"][1], fps=24)
        call("camera_shot", name="DanceDemo", subject=[rig], shot="full", angle=15,
             start_frame=1, end_frame=second["frames"][1], avoid_occlusion=False)
        for motion, bpm in ((first, 72), (second, 132)):
            lo, hi = motion["frames"]
            call("add_title", text=f"{bpm} BPM", style="corner", start_s=(lo-1)/24,
                 duration_s=(hi-lo+1)/24, name=f"BPM{bpm}", size=.7)
        call("set_lighting", preset="studio", subject=[rig])
        call("save_project", path="motion_dance_bpms.blend")
        tick = time.perf_counter()
        result = movie("motion_dance_bpms.mp4", second["frames"][1])
        report["dance"] = dict(path=result["path"], render_s=round(time.perf_counter()-tick, 3),
                               frames=[1, second["frames"][1]], duration_s=second["frames"][1]/24,
                               bpms=[72, 132], cycle_frames=[first["cycle_frames"], second["cycle_frames"]],
                               output_fps=result["fps"], output_frames=result["frames"])
        print("DANCE DRAFT", report["dance"], flush=True)
        (ROOT/"output"/"motion_demo_times.json").write_text(json.dumps(report, indent=2))
    finally:
        client.stop()


if __name__ == "__main__":
    main()
