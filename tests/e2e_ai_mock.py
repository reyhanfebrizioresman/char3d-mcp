"""Offline end-to-end test of the AI pipelines against a local fake fal.ai.

    .venv/bin/python tests/e2e_ai_mock.py

MCP client -> MCP server (FAL_KEY=test-key, CHAR3D_FAL_BASE=mock) -> mock queue API
-> downloads -> Blender import / prepare_model / auto-rig.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from mock_fal import MockFal  # noqa: E402


def text_of(res):
    return [c.text for c in res.content if c.type == "text"]


async def main():
    files = tempfile.mkdtemp(prefix="char3d_mockfal_")
    mock = MockFal(files)
    base = mock.start()
    env = dict(os.environ, FAL_KEY="test-key", CHAR3D_FAL_BASE=base, CHAR3D_POLL_SECONDS="0.2",
               CHAR3D_PORT=os.environ.get("CHAR3D_PORT", "9897"))
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=env)
    try:
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()

            async def call(tool, **args):
                res = await s.call_tool(tool, args)
                if res.isError:
                    raise RuntimeError(f"{tool} failed: {text_of(res)}")
                texts = text_of(res)
                if not texts:
                    return res
                try:
                    return json.loads(texts[0])
                except json.JSONDecodeError:
                    return texts[0]

            async def wait_job(job_id, limit=300):
                t0 = time.time()
                while time.time() - t0 < limit:
                    st = await call("ai_job_status", job_id=job_id)
                    if st["status"] not in ("queued", "running"):
                        return st
                    await asyncio.sleep(0.5)
                raise TimeoutError(job_id)

            # fixtures the fake provider will "generate": an un-landmarked T-pose human
            # exported with odd scale/offset, a concept PNG and a short MP4
            await call("new_scene")
            await call("create_human", name="Fx", style="stylized", arm_angle=0)
            await call("transform_object", name="Fx", location=[3, 2, 1], scale=[0.4, 0.4, 0.4])
            glb = await call("export_asset", path="mock_model.glb", objects=["Fx"])
            png = await call("render_preview", view="front", width=256, height=256,
                             engine_name="workbench")
            png_path = png["path"]
            await call("set_lighting", preset="studio")
            await call("camera_shot", shot="full", move="static", start_frame=1, end_frame=12)
            vid = await call("render_video", path="mock_clip.mp4", quality="draft", wait=True)
            shutil.copy(glb["path"], os.path.join(files, "model.glb"))
            shutil.copy(png_path, os.path.join(files, "concept.png"))
            shutil.copy(vid["path"], os.path.join(files, "clip.mp4"))

            st = await call("ai_status")
            assert st["fal"]["configured"] and st["fal"]["endpoint"] == base, st
            assert st["default_provider"] == "fal", st

            # text -> concept image -> 3D -> import -> prepare -> rig
            await call("new_scene")
            job = await call("ai_text_to_3d", prompt="a friendly robot explorer", name="Robo",
                             provider="fal")
            done = await wait_job(job["job_id"])
            assert done["status"] == "done", done
            res = done["result"]
            assert abs(res["dimensions"][2] - 1.75) < 0.01, res          # normalised height
            assert res["rig"]["ok"] and res["rig"]["unweighted_vertices"] == 0, res
            info = await call("scene_info")
            names = {o["name"] for o in info["objects"]}
            assert {"Robo", "Robo_rig"} <= names, names
            assert abs(info["bounds"]["min"][2]) < 1e-3, info["bounds"]   # on the ground
            await call("animate", armature="Robo_rig", clip="walk", cycles=1)
            print("text_to_3d:", res["mesh"], res["dimensions"], "rig ok", res["rig"]["ok"])

            # image -> video
            job = await call("ai_image_to_video", image=png_path, provider="fal",
                             prompt="slow dolly in, character waves", duration=5)
            done = await wait_job(job["job_id"])
            assert done["status"] == "done", done
            assert os.path.getsize(done["result"]["video"]) == os.path.getsize(vid["path"])
            print("image_to_video:", os.path.basename(done["result"]["video"]),
                  done["result"]["bytes"], "bytes")

            # what was sent to the provider
            posts = [c for c in mock.calls if c[0] == "POST"]
            assert all(c[2] == "Key test-key" for c in mock.calls if c[1].startswith("/requests")
                       or c[0] == "POST"), "missing auth"
            t2i, i23d, i2v = posts[0], posts[1], posts[2]
            assert "flux" in t2i[1] and "robot explorer" in t2i[3]["prompt"]
            assert "A-pose" in t2i[3]["prompt"]
            assert "hunyuan3d" in i23d[1] and i23d[3]["input_image_url"].endswith("/files/concept.png")
            assert "image-to-video" in i2v[1]
            assert i2v[3]["image_url"].startswith("data:image/png;base64,")
            assert i2v[3]["duration"] == "5"
            print("provider calls:", [c[1] for c in posts])
            await call("engine_shutdown")
    finally:
        mock.stop()
        shutil.rmtree(files, ignore_errors=True)

    # without a key the tools must refuse clearly instead of calling out
    os.environ.pop("FAL_KEY", None)
    sys.path.insert(0, ROOT)
    from providers.jobs import JobManager, ProviderError
    jm = JobManager(engine=None)
    st = jm.status()
    assert st["fal"]["configured"] is False and st["default_provider"] == "hf", st
    try:
        jm.text_to_3d("x", "y", provider="fal")
        raise AssertionError("expected ProviderError without FAL_KEY")
    except ProviderError as exc:
        assert "FAL_KEY" in str(exc)
    print("no-key: fal refused, auto falls back to free hf - OK")
    print("AI MOCK E2E OK")


asyncio.run(main())
