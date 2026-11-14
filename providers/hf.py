"""Free generation through public Hugging Face Spaces (Gradio apps on ZeroGPU).

No key needed. An optional free HF token (HF_TOKEN) raises the daily GPU quota.
Spaces are community demos: they can queue, hit quotas, sleep or change their API.
Each task has named "recipes" (space + endpoint + argument builder + output picker);
defaults can be switched per call (`model="trellis"`) or via CHAR3D_HF_<TASK>.
"""
import inspect
import os
import shutil
import time

from .fal import ProviderError

try:
    from gradio_client import Client, handle_file
except ImportError:  # optional dependency
    Client = handle_file = None


def _file(x):
    return handle_file(x)


RECIPES = {
    "text_to_image": {
        "flux-schnell": dict(
            space="black-forest-labs/FLUX.1-schnell", api="/infer", output=0,
            args=lambda i: dict(prompt=i["prompt"], randomize_seed=True, width=1024, height=1024,
                                num_inference_steps=4)),
    },
    "image_to_3d": {
        "hunyuan3d": dict(
            space="tencent/Hunyuan3D-2", api="/shape_generation", output=0,
            args=lambda i: dict(image=_file(i["image"]), steps=30, guidance_scale=5.0,
                                octree_resolution=256, check_box_rembg=True,
                                randomize_seed=True)),
        "hunyuan3d-textured": dict(
            space="tencent/Hunyuan3D-2", api="/generation_all", output=1,
            args=lambda i: dict(image=_file(i["image"]), steps=30, guidance_scale=5.0,
                                octree_resolution=256, check_box_rembg=True,
                                randomize_seed=True)),
        "trellis": dict(
            space="trellis-community/TRELLIS", api="/generate_and_extract_glb", output=1,
            before=["/start_session"],
            args=lambda i: dict(image=_file(i["image"]), multiimages=[], seed=0,
                                mesh_simplify=0.95, texture_size=1024)),
        "stable-fast-3d": dict(
            space="stabilityai/stable-fast-3d", api="/run_button", output=1,
            args=lambda i: dict(input_image=_file(i["image"]), foreground_ratio=0.85,
                                remesh_option="None", vertex_count=-1, texture_size=1024)),
    },
    "image_to_video": {
        "ltx": dict(
            space="Lightricks/ltx-video-distilled", api="/image_to_video", output=0,
            args=lambda i: dict(prompt=i["prompt"], input_image_filepath=_file(i["image"]),
                                mode="image-to-video", duration_ui=min(float(i["duration"]), 8.0),
                                randomize_seed=True)),
        "wan": dict(
            space="zerogpu-aoti/wan2-2-fp8da-aoti-faster", api="/generate_video", output=0,
            args=lambda i: dict(input_image=_file(i["image"]), prompt=i["prompt"],
                                duration_seconds=min(float(i["duration"]), 5.0),
                                randomize_seed=True)),
    },
    "text_to_video": {
        "ltx": dict(
            space="Lightricks/ltx-video-distilled", api="/text_to_video", output=0,
            args=lambda i: dict(prompt=i["prompt"], mode="text-to-video",
                                duration_ui=min(float(i["duration"]), 8.0), randomize_seed=True)),
    },
}
DEFAULTS = {"text_to_image": "flux-schnell", "image_to_3d": "hunyuan3d",
            "image_to_video": "ltx", "text_to_video": "ltx"}


def recipe_for(task, name=None):
    name = name or os.environ.get(f"CHAR3D_HF_{task.upper()}") or DEFAULTS[task]
    if name not in RECIPES[task]:
        raise ProviderError(f"unknown free model '{name}' for {task}. "
                            f"Choose one of {sorted(RECIPES[task])}")
    return name, RECIPES[task][name]


def _pick(result, index):
    """Gradio returns tuples of outputs; files come back as paths or {video|path: ...}."""
    out = result[index] if isinstance(result, (list, tuple)) else result
    for _ in range(3):
        if isinstance(out, dict):
            out = out.get("video") or out.get("path") or out.get("value") or out.get("name")
        else:
            break
    if not isinstance(out, str) or not os.path.isfile(out):
        raise ProviderError(f"Space returned no file at output {index}: {str(result)[:300]}")
    return out


class HFClient:
    name = "hf"

    @property
    def available(self):
        return Client is not None

    @property
    def token_set(self):
        return bool(os.environ.get("HF_TOKEN"))

    def _client(self, space):
        if Client is None:
            raise ProviderError("gradio_client is not installed: .venv/bin/pip install -r requirements.txt")
        kwargs = {"verbose": False}
        token = os.environ.get("HF_TOKEN")
        if token:
            params = inspect.signature(Client).parameters
            kwargs["token" if "token" in params else "hf_token"] = token
        try:
            return Client(space, **kwargs)
        except Exception as exc:
            raise ProviderError(f"cannot open Space {space} (sleeping, down or renamed?): "
                                f"{type(exc).__name__}: {str(exc)[:200]}") from None

    def run(self, job, task, inputs, dest_dir, stem, recipe=None, on_status=None):
        """Run a recipe and copy its output file into dest_dir. Returns (path, label)."""
        name, r = recipe_for(task, recipe)
        client = self._client(r["space"])
        for pre in r.get("before", []):
            try:
                client.predict(api_name=pre)
            except Exception:
                pass   # optional warm-up endpoints
        job_handle = client.submit(api_name=r["api"], **r["args"](inputs))
        job.handles.append(job_handle)
        while not job_handle.done():
            if job.cancel_requested:
                job_handle.cancel()
                raise InterruptedError("cancelled")
            st = job_handle.status()
            if on_status:
                rank = getattr(st, "rank", None)
                eta = getattr(st, "eta", None)
                code = getattr(getattr(st, "code", None), "value", str(getattr(st, "code", "")))
                on_status(f"{code}" + (f", queue {rank}" if rank else "")
                          + (f", eta {eta:.0f}s" if isinstance(eta, (int, float)) else ""))
            time.sleep(2)
        try:
            result = job_handle.result()
        except Exception as exc:
            msg = str(exc)
            hint = (" (free GPU quota used up: wait, or set a free HF_TOKEN)"
                    if "quota" in msg.lower() or "zerogpu" in msg.lower() else "")
            raise ProviderError(f"Space {r['space']} failed: {msg[:300]}{hint}") from None
        src = _pick(result, r["output"])
        ext = os.path.splitext(src)[1].lower() or ".bin"
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"{stem}{ext}")
        shutil.copyfile(src, dest)
        return dest, f"{name} ({r['space']})"
