"""One engine command at a time, with background video/AI progress tracking."""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

from .security import redact

TERMINAL = {"completed", "failed", "cancelled"}
AI_GENERATORS = {"ai_text_to_3d", "ai_image_to_3d", "ai_image_to_video",
                 "ai_text_to_video", "ai_text_to_speech"}
INDEPENDENT = {"direct_scene", "direct_world", "director_status", "world_schema"}


@dataclass
class Job:
    tool: str
    arguments: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    status: str = "queued"
    result: dict | None = None
    error: str | None = None
    progress: dict | None = None


class JobQueue:
    def __init__(self, mcp, workspace):
        self.mcp, self.workspace = mcp, workspace
        self.jobs = {}
        self.queue = asyncio.Queue()
        self.lock = asyncio.Lock()
        self.current = None
        self.monitors = set()
        self.independent = set()

    def submit(self, tool, arguments):
        if self.queue.qsize() >= 50:
            raise ValueError("Antrean penuh. Tunggu pekerjaan selesai.")
        if tool in {"direct_scene", "direct_world"} and sum(j.tool in {"direct_scene", "direct_world"} and j.status not in TERMINAL for j in self.jobs.values()) >= 2:
            raise ValueError("Dua draf sutradara masih berjalan. Tunggu salah satunya selesai.")
        job = Job(tool=tool, arguments=arguments)
        self.jobs[job.id] = job
        if tool in INDEPENDENT:
            task = asyncio.create_task(self.run_independent(job))
            self.independent.add(task)
            task.add_done_callback(self.independent.discard)
        else:
            self.queue.put_nowait(job)
        done = [key for key, j in self.jobs.items() if j.status in TERMINAL]
        for key in done[:-100]:
            del self.jobs[key]
        return job

    def public(self, job):
        if job.tool == "script_to_film" and job.arguments.get("build", True) and job.status == "running":
            # Read engine-owned progress without waiting on its in-flight RPC/build.
            try:
                from engine.film_plan import parse_film
                import re
                plan = parse_film(job.arguments["script"], name=job.arguments.get("name"))
                slug = re.sub(r'[^\w.-]+', '_', plan['name'].strip())[:100]
                path = self.workspace.resolve(f"projects/{slug}/film.json")
                if path.stat().st_mtime >= job.started:
                    manifest = json.loads(path.read_text())
                    job.progress = {"scenes": [{k:s.get(k) for k in ("name", "index", "status")} for s in manifest["scenes"]]}
            except (ValueError, KeyError, OSError):
                pass
        waiting = [j.id for j in self.jobs.values() if j.status == "queued" and j.tool not in INDEPENDENT]
        now = job.finished or time.time()
        return redact({"id": job.id, "tool": job.tool, "status": job.status,
                       "created": job.created, "started": job.started,
                       "elapsed_s": round(now - (job.started or job.created), 1),
                       "queue_position": waiting.index(job.id) + 1 if job.id in waiting else 0,
                       "result": job.result, "error": job.error, "progress": job.progress})

    async def invoke(self, tool, arguments):
        if tool in INDEPENDENT:
            blocks = await self.mcp.call_tool(tool, arguments)
        else:
            async with self.lock:
                blocks = await self.mcp.call_tool(tool, arguments)
        # FastMCP versions may return (content, structured) for structured tools.
        if isinstance(blocks, tuple):
            blocks = blocks[0]
        if isinstance(blocks, dict):
            blocks = [blocks]
        data, texts = [], []
        for block in blocks:
            kind = getattr(block, "type", None)
            if kind == "text":
                try:
                    data.append(json.loads(block.text))
                except (ValueError, TypeError):
                    texts.append(block.text)
            elif isinstance(block, dict):
                data.append(block)
        # MCP Image blocks carry base64. Use workspace paths from companion JSON,
        # expose fetchable URLs without duplicating image payloads in every poll.
        images, files = [], []

        def scan(value):
            if isinstance(value, str):
                url = self.workspace.url(value)
                if not url and value.startswith("audio/tts/"):
                    url = self.workspace.url(self.workspace.resolve(value, "imports"))
                if url and url not in files:
                    files.append(url)
                    if value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        images.append(url)
            elif isinstance(value, dict):
                for item in value.values():
                    scan(item)
            elif isinstance(value, list):
                for item in value:
                    scan(item)
        for value in data:
            scan(value)
        value = data[0] if len(data) == 1 else data
        if not data and texts:
            value = texts[0] if len(texts) == 1 else texts
        return redact({"data": value,
                       "text": texts, "images": images, "files": files})

    async def run_independent(self, job):
        """Director network/text work never acquires the Blender queue or lock."""
        job.started, job.status = time.time(), "running"
        try:
            job.result = await self.invoke(job.tool, job.arguments)
            job.status = "completed"
        except Exception as exc:
            job.error, job.status = redact(str(exc)), "failed"
        finally:
            job.finished = time.time()

    async def worker(self):
        while True:
            job = await self.queue.get()
            self.current = job.id
            job.started, job.status = time.time(), "running"
            try:
                job.result = await self.invoke(job.tool, job.arguments)
                data = job.result["data"]
                background = data.get("job_id") if isinstance(data, dict) else None
                if background and (job.tool in {"render_video", "render_film"} or job.tool in AI_GENERATORS):
                    job.status = "rendering" if job.tool in {"render_video", "render_film"} else "processing"
                    task = asyncio.create_task(self.monitor(job, background))
                    self.monitors.add(task)
                    task.add_done_callback(self.monitors.discard)
                else:
                    job.status, job.finished = "completed", time.time()
                if job.tool == "cancel_render":
                    for other in self.jobs.values():
                        if (other.tool in {"render_video", "render_film"} and other.status == "rendering"
                                and other.result["data"].get("job_id") == job.arguments.get("job_id")):
                            other.status, other.finished = "cancelled", time.time()
            except Exception as exc:
                job.error, job.status, job.finished = redact(str(exc)), "failed", time.time()
            finally:
                self.current = None
                self.queue.task_done()

    async def monitor(self, job, background_id):
        status_tool = "render_status" if job.tool in {"render_video", "render_film"} else "ai_job_status"
        while True:
            await asyncio.sleep(1.5)
            if job.status in TERMINAL:
                return
            try:
                status = await self.invoke(status_tool, {"job_id": background_id})
                progress = status["data"]
                job.progress = progress
                state = progress.get("status", "")
                if state in {"done", "complete", "completed", "finished", "failed", "error", "cancelled", "canceled"}:
                    job.status = {"failed": "failed", "error": "failed", "cancelled": "cancelled", "canceled": "cancelled"}.get(state, "completed")
                    job.finished, job.result = time.time(), status
                    if job.status == "failed":
                        job.error = redact(str(progress.get("error") or progress.get("log") or "Pekerjaan gagal"))
                    return
            except Exception as exc:
                job.error, job.status, job.finished = redact(str(exc)), "failed", time.time()
                return
