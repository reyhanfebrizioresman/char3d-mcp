"""Plan/build a real Indonesian scene and deliver a draft through a running UI."""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8781")
    parser.add_argument("--resume", action="store_true", help="Continue completed stages from this UI's history")
    parser.add_argument("--character-views", action="store_true", help="Also check all four Eevee character views")
    args = parser.parse_args()
    report = {}

    def http(path, body=None):
        request = Request(args.url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def tool(name, arguments=None, label=None):
        key = label or name
        if args.resume and key in report:
            print(f"PASS {key}: restored completed stage from UI history", flush=True)
            return report[key]
        started = time.monotonic()
        ident = http("/api/run", {"tool": name, "arguments": arguments or {}})["job_id"]
        last = 0
        while time.monotonic() - started < 1800:
            job = http("/api/jobs/" + ident)
            assert job["status"] not in {"failed", "cancelled"}, job
            if time.monotonic() - last > 25:
                print(name, job["status"], job["elapsed_s"], (job.get("progress") or {}).get("progress", ""), flush=True)
                last = time.monotonic()
            if job["status"] == "completed":
                result = job["result"]
                report[label or name] = result
                Path("output/webui_e2e.json").write_text(json.dumps(report, indent=2))
                print(f"PASS {label or name}: {time.monotonic() - started:.1f}s", flush=True)
                return result
            time.sleep(.5)
        raise AssertionError(f"timeout {name}")

    if args.resume:
        counts = {}
        for job in reversed(http('/api/jobs')['jobs']):
            if job['status'] != 'completed':
                continue
            name, result = job['tool'], job['result']
            if name == 'script_to_scene':
                report['build' if result['data'].get('characters') else 'plan'] = result
            elif name == 'render_frames':
                key = 'workbench' if not counts.get(name) else 'eevee'
                report[key] = result
                counts[name] = counts.get(name, 0) + 1
            elif name in {'save_project', 'scene_info', 'export_asset', 'render_video'}:
                report[name] = result
            elif name == 'render_views':
                report['character_views'] = result
    tool("scene_info")
    if not args.resume:
        tool("new_scene", {"frame_end": 48})
    script = "JUDUL: Sebuah Awal\nLOKASI: park\nANA (perempuan, 28, rambut bob): Halo!\nBUDI (laki-laki, 30, rambut pendek): Pagi, Ana."
    plan = tool("script_to_scene", {"script": script, "language": "id", "build": False}, "plan")
    assert len(plan["data"]["plan"]["characters"]) == 2
    built = tool("script_to_scene", {"script": script, "language": "id", "build": True, "seed": 7}, "build")
    assert len(built["data"]["characters"]) == 2 and built["data"]["shots"]
    frame = built["data"]["shots"][0]["frames"][0] + 3
    tool("render_frames", {"frames": [frame], "camera": "scene", "size": 512, "engine_name": "workbench"}, "workbench")
    still = tool("render_frames", {"frames": [frame], "camera": "scene", "size": 512, "engine_name": "eevee"}, "eevee")
    assert still["images"]
    # Save a milestone and a portable model to exercise all gallery types.
    tool("save_project", {"path": "webui-sebuah-awal.blend"})
    info = tool("scene_info")["data"]
    rig = next(obj["name"] for obj in info["objects"] if obj["type"] == "ARMATURE")
    if args.character_views or 'character_views' in report:
        tool("render_views", {"objects": [rig], "engine_name": "eevee", "size": 256}, "character_views")
    tool("export_asset", {"path": "webui-karakter.glb", "objects": [rig], "max_influences": 4})
    tool("render_options", {"quality": "draft", "frame_start": 1, "frame_end": 12})
    video = tool("render_video", {"path": "webui-sebuah-awal-draft.mp4", "quality": "draft", "resolution": "480p", "frame_start": 1, "frame_end": 12})
    assert video["data"]["status"] == "done"
    files = http("/api/gallery")["files"]
    assert any(f["name"] == "webui-sebuah-awal-draft.mp4" for f in files)
    for url in [still["images"][0], *video["files"]]:
        with urlopen(args.url + url, timeout=20) as response:
            assert response.status == 200 and response.read(16)
    report["gallery"] = files
    Path("output/webui_e2e.json").write_text(json.dumps(report, indent=2))
    print("WEBUI E2E OK — plan, build, Eevee, save, GLB, draft MP4 + gallery", flush=True)


if __name__ == "__main__":
    main()
