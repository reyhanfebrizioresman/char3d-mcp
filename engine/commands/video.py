"""Video rendering as background jobs.

The scene (with temporary render settings) is saved to a .blend snapshot and rendered by
a separate Blender process, so the engine stays responsive while frames render.
"""
import glob
import os
import re
import shutil
import subprocess
import time

import bpy

from .. import context
from . import command

QUALITY = {
    # engine, resolution %, samples
    "draft": ("BLENDER_WORKBENCH", 50, 0),
    "preview": ("BLENDER_EEVEE", 50, 16),
    "final": ("BLENDER_EEVEE", 100, 64),
    "cycles": ("CYCLES", 100, 96),
}
JOBS = {}


def _apply_settings(sc, quality, width, height, fps, start, end, base):
    engine, pct, samples = QUALITY[quality]
    r = sc.render
    r.engine = engine
    if width and height:
        r.resolution_x, r.resolution_y = int(width), int(height)
    r.resolution_percentage = pct
    if fps:
        r.fps = int(fps)
    sc.frame_start, sc.frame_end = int(start), int(end)
    if engine == "BLENDER_EEVEE":
        sc.eevee.taa_render_samples = samples
    elif engine == "CYCLES":
        sc.cycles.device = "CPU"
        sc.cycles.samples = samples
        sc.cycles.use_denoising = True
    elif engine == "BLENDER_WORKBENCH":
        sh = sc.display.shading
        sh.light, sh.color_type = "STUDIO", "MATERIAL"
    im = r.image_settings
    if hasattr(im, "media_type"):
        im.media_type = "VIDEO"
    im.file_format = "FFMPEG"
    r.ffmpeg.format = "MPEG4"
    r.ffmpeg.codec = "H264"
    r.ffmpeg.constant_rate_factor = "HIGH" if quality in ("final", "cycles") else "MEDIUM"
    r.ffmpeg.ffmpeg_preset = "GOOD"
    r.use_file_extension = True
    r.filepath = base


def _finalize(job):
    if job["status"] in ("done", "failed"):
        return
    code = job["proc"].poll()
    if code is None:
        return
    produced = sorted(glob.glob(glob.escape(job["base"]) + "*.mp4"), key=os.path.getmtime)
    if code == 0 and produced:
        try:
            if os.path.exists(job["path"]):
                os.remove(job["path"])
            shutil.move(produced[-1], job["path"])   # works across filesystems
            job["status"] = "done"
            job["bytes"] = os.path.getsize(job["path"])
        except OSError as exc:
            job["status"] = "failed"
            job["error"] = f"rendered to {produced[-1]} but could not move it: {exc}"
    else:
        job["status"] = "failed"
    job["finished"] = time.time()
    try:
        os.remove(job["blend"])
    except OSError:
        pass


def _progress(job):
    try:
        with open(job["log"], errors="replace") as f:
            text = f.read()
    except OSError:
        return None, ""
    frames = [int(x) for x in re.findall(r"Fra:\s*(\d+)", text)]
    return (max(frames) if frames else None), text


def _report(job):
    _finalize(job)
    last, text = _progress(job)
    total = job["frames"][1] - job["frames"][0] + 1
    done = 0 if last is None else max(0, last - job["frames"][0] + (1 if job["status"] == "done" else 0))
    if job["status"] == "done":
        done = total
    elapsed = (job.get("finished") or time.time()) - job["started"]
    out = {"job_id": job["id"], "status": job["status"], "path": job["path"],
           "quality": job["quality"], "frames": job["frames"],
           "progress": f"{done}/{total}", "elapsed_s": round(elapsed, 1)}
    if job["status"] == "running" and done > 0:
        out["eta_s"] = round(elapsed / done * (total - done), 1)
    if job["status"] == "done":
        out["bytes"] = job["bytes"]
    if job.get("error"):
        out["error"] = job["error"]
    if job["status"] == "failed":
        out["log_tail"] = "\n".join(text.strip().splitlines()[-15:])
    return out


@command("render_video")
def render_video(path="video.mp4", frame_start=None, frame_end=None, quality="preview",
                 width=None, height=None, fps=None, wait=False):
    """Render the scene camera / shot timeline to MP4 (H.264) in a background process."""
    if quality not in QUALITY:
        raise ValueError(f"quality must be one of {list(QUALITY)}")
    sc = bpy.context.scene
    if sc.camera is None and not any(m.camera for m in sc.timeline_markers):
        raise RuntimeError("no camera: create one with camera_shot first")
    start = int(frame_start if frame_start is not None else sc.frame_start)
    end = int(frame_end if frame_end is not None else sc.frame_end)
    if end < start:
        raise ValueError("frame_end must be >= frame_start")
    path = context.resolve(path, "renders")
    if not path.lower().endswith(".mp4"):
        path += ".mp4"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    job_id = f"job{len(JOBS) + 1}_{time.strftime('%H%M%S')}"
    jobs_dir = os.path.join(context.WORKSPACE, "jobs")
    os.makedirs(jobs_dir, exist_ok=True)
    base = os.path.join(os.path.dirname(path), f".{job_id}_")
    blend = os.path.join(jobs_dir, f"{job_id}.blend")
    log = os.path.join(jobs_dir, f"{job_id}.log")

    r = sc.render
    saved = dict(engine=r.engine, rx=r.resolution_x, ry=r.resolution_y, pct=r.resolution_percentage,
                 fps=r.fps, fs=sc.frame_start, fe=sc.frame_end, fp=r.filepath,
                 media=getattr(r.image_settings, "media_type", None), fmt=r.image_settings.file_format)
    try:
        _apply_settings(sc, quality, width, height, fps, start, end, base)
        bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True)
    finally:
        r.engine, r.resolution_x, r.resolution_y = saved["engine"], saved["rx"], saved["ry"]
        r.resolution_percentage, r.fps, r.filepath = saved["pct"], saved["fps"], saved["fp"]
        sc.frame_start, sc.frame_end = saved["fs"], saved["fe"]
        if saved["media"]:
            r.image_settings.media_type = saved["media"]
        r.image_settings.file_format = saved["fmt"]

    with open(log, "wb") as lf:
        proc = subprocess.Popen([bpy.app.binary_path, "-b", blend, "-a"], stdout=lf,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    job = {"id": job_id, "proc": proc, "path": path, "base": base, "blend": blend, "log": log,
           "quality": quality, "frames": [start, end], "status": "running",
           "started": time.time()}
    JOBS[job_id] = job
    if wait:
        proc.wait()
    return _report(job)


@command("render_status")
def render_status(job_id=None):
    if job_id:
        if job_id not in JOBS:
            raise KeyError(f"unknown job {job_id}. Known: {list(JOBS)}")
        return _report(JOBS[job_id])
    return {"jobs": [_report(j) for j in JOBS.values()]}


@command("cancel_render")
def cancel_render(job_id):
    job = JOBS.get(job_id)
    if not job:
        raise KeyError(f"unknown job {job_id}")
    if job["proc"].poll() is None:
        job["proc"].terminate()
        job["proc"].wait(timeout=10)
    job["status"] = "failed"
    job["finished"] = time.time()
    return _report(job)
