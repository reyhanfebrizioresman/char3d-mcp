"""Minimal JSON-lines RPC loop running on Blender's main thread.

Protocol (one JSON object per line, one request per connection is fine):
    -> {"id": 1, "cmd": "scene_info", "params": {}}
    <- {"id": 1, "ok": true, "result": {...}}
    <- {"id": 1, "ok": false, "error": "...", "traceback": "..."}
"""
import json
import socket
import traceback

from . import context
from .commands import dispatch


def _handle(req):
    rid = req.get("id")
    try:
        result = dispatch(req["cmd"], req.get("params") or {})
        return {"id": rid, "ok": True, "result": result}
    except Exception as exc:  # report every engine error back to the caller
        return {
            "id": rid,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def serve(host, port, workspace):
    context.init(workspace)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    srv.settimeout(0.5)
    print(f"CHAR3D_READY {host}:{port} workspace={workspace}", flush=True)

    running = True
    while running:
        from .commands.film import tick
        tick()
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        with conn:
            stream = conn.makefile("rwb")
            for raw in stream:
                if not raw.strip():
                    continue
                try:
                    req = json.loads(raw)
                except json.JSONDecodeError as exc:
                    resp = {"id": None, "ok": False, "error": f"bad json: {exc}"}
                else:
                    if req.get("cmd") == "shutdown":
                        from .commands.film import shutdown
                        shutdown()
                        resp = {"id": req.get("id"), "ok": True, "result": "bye"}
                        running = False
                    else:
                        resp = _handle(req)
                stream.write((json.dumps(resp) + "\n").encode())
                stream.flush()
                if not running:
                    break
    srv.close()
