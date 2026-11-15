"""Video rendering as background jobs.

The scene (with temporary render settings) is saved to a .blend snapshot and rendered by
a separate Blender process, so the engine stays responsive while frames render.
"""
import glob
import json
import math
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
# named output sizes (landscape; vertical=True swaps them)
RESOLUTIONS = {
    "480p": (854, 480), "540p": (960, 540), "720p": (1280, 720),
    "1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160),
}
# Speed model (seconds per frame): overhead + k * pixels * samples, fitted on the developer
# machine (CPU only, no GPU) with a clothed MPFB character + hair: 960x540@16 ~ 4 s,
# 1920x1080@64 ~ 48 s. Lighter scenes (mannequins) render ~35% faster.
# Every machine differs (a GPU can be 10-50x faster), so each engine has a per-machine
# speed factor learned from finished renders and optional test frames (CALIB_PATH).
EEVEE_OVERHEAD_S, EEVEE_K = 1.1, 3.55e-7
WORKBENCH_K = 1.0e-7
CYCLES_K = 2.4e-6
ENGINE_KEY = {"BLENDER_EEVEE": "eevee", "BLENDER_WORKBENCH": "workbench", "CYCLES": "cycles"}
CALIB_PATH = os.environ.get("CHAR3D_RENDER_CALIB") or os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "char3d", "render_speed.json")
TEST_RESOLUTION = (854, 480)
# a lone in-process test frame is ~15-20% slower per frame than the same frame inside a
# background animation render (per-render sync/compositing), measured on Eevee
TEST_FRAME_BIAS = 0.85
JOBS = {}


def _output_size(sc, quality, width, height, resolution, vertical):
    """Final pixel size (w, h) and resolution percentage for a render."""
    pct = QUALITY[quality][1]
    if resolution:
        key = str(resolution).lower()
        if key not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {list(RESOLUTIONS)}")
        w, h = RESOLUTIONS[key]
        pct = 100
    elif width and height:
        w, h = int(width), int(height)
    else:
        w, h = sc.render.resolution_x, sc.render.resolution_y
    if vertical and w > h:
        w, h = h, w
    return w, h, pct


def _scene_weight(sc):
    """1.0 for heavy scenes (realistic human with hair/clothes), ~0.65 for light ones."""
    verts = 0
    for ob in sc.objects:
        if ob.type == "MESH" and not ob.hide_render:
            verts += len(ob.data.vertices)
    return 1.0 if verts > 30000 else 0.65


def _model_spf(engine, samples, w, h, weight):
    """Uncalibrated seconds per frame (developer machine)."""
    px = w * h
    if engine == "BLENDER_WORKBENCH":
        return 0.05 + WORKBENCH_K * px
    if engine == "CYCLES":
        return (2.0 + CYCLES_K * px * samples) * weight
    return (EEVEE_OVERHEAD_S + EEVEE_K * px * samples) * weight


# ---- per-machine calibration
def _load_calib():
    try:
        with open(CALIB_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_calib(data):
    try:
        os.makedirs(os.path.dirname(CALIB_PATH), exist_ok=True)
        tmp = CALIB_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, CALIB_PATH)
    except OSError:
        pass


def _factor(engine):
    return float(_load_calib().get(ENGINE_KEY[engine], {}).get("factor", 1.0))


def _learn(engine, measured_spf, predicted_spf, source, info=None):
    """Blend measured/predicted into the engine's speed factor (geometric moving average)."""
    if not (measured_spf > 0 and predicted_spf > 0):
        return None
    ratio = min(100.0, max(0.01, measured_spf / predicted_spf))
    data = _load_calib()
    key = ENGINE_KEY[engine]
    entry = data.get(key, {})
    n = int(entry.get("samples", 0))
    if n == 0:
        factor = ratio
    else:   # real renders count more than a single test frame
        a = 0.5 if source == "render" else 0.35
        factor = math.exp((1 - a) * math.log(float(entry.get("factor", 1.0))) + a * math.log(ratio))
    data[key] = {"factor": round(factor, 4), "samples": n + 1,
                 "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "last": {"source": source, "measured_s_per_frame": round(measured_spf, 3),
                          "model_s_per_frame": round(predicted_spf, 3), **(info or {})}}
    _save_calib(data)
    return data[key]


def _calibration_report():
    data = _load_calib()
    out = {}
    for key in ("eevee", "workbench", "cycles"):
        e = data.get(key)
        if e:
            out[key] = {"factor": e.get("factor"), "measurements": e.get("samples"),
                        "last": e.get("last", {}).get("source"), "updated": e.get("updated")}
        else:
            out[key] = {"factor": 1.0, "measurements": 0,
                        "last": "not measured (developer machine defaults)"}
    return out


