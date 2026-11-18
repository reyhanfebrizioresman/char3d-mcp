"""Starlette adapter. All scene operations go through the existing FastMCP instance."""
import asyncio
import contextlib
import json
import mimetypes
import re
import uuid
from pathlib import Path
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from mcp_server.server import engine, mcp
from providers.tts import online_request
from providers.director import online_request as director_online

from .jobs import AI_GENERATORS, JobQueue
from .security import LocalOnlyMiddleware, Workspace, redact

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 100 * 1024 * 1024
UPLOAD_TYPES = {
    "audio": {".wav", ".mp3", ".flac", ".ogg", ".m4a"},
    "images": {".png", ".jpg", ".jpeg", ".webp"},
    "models": {".glb", ".gltf", ".fbx", ".obj", ".stl", ".ply", ".usd", ".usdz", ".bvh", ".bin"},
}
GALLERY_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".glb", ".gltf", ".blend", ".srt", ".fbx", ".obj", ".wav"}


def create_app(port=8765):
    workspace = Workspace(engine.workspace)
    jobs = JobQueue(mcp, workspace)
    catalog = {}

    @contextlib.asynccontextmanager
    async def lifespan(app):
        for tool in await mcp.list_tools():
            if tool.name != "run_blender_python":
                catalog[tool.name] = tool.model_dump(by_alias=True)
        worker = asyncio.create_task(jobs.worker())
        yield
        tasks = [worker, *jobs.monitors, *jobs.independent]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # BlenderClient owns its process lifecycle; no subprocess launch here.

    async def index(request):
        return FileResponse(STATIC / "index.html")

    async def tools(request):
        name = request.path_params.get("name")
        if name:
            if name not in catalog:
                raise HTTPException(404, "Tool tidak tersedia")
            return JSONResponse(redact(catalog[name]))
        return JSONResponse(redact({"tools": list(catalog.values())}))

    async def run(request):
        raw = await limited_body(request, 2 * 1024 * 1024)
        try:
            body = json.loads(raw)
            name = body.get("tool")
            arguments = body.get("arguments", {})
            if name not in catalog:
                raise HTTPException(404, "Tool tidak tersedia")
            if not isinstance(arguments, dict):
                raise ValueError("arguments harus berupa objek JSON")
            if (name in AI_GENERATORS or online_request(name, arguments) or
                    name == "direct_scene" and director_online(arguments)) and body.get("confirm_external") is not True:
                raise HTTPException(403, "Konfirmasi diperlukan: prompt/gambar/audio dikirim ke layanan AI pihak ketiga")
            workspace.validate_arguments(name, arguments)
            job = jobs.submit(name, arguments)
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(400, redact(str(exc))) from None
        return JSONResponse({"job_id": job.id}, 202)

    async def job_list(request):
        return JSONResponse({"jobs": [jobs.public(j) for j in reversed(list(jobs.jobs.values()))],
                             "current": jobs.current, "queued": jobs.queue.qsize()})

    async def job_detail(request):
        job = jobs.jobs.get(request.path_params["id"])
        if job is None:
            raise HTTPException(404, "Pekerjaan tidak ditemukan")
        return JSONResponse(jobs.public(job))

    async def gallery(request):
        entries = []
        for folder in ("renders", "exports", "projects", "imports/audio/tts"):
            directory = workspace.root / folder
            if not directory.exists():
                continue
            # Never follow symlink directories. Check file targets before stat/URL.
            for path in directory.rglob("*"):
                relative_parts = path.relative_to(directory).parts
                if "film_cache" in relative_parts or any(p.startswith(".") for p in relative_parts):
                    continue
                if path.suffix.lower() not in GALLERY_TYPES:
                    continue
                try:
                    safe = workspace.resolve(path)
                    if not safe.is_file():
                        continue
                    stat = safe.stat()
                    relative = path.relative_to(workspace.root).as_posix()
                    entries.append({"name": path.name, "path": relative, "folder": folder,
                                    "url": workspace.url(path), "size": stat.st_size,
                                    "modified": stat.st_mtime, "extension": path.suffix.lower()})
                except (OSError, ValueError):
                    continue
        entries.sort(key=lambda entry: entry["modified"], reverse=True)
        return JSONResponse({"files": entries[:1000], "limit": 1000})

    async def files(request):
        try:
            path = workspace.resolve(request.path_params["path"])
        except (ValueError, OSError):
            raise HTTPException(403, "Path tidak diizinkan") from None
        if not path.is_file():
            raise HTTPException(404, "File tidak ditemukan")
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        # Never execute HTML/SVG/JS uploaded or generated inside the workspace.
        inline = path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".wav", ".mp3", ".ogg", ".glb", ".gltf", ".bin"}
        download = request.query_params.get("download") == "1" or not inline
        return FileResponse(path, media_type=media, filename=path.name if download else None,
                            content_disposition_type="attachment")

    async def upload(request):
        kind = request.query_params.get("kind", "audio")
        filename = unquote(request.headers.get("x-filename", "upload"))
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename.replace("\\", "/").split("/")[-1])[:120]
        suffix = Path(filename).suffix.lower()
        if kind not in UPLOAD_TYPES or suffix not in UPLOAD_TYPES[kind]:
            raise HTTPException(400, "Jenis file tidak didukung")
        # Unique names prevent overwriting earlier imports. Raw streaming upload:
        # no multipart dependency, bounded memory and no user-controlled directory.
        target = workspace.resolve(f"{uuid.uuid4().hex[:12]}_{filename}", f"imports/{kind}")
        target.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        try:
            with target.open("xb") as stream:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > MAX_UPLOAD:
                        raise HTTPException(413, "Batas unggahan 100 MB")
                    stream.write(chunk)
            if not count:
                raise HTTPException(400, "File kosong")
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return JSONResponse({"path": target.relative_to(workspace.root / "imports").as_posix(),
                             "size": count}, 201)

    async def error(request, exc):
        return JSONResponse({"error": redact(str(exc.detail))}, exc.status_code)

    app = Starlette(lifespan=lifespan, routes=[
        Route("/", index), Route("/api/tools", tools), Route("/api/tools/{name}", tools),
        Route("/api/run", run, methods=["POST"]), Route("/api/jobs", job_list),
        Route("/api/jobs/{id}", job_detail), Route("/api/gallery", gallery),
        Route("/api/files/{path:path}", files), Route("/api/upload", upload, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ], exception_handlers={HTTPException: error})
    app.add_middleware(LocalOnlyMiddleware, port=port)
    app.state.jobs = jobs
    return app


async def limited_body(request, limit):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, "Permintaan terlalu besar")
        chunks.append(chunk)
    return b"".join(chunks)
