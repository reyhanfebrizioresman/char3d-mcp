"""Queue concurrency and workspace boundaries, without Blender or network providers."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.jobs import JobQueue  # noqa: E402
from webui.security import Workspace, redact  # noqa: E402


class FakeMCP:
    def __init__(self):
        self.calls = []
        self.active = 0
        self.peak = 0
        self.done = False

    async def call_tool(self, name, arguments):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls.append(name)
        await asyncio.sleep(.01)
        if name in {"render_video", "render_film"}:
            result = {"job_id": "video-1", "status": "running"}
        elif name == "render_status":
            result = {"job_id": "video-1", "status": "done" if self.done else "running"}
        else:
            result = {"name": name}
        self.active -= 1
        return [SimpleNamespace(type="text", text=json.dumps(result))]


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mcp = FakeMCP()
        self.queue = JobQueue(self.mcp, Workspace(self.temp.name))
        self.worker = asyncio.create_task(self.queue.worker())

    async def asyncTearDown(self):
        tasks = [self.worker, *self.queue.monitors, *self.queue.independent]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.temp.cleanup()

    async def test_fifo_and_one_command_at_a_time(self):
        jobs = [self.queue.submit(name, {}) for name in ("first", "second", "third")]
        self.assertEqual(self.queue.public(jobs[-1])["queue_position"], 3)
        await asyncio.wait_for(self.queue.queue.join(), 2)
        self.assertEqual(self.mcp.calls, ["first", "second", "third"])
        self.assertEqual(self.mcp.peak, 1)
        self.assertTrue(all(job.status == "completed" for job in jobs))

    async def test_background_render_releases_queue_and_tracks_completion(self):
        video = self.queue.submit("render_video", {})
        other = self.queue.submit("scene_info", {})
        await asyncio.wait_for(self.queue.queue.join(), 2)
        self.assertEqual(video.status, "rendering")
        self.assertEqual(other.status, "completed")
        self.mcp.done = True
        await asyncio.wait_for(asyncio.gather(*self.queue.monitors), 3)
        self.assertEqual(video.status, "completed")
        self.assertEqual(video.result["data"]["status"], "done")
        self.assertEqual(self.mcp.peak, 1)

    async def test_cancel_has_a_terminal_state(self):
        video = self.queue.submit("render_video", {})
        await self.queue.queue.join()
        self.queue.submit("cancel_render", {"job_id": "video-1"})
        await self.queue.queue.join()
        self.assertEqual(video.status, "cancelled")
        self.assertIsNotNone(video.finished)

    async def test_film_background_progress_and_cancel(self):
        film = self.queue.submit("render_film", {"name": "Test"})
        await self.queue.queue.join()
        self.assertEqual(film.status, "rendering")
        self.queue.submit("cancel_render", {"job_id": "video-1"})
        await self.queue.queue.join()
        self.assertEqual(film.status, "cancelled")

    async def test_remote_cancel_waits_for_worker_cleanup(self):
        status_checked = asyncio.Event()
        cleaned = asyncio.Event()

        async def remote(name, arguments):
            if name == "render_status":
                if status_checked.is_set():
                    await cleaned.wait()
                    pending = False
                else:
                    pending = True
                    status_checked.set()
                result = {"job_id": "remote_123", "status": "cancelled", "cleanup_pending": pending}
            else:
                result = {"job_id": "remote_123", "status": "running"}
            return [SimpleNamespace(type="text", text=json.dumps(result))]

        self.mcp.call_tool = remote
        video = self.queue.submit("render_video", {"target": "remote"})
        await self.queue.queue.join()
        self.queue.submit("cancel_render", {"job_id": "remote_123"})
        await self.queue.queue.join()
        self.assertEqual(video.status, "rendering")
        await asyncio.wait_for(status_checked.wait(), 3)
        self.assertTrue(video.progress["cleanup_pending"])
        self.assertEqual(video.status, "rendering")
        cleaned.set()
        await asyncio.wait_for(asyncio.gather(*self.queue.monitors), 3)
        self.assertEqual(video.status, "cancelled")
        self.assertFalse(video.result["data"]["cleanup_pending"])

    async def test_film_build_progress_reads_manifest_without_engine_lock(self):
        job = self.queue.submit("script_to_film", {"script": "JUDUL: Test\nADEGAN: One\nA: Hello."})
        job.status, job.started = "running", 0
        path = Path(self.temp.name) / "projects/Test/film.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"scenes": [{"name": "One", "index": 1, "status": "building"}]}))
        self.assertEqual(self.queue.public(job)["progress"]["scenes"][0]["status"], "building")

    async def test_director_runs_outside_engine_lane_both_directions(self):
        blocked, started = asyncio.Event(), asyncio.Event()
        original = self.mcp.call_tool
        slow_tool = 'direct_scene'
        async def controlled(name, arguments):
            if name == slow_tool:
                started.set()
                await blocked.wait()
            return await original(name, arguments)
        self.mcp.call_tool = controlled
        director = self.queue.submit('direct_scene', {})
        await asyncio.wait_for(started.wait(), 1)
        engine = self.queue.submit('scene_info', {})
        await asyncio.wait_for(self.queue.queue.join(), 1)
        self.assertEqual(engine.status, 'completed')
        self.assertEqual(director.status, 'running')
        blocked.set()
        await asyncio.gather(*self.queue.independent)
        blocked.clear(); started.clear(); slow_tool = 'scene_info'
        engine = self.queue.submit('scene_info', {})
        await asyncio.wait_for(started.wait(), 1)
        director = self.queue.submit('direct_scene', {})
        await asyncio.wait_for(asyncio.gather(*self.queue.independent), 1)
        self.assertEqual(director.status, 'completed')
        self.assertEqual(engine.status, 'running')
        blocked.set()
        await self.queue.queue.join()


class SecurityTests(unittest.TestCase):
    def test_traversal_absolute_path_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            workspace = Workspace(root)
            (Path(root) / "escape").symlink_to(outside)
            for path in ("../escape", "/etc/passwd", "escape/file.wav"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    workspace.resolve(path)
            self.assertEqual(workspace.resolve("audio/line.wav", "imports"), Path(root) / "imports/audio/line.wav")

    def test_nested_audio_cannot_escape_and_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                Workspace(root).validate_arguments("script_to_scene", {"script": {"beats": [{"audio": "/etc/passwd"}]}})
        with patch.dict(os.environ, {"FAL_KEY": "private-fal", "HF_TOKEN": "private-hf", "ANTHROPIC_API_KEY": "private-claude"}):
            self.assertEqual(redact({"error": "private-fal private-hf private-claude", "HF_TOKEN": "anything", "ANTHROPIC_API_KEY": "anything"}),
                             {"error": "[RAHASIA] [RAHASIA] [RAHASIA]", "HF_TOKEN": "[RAHASIA]", "ANTHROPIC_API_KEY": "[RAHASIA]"})


if __name__ == "__main__":
    unittest.main()
