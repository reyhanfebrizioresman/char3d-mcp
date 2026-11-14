"""Background AI jobs: call provider models, download outputs, bring results into Blender.

Providers:
  fal - fal.ai queue API, paid per use, needs FAL_KEY.
  hf  - public Hugging Face Spaces, free (queues/quotas), optional HF_TOKEN.
provider="auto" uses fal when FAL_KEY is set, otherwise the free hf Spaces.

Each job runs in its own thread inside the MCP server process. Blender work goes through
the shared BlenderClient (thread-safe), so the engine and AI calls never block each other.
"""
import os
import threading
import time
import traceback
import uuid

from . import hf as hfmod
from . import models
from .fal import FalClient, ProviderError, data_uri, download, find_urls
from .hf import HFClient

POLL_S = float(os.environ.get("CHAR3D_POLL_SECONDS", "3"))
TIMEOUT_S = float(os.environ.get("CHAR3D_AI_TIMEOUT", "1800"))
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
MESH_EXTS = (".glb", ".gltf", ".fbx", ".obj")
VIDEO_EXTS = (".mp4", ".webm", ".mov")


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, kind, provider, params):
        self.id = f"ai_{uuid.uuid4().hex[:8]}"
        self.kind = kind
        self.provider = provider
        self.params = params
        self.status = "queued"
        self.stage = "queued"
        self.log = []
        self.result = {}
        self.error = None
        self.created = time.time()
        self.finished = None
        self.cancel_requested = False
        self.submissions = []   # fal requests
        self.handles = []       # gradio jobs

    def note(self, msg):
        self.stage = msg
        self.log.append(f"{time.strftime('%H:%M:%S')} {msg}")

    def report(self):
        out = {"job_id": self.id, "kind": self.kind, "provider": self.provider,
               "status": self.status, "stage": self.stage,
               "elapsed_s": round((self.finished or time.time()) - self.created, 1),
               "log": self.log[-12:]}
        if self.result:
            out["result"] = self.result
        if self.error:
            out["error"] = self.error
        return out


