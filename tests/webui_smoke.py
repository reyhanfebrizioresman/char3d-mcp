"""Real local UI / MCP smoke. Run on an isolated CHAR3D_PORT (never 9876).

CHAR3D_PORT=9981 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python tests/webui_smoke.py
The test starts its own UI subprocess, reusing the configured engine if available.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui-port", type=int, default=8781)
    args = parser.parse_args()
    port = os.environ.get("CHAR3D_PORT")
    if not port or port == "9876":
        parser.error("Set CHAR3D_PORT to an isolated engine port, e.g. 9981")
    base = f"http://127.0.0.1:{args.ui_port}"
    workspace = Path(os.environ.get("CHAR3D_WORKSPACE", ROOT / "output")).resolve()
    env = dict(os.environ, CHAR3D_ALLOW_PYTHON="1", FAL_KEY="webui-secret-fal-sentinel",
               HF_TOKEN="webui-secret-hf-sentinel")
    server = subprocess.Popen([sys.executable, "-m", "webui", "--port", str(args.ui_port)],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    def http(path, data=None, headers=None, method=None, binary=False):
        body = json.dumps(data).encode() if data is not None else None
        req = Request(base + path, data=body,
                      headers={"Content-Type": "application/json", **(headers or {})}, method=method)
        with urlopen(req, timeout=20) as response:
            raw = response.read()
            assert b"webui-secret-fal-sentinel" not in raw
            assert b"webui-secret-hf-sentinel" not in raw
            return raw if binary else json.loads(raw)

    def reject(path, status, **kwargs):
        try:
            http(path, **kwargs)
        except HTTPError as exc:
            assert exc.code == status, (path, exc.code, status)
        else:
            raise AssertionError(f"{path} must reject the request")

    def tool(name, arguments=None):
        ident = http("/api/run", {"tool": name, "arguments": arguments or {}})["job_id"]
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            job = http("/api/jobs/" + ident)
            if job["status"] == "completed":
                return job["result"]
            assert job["status"] != "failed", job
            time.sleep(.2)
        raise AssertionError(f"Timed out: {name}")

    link = workspace / "renders" / "webui_escape.png"
    outside = ROOT / "README.md"
    try:
        for _ in range(150):
            if server.poll() is not None:
                raise AssertionError("UI server exited; ensure the UI port is free")
            try:
                catalog = http("/api/tools")["tools"]
                break
            except (URLError, OSError):
                time.sleep(.1)
        else:
            raise AssertionError("UI server did not start")
        names = {tool["name"] for tool in catalog}
        assert "script_to_scene" in names and "run_blender_python" not in names
        assert http("/api/tools/create_human")["inputSchema"]["properties"]["style"]["enum"]
        print("PASS tool catalog + JSON schema; Python hidden even when enabled", flush=True)
        reject("/api/run", 403, data={"tool": "new_scene"}, headers={"Origin": "https://evil.example"})
        reject("/api/run", 403, data={"tool": "new_scene"}, headers={"Host": "rebind.example:8781"})
        reject("/api/run", 403, data={"tool": "new_scene"}, headers={"Origin": "null"})
        reject("/api/tools", 403, headers={"Host": "rebind.example:8781"})
        reject("/api/run", 404, data={"tool": "run_blender_python", "arguments": {"code": "result=1"}})
        for name in ("ai_text_to_3d", "ai_image_to_3d", "ai_text_to_video", "ai_image_to_video", "ai_text_to_speech"):
            reject("/api/run", 403, data={"tool": name})
        reject("/api/run", 403, data={"tool": "ai_text_to_video", "confirm_external": "true"})
        reject("/api/run", 400, data={"tool": "open_project", "arguments": {"path": "/etc/passwd"}})
        print("PASS local Origin/Host; AI consent; Python invocation blocked", flush=True)
        tool("scene_info")
        tool("new_scene", {"frame_end": 24})
        human = tool("create_human", {"name": "WebUISmoke", "style": "stylized"})["data"]
        assert human["name"] == "WebUISmoke", human
        preview = tool("render_preview", {"width": 256, "height": 256, "engine_name": "workbench"})
        assert preview["images"], preview
        image = http(preview["images"][0], binary=True)
        assert image.startswith(b"\x89PNG"), image[:30]
        assert any(file["extension"] == ".png" for file in http("/api/gallery")["files"])
        assert http("/api/jobs")["jobs"]
        print("PASS scene_info → new_scene → create_human → render_preview; image fetch + gallery", flush=True)
        reject("/api/files/%2e%2e/README.md", 403)
        reject("/api/files/%2fetc%2fpasswd", 403)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to(outside)
        reject("/api/files/renders/webui_escape.png", 403)
        assert not any(file["name"] == link.name for file in http("/api/gallery")["files"])
        reject("/api/upload?kind=images", 400, method="POST", headers={"X-Filename": "x.html"})
        # Raw upload with a hostile filename must still land inside imports/audio.
        req = Request(base + "/api/upload?kind=audio", b"RIFFtest", headers={"X-Filename": "../../recording.wav"}, method="POST")
        with urlopen(req) as response:
            uploaded = json.load(response)
        assert uploaded["path"].startswith("audio/") and ".." not in uploaded["path"]
        (workspace / "imports" / uploaded["path"]).unlink()
        print("PASS traversal + symlink escape rejected; sanitized upload", flush=True)
        # A validation error echoes the sentinel; both the error and all history
        # must be redacted without configuring or contacting an external provider.
        bad = http("/api/run", {"tool": "create_human", "arguments": {"height": "webui-secret-fal-sentinel"}})["job_id"]
        for _ in range(100):
            if http("/api/jobs/" + bad)["status"] == "failed":
                break
            time.sleep(.05)
        raw = http("/api/jobs", binary=True)
        assert b"webui-secret-fal-sentinel" not in raw
        print("PASS secret redaction in errors + job history", flush=True)
        assert tool("engine_shutdown")["data"] == "stopped"
        print("PASS plain-text tool result + owned engine shutdown", flush=True)
        print("WEBUI SMOKE OK", flush=True)
    finally:
        link.unlink(missing_ok=True)
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    main()