def _frame_times(log_text):
    """Per-frame render times (s) from a Blender log ("Time: 00:12.34" / "01:02:03.45")."""
    out = []
    for m in re.finditer(r"\bTime: ([\d:.]+)", log_text):
        parts = m.group(1).split(":")
        try:
            sec = 0.0
            for p in parts:
                sec = sec * 60 + float(p)
            out.append(sec)
        except ValueError:
            continue
    return out


def _learn_from_job(job, text):
    """After a finished render: learn this machine's speed from the median frame time."""
    times = _frame_times(text)
    if len(times) >= 4:
        times = times[1:]                    # first frame includes shader compilation
    if len(times) < 3 or not job.get("model_spf"):
        return
    times.sort()
    median = times[len(times) // 2]
    engine = QUALITY[job["quality"]][0]
    learned = _learn(engine, median, job["model_spf"], "render",
                     {"quality": job["quality"], "size": job.get("size"), "frames": len(times)})
    if learned:
        job["learned_speed"] = {"engine": ENGINE_KEY[engine], "factor": learned["factor"],
                                "measured_s_per_frame": round(median, 2)}


def _seconds_per_frame(quality, w, h, weight):
    engine, _pct, samples = QUALITY[quality]
    return _model_spf(engine, samples, w, h, weight) * _factor(engine)


def _fmt_duration(sec):
    sec = int(round(sec))
    if sec < 90:
        return f"~{sec} s"
    if sec < 5400:
        return f"~{round(sec / 60)} min"
    return f"~{sec / 3600:.1f} h"


def _estimate(sc, quality, w, h, frames):
    spf = _seconds_per_frame(quality, w, h, _scene_weight(sc))
    total = spf * frames
    return {"seconds_per_frame": round(spf, 1), "total_s": round(total),
            "total": _fmt_duration(total)}


def _test_frame(sc, quality, frame):
    """Render one frame in-process at 480p to measure this machine (after a warm-up render
    that compiles shaders). Samples are capped so the test stays short; the model scales."""
    engine, _pct, samples = QUALITY[quality]
    samples = min(samples, 32) if engine == "BLENDER_EEVEE" else min(samples, 16)
    w, h = TEST_RESOLUTION
    r = sc.render
    saved = dict(engine=r.engine, rx=r.resolution_x, ry=r.resolution_y,
                 pct=r.resolution_percentage, fp=r.filepath, frame=sc.frame_current,
                 eevee=sc.eevee.taa_render_samples)
    cyc = None
    if engine == "CYCLES":
        cyc = (sc.cycles.samples, sc.cycles.device, sc.cycles.use_denoising)
    try:
        r.engine = engine
        r.resolution_x, r.resolution_y = w, h
        sc.frame_set(int(frame))
        if engine == "CYCLES":
            sc.cycles.device, sc.cycles.use_denoising = "CPU", True
        # warm-up: tiny, 1 sample (shader compilation, scene sync)
        r.resolution_percentage = 25
        if engine == "BLENDER_EEVEE":
            sc.eevee.taa_render_samples = 1
        elif engine == "CYCLES":
            sc.cycles.samples = 1
        bpy.ops.render.render()
        r.resolution_percentage = 100
        if engine == "BLENDER_EEVEE":
            sc.eevee.taa_render_samples = samples
        elif engine == "CYCLES":
            sc.cycles.samples = samples
        t0 = time.perf_counter()
        bpy.ops.render.render()
        measured = (time.perf_counter() - t0) * TEST_FRAME_BIAS
    finally:
        r.engine, r.resolution_x, r.resolution_y = saved["engine"], saved["rx"], saved["ry"]
        r.resolution_percentage, r.filepath = saved["pct"], saved["fp"]
        sc.eevee.taa_render_samples = saved["eevee"]
        if cyc:
            sc.cycles.samples, sc.cycles.device, sc.cycles.use_denoising = cyc
        sc.frame_set(saved["frame"])
    predicted = _model_spf(engine, samples, w, h, _scene_weight(sc))
    learned = _learn(engine, measured, predicted, "test_frame",
                     {"quality": quality, "size": [w, h], "samples": samples})
    return {"engine": ENGINE_KEY[engine], "size": f"{w}x{h}", "samples": samples,
            "measured_s": round(measured, 2), "factor": learned["factor"] if learned else None}


def _apply_settings(sc, quality, size, fps, start, end, base):
    engine, _pct, samples = QUALITY[quality]
    r = sc.render
    r.engine = engine
    w, h, pct = size
    r.resolution_x, r.resolution_y = int(w), int(h)
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
    from .audio import _sound_strips
    if _sound_strips(sc):            # timeline has sound: mux it as AAC
        r.ffmpeg.audio_codec = "AAC"
        r.ffmpeg.audio_bitrate = 192
        if hasattr(r.ffmpeg, "audio_channels"):
            r.ffmpeg.audio_channels = "STEREO"
    else:
        r.ffmpeg.audio_codec = "NONE"
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
            try:
                with open(job["log"], errors="replace") as f:
                    _learn_from_job(job, f.read())
            except OSError:
                pass
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
           "quality": job["quality"], "size": job.get("size"), "frames": job["frames"],
           "progress": f"{done}/{total}", "elapsed_s": round(elapsed, 1)}
    if job["status"] == "running" and done > 0:
        out["eta_s"] = round(elapsed / done * (total - done), 1)
    elif job["status"] == "running" and job.get("estimate"):
        out["estimate"] = job["estimate"]
    if job["status"] == "done":
        out["bytes"] = job["bytes"]
        out["has_audio"] = job.get("audio", False)
        if job.get("learned_speed"):
            out["learned_speed"] = job["learned_speed"]
    if job.get("error"):
        out["error"] = job["error"]
    if job["status"] == "failed":
        out["log_tail"] = "\n".join(text.strip().splitlines()[-15:])
    return out


