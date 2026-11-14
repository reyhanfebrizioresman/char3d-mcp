"""Local stand-in for the fal.ai queue API, for offline tests.

Implements: POST /<model id> -> {request_id, status_url, response_url, cancel_url};
GET status (IN_QUEUE -> IN_PROGRESS -> COMPLETED); GET result; PUT cancel; GET /files/*.
Outputs are chosen from the model id: "flux"/"image" -> PNG, "3d"/"trellis" -> GLB,
"video" -> MP4. Every request is recorded (path, auth header, JSON body) for assertions.
"""
import json
import os
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockFal:
    def __init__(self, files_dir, key="test-key"):
        self.files_dir = files_dir
        self.key = key
        self.calls = []
        self.requests = {}
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, raw=None, ctype="application/json"):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self):
                ok = self.headers.get("Authorization") == f"Key {mock.key}"
                if not ok:
                    self._send(401, {"detail": "bad key"})
                return ok

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                mock.calls.append(("POST", self.path, self.headers.get("Authorization"), body))
                if not self._authed():
                    return
                rid = uuid.uuid4().hex[:10]
                mock.requests[rid] = {"model": self.path.strip("/"), "polls": 0, "input": body}
                base = f"http://127.0.0.1:{mock.port}/requests/{rid}"
                self._send(200, {"request_id": rid, "status_url": base + "/status",
                                 "response_url": base, "cancel_url": base + "/cancel"})

            def do_PUT(self):
                mock.calls.append(("PUT", self.path, self.headers.get("Authorization"), None))
                self._send(200, {"status": "CANCELLATION_REQUESTED"})

            def do_GET(self):
                mock.calls.append(("GET", self.path, self.headers.get("Authorization"), None))
                clean = urllib.parse.urlparse(self.path).path
                parts = clean.strip("/").split("/")
                if parts[0] == "files":
                    path = os.path.join(mock.files_dir, os.path.basename(clean))
                    if not os.path.isfile(path):
                        return self._send(404, {"detail": "no file"})
                    with open(path, "rb") as f:
                        return self._send(200, raw=f.read(), ctype="application/octet-stream")
                if not self._authed():
                    return
                if parts[0] != "requests" or parts[1] not in mock.requests:
                    return self._send(404, {"detail": "unknown request"})
                req = mock.requests[parts[1]]
                if len(parts) == 3 and parts[2] == "status":
                    req["polls"] += 1
                    state = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"][min(req["polls"] - 1, 2)]
                    out = {"status": state}
                    if state == "IN_QUEUE":
                        out["queue_position"] = 1
                    return self._send(200, out)
                files = f"http://127.0.0.1:{mock.port}/files"
                m = req["model"]
                if "video" in m:
                    return self._send(200, {"video": {"url": f"{files}/clip.mp4"}})
                if "3d" in m or "trellis" in m:
                    return self._send(200, {"model_mesh": {"url": f"{files}/model.glb?sig=abc",
                                                           "content_type": "model/gltf-binary"}})
                return self._send(200, {"images": [{"url": f"{files}/concept.png",
                                                    "width": 1024, "height": 1024}],
                                        "seed": 42})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.shutdown()
