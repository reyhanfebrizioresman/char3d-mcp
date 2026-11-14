"""Minimal fal.ai queue client (stdlib only).

Queue protocol: POST {base}/{model_id} -> {request_id, status_url, response_url,
cancel_url}; poll status_url until status == "COMPLETED"; GET response_url for output.
Auth header: "Authorization: Key $FAL_KEY". The key is read from the environment only
and never written to disk or logs.

CHAR3D_FAL_BASE overrides the endpoint (used by the local mock server in tests).
"""
import base64
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://queue.fal.run"
USER_AGENT = "char3d/0.6"


class ProviderError(RuntimeError):
    pass


class FalClient:
    name = "fal"

    def __init__(self):
        self.base = (os.environ.get("CHAR3D_FAL_BASE") or DEFAULT_BASE).rstrip("/")

    @property
    def key(self):
        return os.environ.get("FAL_KEY")

    @property
    def configured(self):
        return bool(self.key)

    def _request(self, method, url, body=None, timeout=60):
        if not self.key:
            raise ProviderError("FAL_KEY is not set. Add it to the MCP server's environment "
                                "(see README: 'AI providers').")
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            raise ProviderError(f"refusing non-http URL: {url}")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Key {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:600].decode(errors="replace")
            raise ProviderError(f"fal HTTP {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"cannot reach fal ({self.base}): {exc.reason}") from None
        return json.loads(raw) if raw else {}

    def submit(self, model, payload):
        sub = self._request("POST", f"{self.base}/{model.strip('/')}", payload)
        if "status_url" not in sub or "response_url" not in sub:
            raise ProviderError(f"unexpected submit response: {str(sub)[:300]}")
        return sub

    def status(self, sub):
        return self._request("GET", sub["status_url"])

    def result(self, sub):
        return self._request("GET", sub["response_url"])

    def cancel(self, sub):
        if sub.get("cancel_url"):
            try:
                self._request("PUT", sub["cancel_url"])
            except ProviderError:
                pass


def data_uri(path, max_bytes=20 * 1024 * 1024):
    """Inline a local file (image) as a data: URI for model inputs."""
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ProviderError(f"{path} is {size} bytes; inline limit is {max_bytes}")
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"


def find_urls(obj, exts):
    """All http(s) URLs in a nested JSON result whose path ends with one of exts."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.startswith(("http://", "https://")):
            path = urllib.parse.urlparse(o).path.lower()
            if any(path.endswith(e) for e in exts):
                found.append(o)
    walk(obj)
    return found


def download(url, dest, max_bytes=1024 * 1024 * 1024, timeout=300):
    """Stream a provider output file to dest (http/https only, size-capped)."""
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ProviderError(f"refusing to download non-http URL: {url}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total = 0
    tmp = dest + ".part"
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"download failed (HTTP {exc.code}): {url.split('?')[0]}") from None
    except urllib.error.URLError as exc:
        raise ProviderError(f"download failed ({exc.reason}): {url.split('?')[0]}") from None
    with resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                out.close()
                os.remove(tmp)
                raise ProviderError(f"download exceeds {max_bytes} bytes: {url}")
            out.write(chunk)
    os.replace(tmp, dest)
    return total