@command("render_video")
def render_video(path="video.mp4", frame_start=None, frame_end=None, quality="preview",
                 width=None, height=None, fps=None, wait=False, resolution=None, vertical=False):
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
        size = _output_size(sc, quality, width, height, resolution, vertical)
        _apply_settings(sc, quality, size, fps, start, end, base)
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
    from .audio import _sound_strips
    job = {"id": job_id, "proc": proc, "path": path, "base": base, "blend": blend, "log": log,
           "audio": bool(_sound_strips(sc)),
           "quality": quality, "frames": [start, end], "status": "running",
           "started": time.time(),
           "size": [round(size[0] * size[2] / 100), round(size[1] * size[2] / 100)]}
    out_w, out_h = job["size"]
    job["estimate"] = _estimate(sc, quality, out_w, out_h, end - start + 1)
    job["model_spf"] = _model_spf(QUALITY[quality][0], QUALITY[quality][2], out_w, out_h,
                                  _scene_weight(sc))
    JOBS[job_id] = job
    if wait:
        proc.wait()
    return _report(job)


@command("render_options")
def render_options(quality="final", frame_start=None, frame_end=None, vertical=False,
                   calibrate=False):
    """Resolution choices with estimated render time for this scene, to offer the user.

    Estimates use this machine's learned speed (from finished renders); calibrate=True first
    renders one 480p test frame of this scene to measure it now.
    """
    if quality not in QUALITY:
        raise ValueError(f"quality must be one of {list(QUALITY)}")
    sc = bpy.context.scene
    start = int(frame_start if frame_start is not None else sc.frame_start)
    end = int(frame_end if frame_end is not None else sc.frame_end)
    test = None
    if calibrate:
        if sc.camera is None and not any(m.camera for m in sc.timeline_markers):
            raise RuntimeError("no camera: create one with camera_shot first")
        test = _test_frame(sc, quality, (start + end) // 2)
    frames = max(1, end - start + 1)
    fps = sc.render.fps / (sc.render.fps_base or 1)
    options = []
    for name, (w, h) in RESOLUTIONS.items():
        if vertical:
            w, h = h, w
        options.append({"resolution": name, "size": f"{w}x{h}",
                        **_estimate(sc, quality, w, h, frames)})
    engine = QUALITY[quality][0]
    calib = _calibration_report()
    out = {"quality": quality, "frames": [start, end], "duration_s": round(frames / fps, 2),
           "scene_weight": "heavy" if _scene_weight(sc) >= 1 else "light",
           "options": options, "machine_speed": calib[ENGINE_KEY[engine]]}
    if test:
        out["test_frame"] = test
    if not calib[ENGINE_KEY[engine]]["measurements"]:
        out["note"] = ("not calibrated on this machine yet (developer-machine defaults, CPU only): "
                       "call again with calibrate=True for a measured estimate")
    else:
        out["note"] = "estimates learned on this machine; render_status shows the real ETA"
    return out


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
