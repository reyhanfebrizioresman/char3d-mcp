"""Reproducible motion sheets, using the engine RPC commands on isolated port 9991.

CHAR3D_PORT=9991 .venv/bin/python tests/motion_visuals.py --clips cry drink kneel
No asset downloads. One engine; always stop the process this script starts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import textwrap
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.motion_library import MOTIONS  # noqa: E402
from mcp_server.blender_client import BlenderClient  # noqa: E402

os.environ["CHAR3D_PORT"] = "9991"
os.environ["CHAR3D_ALLOW_PYTHON"] = "1"
os.environ["CHAR3D_WORKSPACE"] = str(ROOT/"output")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("LP_NUM_THREADS", "4")
os.environ.setdefault("MALLOC_ARENA_MAX", "2")


def isolate(call):
    call("run_python", code=textwrap.dedent(f"""
        import addon_utils, importlib, os, shutil
        module='bl_ext.user_default.mpfb'
        source=os.path.join(bpy.utils.extension_path_user(module),'data')
        home={str(ROOT/'output'/'mpfb_motion')!r}
        os.makedirs(home,exist_ok=True)
        data=os.path.join(home,'data')
        if os.path.isdir(source) and not os.path.isdir(data): shutil.copytree(source,data)
        cls=importlib.import_module(module+'._preferences').MpfbPreferences
        if 'bl_rna' not in cls.__dict__: bpy.utils.register_class(cls)
        addon=bpy.context.preferences.addons.get(module)
        if addon is None:
            addon=bpy.context.preferences.addons.new()
            addon.module=module
        addon.preferences.mpfb_user_data=home
        bpy.context.scene.render.threads_mode='FIXED'
        bpy.context.scene.render.threads=4
        result=True
    """))


def contact_sheet(paths, path, title, size=256):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        # The shared venv is immutable; use the host's existing Pillow installation.
        import inspect
        import subprocess
        source = "import json,sys\n"+inspect.getsource(contact_sheet)+"\ncontact_sheet(*json.loads(sys.argv[1]))"
        subprocess.run(["/usr/bin/python3", "-c", source, json.dumps([paths, str(path), title, size])], check=True)
        return
    sheet = Image.new("RGB", (size*5, (size+24)*3+36), (35, 38, 44))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), title, fill="white")
    for i, item in enumerate(paths):
        img = Image.open(item["path"]).convert("RGB")
        img.thumbnail((size, size))
        x, y = (i%5)*size, 36+(i//5)*(size+24)
        sheet.paste(img, (x, y))
        draw.text((x+5, y+size+3), f"{item['view']}  f{item['frame']}", fill="white")
    sheet.save(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", nargs="*", default=list(MOTIONS))
    parser.add_argument("--genders", nargs="*", default=["female", "male"])
    parser.add_argument("--eevee", action="store_true")
    parser.add_argument("--eevee-size", type=int, default=320, choices=(256, 320, 512))
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--family", choices=["game_engine", "rigify", "basic", "mannequin_rigify"], default="game_engine")
    parser.add_argument("--load-base", action="store_true")
    parser.add_argument("--hand", choices=["left", "right"], default="right")
    args = parser.parse_args()
    out = ROOT/"output"/"motion_sheets"
    out.mkdir(parents=True, exist_ok=True)
    client = BlenderClient()
    call = client.call
    manifest_path = out/"manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    source_hash = hashlib.sha256(b"".join((ROOT/p).read_bytes() for p in
        ("engine/motion_library.py", "engine/commands/motion.py", "engine/commands/anim.py"))).hexdigest()
    try:
        print(call("scene_info"), flush=True)
        for gender in args.genders:
            call("new_scene", frame_end=2)
            isolate(call)
            sex = 0 if gender == "female" else 1
            label = gender if args.family == "game_engine" else f"{args.family}_{gender}"
            base = ROOT/"output"/"projects"/f"motion_{label}_base.blend"
            if args.hand == "left":
                label += "_left"
            if args.load_base and base.exists():
                call("open_project", path=str(base))
                rig = "Motion_rig"
            elif args.family in ("basic", "mannequin_rigify"):
                call("create_human", name="Motion", gender=gender, style="realistic")
                rig = call("auto_rig_humanoid", mesh="Motion", rig_type="basic" if args.family == "basic" else "rigify")["armature"]
            else:
                built = call("create_realistic_human", name="Motion", gender=sex, age=28, rig=args.family,
                             hair="bob01" if sex == 0 else "short02", clothes=[f"{gender}_casualsuit01", "shoes01"])
                rig = built["armature"]
            print(f"BUILT {gender}: {rig}", flush=True)
            if not (args.load_base and base.exists()):
                call("save_project", path=str(base))
            for clip in args.clips:
                if args.reuse and manifest.get(f"{label}/{clip}", {}).get("source_hash") == source_hash:
                    continue
                call("scene_info")
                call("clear_animation", armature=rig)
                call("clear_environment")
                call("set_timeline", frame_start=1, frame_end=2, fps=24)
                subjects = [rig]
                if clip == "type":
                    seat = call("add_prop", kind="chair")["root"]
                    call("sit_on", character=rig, seat=seat, start_frame=1)
                    call("add_prop", kind="desk", location=[0, -.60, 0], rotation_z=180, scale=.75/1.02)
                    call("add_prop", kind="laptop", location=[0, -.45, .758], rotation_z=180)
                    subjects.extend(o["name"] for o in call("scene_info")["objects"] if o["type"] == "EMPTY" and "c3d" not in o["name"])
                for kind in MOTIONS[clip]["required_props"]:
                    prop = call("add_prop", kind=kind)["root"]
                    call("hold_prop", character=rig, prop=prop, start_frame=1, hand=args.hand)
                    subjects.append(prop)
                tick = time.perf_counter()
                result = call("animate", armature=rig, clip=clip, cycles=1, start_frame=25 if clip == "type" else 1,
                              blend_frames=0, **({"bpm": 90} if clip.startswith("dance_") else {}))
                duration = time.perf_counter()-tick
                print(f"BAKED {gender}/{clip}: {duration:.2f}s {result}", flush=True)
                lo, hi = result["frames"]
                fractions = (0, .22, .45, .68, 1.)
                if clip == "clap":
                    fractions = (0, .10, 1/6, .5, 1.)
                frames = [lo+round((hi-lo)*t) for t in fractions]
                images = []
                for view in ("front", "right", "three_quarter"):
                    rendered = call("render_frames", frames=frames, view=view, size=256, objects=subjects,
                                    prefix=f"motion_{label}_{clip}_{view}")
                    for f, item in zip(frames, rendered["frames"]):
                        images.append(dict(item, view=view, frame=f))
                path = out/f"{label}_{clip}.jpg"
                contact_sheet(images, path, f"{label} / {clip} / {lo}..{hi}")
                manifest[f"{label}/{clip}"] = dict(sheet=str(path), frames=frames, bake_seconds=round(duration, 3), result=result,
                                                  source_hash=source_hash)
                if args.eevee and MOTIONS[clip]["category"] in ("body_language", "reaction"):
                    call("set_lighting", preset="studio", subject=[rig])
                    call("camera_shot", subject=[rig], shot="medium", angle=15,
                         elevation=-12 if clip in ("sad", "tired", "shy", "cry", "thinking", "facepalm") else 5,
                         start_frame=frames[2], end_frame=frames[2]+1, name="Emotion")
                    expression = {"happy": "smile", "excited": "big_smile", "nervous": "fear", "tired": "sleepy", "cry": "sad", "startle": "surprised"}.get(clip, clip)
                    if expression not in ("sad", "angry", "smile", "big_smile", "fear", "sleepy", "laugh", "surprised", "thinking"):
                        expression = "neutral"
                    call("set_expression", character=rig, expression=expression, strength=.55, frame=frames[2], keyframe=True)
                    item = call("render_frames", frames=[frames[2]], camera="scene", engine="eevee", size=args.eevee_size,
                                prefix=f"motion_{label}_{clip}_eevee")["frames"][0]
                    target = out/f"{label}_{clip}_eevee.png"
                    shutil.copyfile(item["path"], target)
                    manifest[f"{label}/{clip}"]["eevee"] = str(target)
                manifest_path.write_text(json.dumps(manifest, indent=2))
                print(f"SHEET {gender}/{clip}: {path} bake={duration:.2f}s", flush=True)
    finally:
        client.stop()


if __name__ == "__main__":
    main()
