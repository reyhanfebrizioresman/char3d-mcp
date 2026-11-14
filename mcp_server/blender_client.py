"""Starts (if needed) and talks to the Blender engine process over localhost TCP."""
import atexit
import json
import os
import shutil
import socket
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EngineError(RuntimeError):
    pass


def _find_blender():
    for cand in (os.environ.get("CHAR3D_BLENDER"),
                 os.path.expanduser("~/.local/opt/blender/blender"),
                 shutil.which("blender")):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    raise EngineError("Blender not found. Set CHAR3D_BLENDER=/path/to/blender.")


class BlenderClient:
    def __init__(self):
        self.host = "127.0.0.1"
        self.port = int(os.environ.get("CHAR3D_PORT", "9876"))
        self.workspace = os.path.abspath(
            os.path.expanduser(os.environ.get("CHAR3D_WORKSPACE", os.path.join(ROOT, "output"))))
        self.log_path = os.path.join(self.workspace, "logs", "blender.log")
        self.proc = None
        self._lock = threading.Lock()
        self._id = 0
        atexit.register(self.stop)

    # -- low level ---------------------------------------------------------
    def _send(self, cmd, params, timeout):
        self._id += 1
        with socket.create_connection((self.host, self.port), timeout=timeout) as s:
            s.settimeout(timeout)
            stream = s.makefile("rwb")
            stream.write((json.dumps({"id": self._id, "cmd": cmd, "params": params}) + "\n").encode())
            stream.flush()
            line = stream.readline()
        if not line:
            raise EngineError("engine closed the connection (did Blender crash? see logs/blender.log)")
        return json.loads(line)

    def _alive(self):
        try:
            return self._send("ping", {}, timeout=2).get("ok", False)
        except OSError:
            return False

    def _log_tail(self, n=30):
        try:
            with open(self.log_path, errors="replace") as f:
                return "".join(f.readlines()[-n:])
        except OSError:
            return "(no log)"

    def _start(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        cmd = [_find_blender(), "-b", "--factory-startup",
               "--python", os.path.join(ROOT, "engine", "bootstrap.py"), "--",
               "--port", str(self.port), "--workspace", self.workspace]
        log = open(self.log_path, "ab")
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, cwd=ROOT)
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise EngineError(f"Blender exited early (code {self.proc.returncode}).\n{self._log_tail()}")
            if self._alive():
                return
            time.sleep(0.5)
        raise EngineError(f"Blender did not become ready in 120s.\n{self._log_tail()}")

    # -- public ------------------------------------------------------------
    def ensure(self):
        """Reuse a running engine on the port (shared by Claude/Codex), or start one."""
        if not self._alive():
            self._start()

    def call(self, cmd, timeout=1800, **params):
        with self._lock:
            self.ensure()
            resp = self._send(cmd, params, timeout)
        if not resp.get("ok"):
            tb = resp.get("traceback", "")
            tail = "\n".join(tb.strip().splitlines()[-6:]) if tb else ""
            raise EngineError(f"{resp.get('error')}\n{tail}".strip())
        return resp["result"]

    def stop(self):
        """Shut down the engine only if this process started it."""
        if self.proc and self.proc.poll() is None:
            try:
                self._send("shutdown", {}, timeout=5)
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
        self.proc = None
