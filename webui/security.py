"""Local origin checks, workspace confinement and response redaction."""
import os
import re
from pathlib import Path
from urllib.parse import quote

from starlette.responses import JSONResponse


def redact(value):
    """Redact configured secrets even when a provider includes one in an error."""
    if isinstance(value, str):
        for key in ("FAL_KEY", "HF_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            secret = os.environ.get(key)
            if secret:
                value = value.replace(secret, "[RAHASIA]")
        return re.sub(r"(?i)(FAL_KEY|HF_TOKEN|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN)(\s*[=:]\s*)[^\s,;\"']+", r"\1\2[RAHASIA]", value)
    if isinstance(value, dict):
        return {k: "[RAHASIA]" if k.upper() in {"FAL_KEY", "HF_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"} else redact(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def resolve(self, path, base=""):
        raw = Path(path)
        if ".." in raw.parts or "\x00" in str(path):
            raise ValueError("Path tidak diizinkan")
        target = (raw if raw.is_absolute() else self.root / base / raw).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("File harus berada di workspace")
        return target

    def url(self, path):
        try:
            target = self.resolve(path)
            if target.is_file():
                return "/api/files/" + quote(target.relative_to(self.root).as_posix(), safe="/")
        except (ValueError, OSError):
            pass
        return None

    def validate_arguments(self, tool, arguments):
        """Tool file inputs/outputs also stay local to the workspace in the browser UI."""
        base = {"save_project": "projects", "open_project": "projects",
                "export_asset": "exports"}.get(tool, "imports")
        if tool in {"render_video", "render_film", "review_video", "ai_text_to_video", "ai_image_to_video"}:
            base = "renders"

        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"path", "audio", "image", "screen_image", "font", "voice_reference", "output"} and isinstance(item, str):
                        if item.startswith("https://") and key == "image" and tool.startswith("ai_"):
                            continue
                        self.resolve(item, base if key in {"path", "output"} else "imports")
                    else:
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(arguments)


class LocalOnlyMiddleware:
    def __init__(self, app, port):
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{host}" for host in self.hosts}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        host, origin = headers.get("host", ""), headers.get("origin")
        if host not in self.hosts or (origin and origin not in self.origins) or (
                scope["method"] not in {"GET", "HEAD", "OPTIONS"}
                and headers.get("sec-fetch-site") == "cross-site"):
            return await JSONResponse({"error": "Permintaan harus berasal dari studio lokal"}, 403)(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cross-origin-resource-policy", b"same-origin"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self' blob: data:; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
                ]
            await send(message)
        await self.app(scope, receive, secure_send)