class JobManager:
    def __init__(self, engine):
        self.engine = engine
        self.fal = FalClient()
        self.hf = HFClient()
        self.jobs = {}

    # ------------------------------------------------------------------ status
    def status(self):
        return {
            "default_provider": self._pick("auto"),
            "fal": {"paid": True, "configured": self.fal.configured, "endpoint": self.fal.base,
                    "models": {k: models.model_for(k) for k in models.DEFAULTS}},
            "hf": {"paid": False, "available": self.hf.available,
                   "hf_token_set": self.hf.token_set,
                   "models": {t: {"default": hfmod.recipe_for(t)[0],
                                  "choices": {n: r["space"] for n, r in hfmod.RECIPES[t].items()}}
                              for t in hfmod.RECIPES},
                   "note": "Free public Spaces: may queue, hit daily GPU quota, or be offline."},
        }

    def _pick(self, provider):
        if provider in (None, "auto"):
            return "fal" if self.fal.configured else ("hf" if self.hf.available else None)
        if provider not in ("fal", "hf"):
            raise ProviderError("provider must be 'auto', 'fal' or 'hf'")
        return provider

    # ------------------------------------------------------------------ plumbing
    def _start(self, kind, provider, params, pipeline):
        prov = self._pick(provider)
        if prov == "fal" and not self.fal.configured:
            raise ProviderError("FAL_KEY is not set; use provider='hf' (free) or ask the user to "
                                "configure fal.ai (README: 'AI providers').")
        if prov == "hf" and not self.hf.available:
            raise ProviderError("gradio_client is not installed (pip install -r requirements.txt).")
        if prov is None:
            raise ProviderError("no AI provider available.")
        job = Job(kind, prov, params)
        self.jobs[job.id] = job

        def runner():
            job.status = "running"
            try:
                pipeline(job)
                job.status = "done"
                job.note("done")
            except (Cancelled, InterruptedError):
                job.status = "cancelled"
                job.note("cancelled")
            except Exception as exc:  # surface every failure to the agent
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.log.append(traceback.format_exc(limit=3))
            finally:
                job.finished = time.time()

        threading.Thread(target=runner, name=job.id, daemon=True).start()
        return job.report()

    def get(self, job_id=None):
        if job_id:
            if job_id not in self.jobs:
                raise KeyError(f"unknown AI job {job_id}. Known: {list(self.jobs)}")
            return self.jobs[job_id].report()
        return {"jobs": [j.report() for j in self.jobs.values()]}

    def cancel(self, job_id):
        job = self.jobs[job_id]
        job.cancel_requested = True
        for sub in job.submissions:
            self.fal.cancel(sub)
        for h in job.handles:
            try:
                h.cancel()
            except Exception:
                pass
        return job.report()

    def _dirs(self):
        ws = self.engine.workspace
        return os.path.join(ws, "imports", "ai"), os.path.join(ws, "renders")

    # ------------------------------------------------------------------ fal helpers
    def _fal_run(self, job, model, payload, label):
        job.note(f"{label}: submitting to fal {model}")
        sub = self.fal.submit(model, payload)
        job.submissions.append(sub)
        start = time.time()
        while True:
            if job.cancel_requested:
                self.fal.cancel(sub)
                raise Cancelled()
            st = self.fal.status(sub)
            state = st.get("status", "UNKNOWN")
            if state == "COMPLETED":
                break
            if state in ("FAILED", "ERROR", "CANCELLED"):
                raise ProviderError(f"{label} failed on provider: {st}")
            pos = st.get("queue_position")
            job.stage = f"{label}: {state.lower()}" + (f" (queue {pos})" if pos is not None else "")
            if time.time() - start > TIMEOUT_S:
                self.fal.cancel(sub)
                raise ProviderError(f"{label} timed out after {TIMEOUT_S:.0f}s")
            time.sleep(POLL_S)
        out = self.fal.result(sub)
        job.note(f"{label}: completed")
        return out

    def _fal_fetch(self, job, output, exts, dest_dir, stem):
        urls = find_urls(output, exts)
        if not urls:
            raise ProviderError(f"no {exts} file in provider output: {str(output)[:400]}")
        url = urls[0]
        ext = next(e for e in exts if url.lower().split("?")[0].endswith(e))
        dest = os.path.join(dest_dir, f"{stem}{ext}")
        job.note(f"downloading {ext}")
        download(url, dest)
        return dest, url

    def _local(self, path):
        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            path = os.path.join(self.engine.workspace, "renders", path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        return path

    def _as_input(self, image):
        """Local path -> absolute path; URLs pass through."""
        return image if image.startswith(("http://", "https://")) else self._local(image)

    # ------------------------------------------------------------------ one generation step
    def _generate(self, job, task, inputs, dest_dir, stem, model=None, extra=None, label=None):
        """Run one task on the job's provider. Returns (local_file, remote_url_or_None)."""
        label = label or task.replace("_", " ")
        if job.provider == "hf":
            job.note(f"{label}: free Space queue")
            path, used = self.hf.run(job, task, inputs, dest_dir, stem, recipe=model,
                                     on_status=lambda s: setattr(job, "stage", f"{label}: {s}"))
            job.note(f"{label}: completed via {used}")
            return path, None
        m = models.model_for(task, model)
        if task == "text_to_image":
            payload = {"prompt": inputs["prompt"], "image_size": "square_hd", "num_images": 1,
                       **(extra or {})}   # prompt is already wrapped by the pipeline
            exts = IMAGE_EXTS
        elif task == "image_to_3d":
            img = inputs["image"]
            url = img if img.startswith(("http://", "https://")) else data_uri(img)
            payload, exts = models.image_to_3d_input(m, url, extra), MESH_EXTS
        elif task == "image_to_video":
            img = inputs["image"]
            url = img if img.startswith(("http://", "https://")) else data_uri(img)
            payload = models.image_to_video_input(m, url, inputs["prompt"], inputs["duration"],
                                                  inputs.get("aspect_ratio"), extra)
            exts = VIDEO_EXTS
        else:
            payload = models.text_to_video_input(inputs["prompt"], inputs["duration"],
                                                 inputs.get("aspect_ratio") or "16:9", extra)
            exts = VIDEO_EXTS
        out = self._fal_run(job, m, payload, label)
        return self._fal_fetch(job, out, exts, dest_dir, stem)

    # ------------------------------------------------------------------ 3D
    def _finish_3d(self, job, mesh_path):
        p = job.params
        job.note("importing into Blender")
        imp = self.engine.call("import_model", path=mesh_path)
        names = [o["name"] for o in imp["imported"]]
        job.note("preparing mesh (join, clean, scale, ground)")
        prep = self.engine.call("prepare_model", objects=names, name=p["name"],
                                height=p.get("height"), max_faces=p.get("max_faces"),
                                rotate_z=p.get("rotate_z", 0.0))
        job.result.update({"model_file": mesh_path, "mesh": prep["name"],
                           "dimensions": prep["dimensions"], "faces": prep["faces"]})
        if p.get("rig"):
            job.note("auto-rigging (estimated landmarks)")
            rep = self.engine.call("auto_rig_humanoid", mesh=prep["name"],
                                   rig_type=p.get("rig_type", "basic"))
            job.result["rig"] = {k: rep[k] for k in ("ok", "armature", "rig_type", "issues",
                                                      "unweighted_vertices", "max_influences")}

    def text_to_3d(self, prompt, name, character=True, rig=True, rig_type="basic", height=None,
                   max_faces=60000, image_model=None, model=None, extra_input=None,
                   provider="auto"):
        params = dict(prompt=prompt, name=name, character=character, rig=rig and character,
                      rig_type=rig_type, height=height or (1.75 if character else None),
                      max_faces=max_faces)

        def pipeline(job):
            imports, _ = self._dirs()
            text = (models.CHARACTER_PROMPT if character else models.PROP_PROMPT).format(
                prompt=prompt.strip())
            concept, url = self._generate(job, "text_to_image", {"prompt": text}, imports,
                                          f"{job.id}_concept", model=image_model,
                                          label="concept image")
            job.result["concept_image"] = concept
            mesh, _ = self._generate(job, "image_to_3d", {"image": url or concept}, imports,
                                     job.id, model=model, extra=extra_input, label="3D model")
            self._finish_3d(job, mesh)

        return self._start("text_to_3d", provider, params, pipeline)

    def image_to_3d(self, image, name, character=True, rig=True, rig_type="basic", height=None,
                    max_faces=60000, model=None, extra_input=None, provider="auto"):
        params = dict(image=image, name=name, character=character, rig=rig and character,
                      rig_type=rig_type, height=height or (1.75 if character else None),
                      max_faces=max_faces)
        src = self._as_input(image)

        def pipeline(job):
            imports, _ = self._dirs()
            mesh, _ = self._generate(job, "image_to_3d", {"image": src}, imports, job.id,
                                     model=model, extra=extra_input, label="3D model")
            self._finish_3d(job, mesh)

        return self._start("image_to_3d", provider, params, pipeline)

    # ------------------------------------------------------------------ video
    def image_to_video(self, image, prompt, duration=5, aspect_ratio=None, model=None,
                       extra_input=None, output=None, provider="auto"):
        params = dict(image=image, prompt=prompt, duration=duration)
        src = self._as_input(image)

        def pipeline(job):
            _, renders = self._dirs()
            stem = os.path.splitext(output)[0] if output else job.id
            path, _ = self._generate(job, "image_to_video",
                                     {"image": src, "prompt": prompt, "duration": duration,
                                      "aspect_ratio": aspect_ratio},
                                     renders, stem, model=model, extra=extra_input, label="video")
            job.result.update({"video": path, "bytes": os.path.getsize(path)})

        return self._start("image_to_video", provider, params, pipeline)

    def text_to_video(self, prompt, duration=5, aspect_ratio="16:9", model=None,
                      extra_input=None, output=None, provider="auto"):
        params = dict(prompt=prompt, duration=duration, aspect_ratio=aspect_ratio)

        def pipeline(job):
            _, renders = self._dirs()
            stem = os.path.splitext(output)[0] if output else job.id
            path, _ = self._generate(job, "text_to_video",
                                     {"prompt": prompt, "duration": duration,
                                      "aspect_ratio": aspect_ratio},
                                     renders, stem, model=model, extra=extra_input, label="video")
            job.result.update({"video": path, "bytes": os.path.getsize(path)})

        return self._start("text_to_video", provider, params, pipeline)
