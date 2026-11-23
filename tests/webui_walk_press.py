"""Exercise the real Studio, Blender, and video playback across three staged previews."""

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import expect, sync_playwright


def call(page, base, tool, **arguments):
    start = page.request.post(f"{base}/api/run", headers={"Origin": base},
                              data={"tool": tool, "arguments": arguments})
    assert start.ok, start.text()
    return wait_job(page, base, start.json()["job_id"])["result"]["data"]


def wait_job(page, base, job_id):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        job = page.request.get(f"{base}/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            assert job["status"] == "completed", job
            return job
        time.sleep(.5)
    raise AssertionError(f"Studio job {job_id} did not finish within 300 seconds")


def create_actor(page, base, name, position, height):
    call(page, base, "create_human", name=name, style="realistic", height=height)
    rig = call(page, base, "auto_rig_humanoid", mesh=name, rig_type="basic")["armature"]
    call(page, base, "transform_object", name=rig, location=position, rotation_deg=[0, 0, 90])
    return rig


def preview(page, base, actor, button):
    panel = page.get_by_role("region", name="Jalan lalu tekan tombol")
    panel.locator("#walk-press-character").select_option(actor)
    panel.locator("#walk-press-button").select_option(button)
    before = call(page, base, "scene_info")
    with page.expect_response(lambda resp: resp.url == f"{base}/api/run" and
                                '"preview_walk_press"' in (resp.request.post_data or "")) as response:
        panel.get_by_role("button", name="Pratinjau aksi").click()
    job = wait_job(page, base, response.value.json()["job_id"])
    video = panel.locator("video")
    expect(video).to_be_visible(timeout=15000)
    page.wait_for_function("document.querySelector('#walk-press-player video')?.readyState >= 1")
    assert video.evaluate("(v) => v.duration") > 2
    assert call(page, base, "scene_info") == before, "Preview modified the working scene"
    result = job["result"]["data"]
    performance = result["performance"]
    assert performance["character"] == actor and performance["button"] == button
    assert performance["distance_m"] > .5
    assert performance["pressed_frame"] > performance["arrival_frame"]
    assert performance["contact_error_m"] < .002
    assert performance["foot_ik_error_m"] < .005
    return {"performance": performance, "video": result["path"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8794")
    parser.add_argument("--browser")
    parser.add_argument("--project")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=args.browser)
        page = browser.new_page(viewport={"width": 1365, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base, wait_until="networkidle")
        if args.project:
            call(page, base, "open_project", path=args.project)
            actor, button = "BUDI_rig", "Press button"
        else:
            call(page, base, "new_scene", fps=24)
            actor = create_actor(page, base, "Budi", [-1.65, -.42, 0], 1.75)
            button = call(page, base, "add_primitive", kind="cube", name="Tombol uji",
                          location=[.9, -.02, 1.015], size=.07)["name"]
        page.get_by_role("link", name="Adegan", exact=True).click()
        expect(page.get_by_role("region", name="Jalan lalu tekan tombol").locator("#walk-press-character")
               .locator(f'option[value="{actor}"]')).to_have_count(1)
        initial = preview(page, base, actor, button)
        print("FIRST", json.dumps(initial), flush=True)

        object_info = next(o for o in call(page, base, "scene_info")["objects"] if o["name"] == button)
        x, y, z = object_info["location"]
        call(page, base, "transform_object", name=button, location=[x + .21, y - .035, z])
        moved = preview(page, base, actor, button)
        print("MOVED", json.dumps(moved), flush=True)
        assert moved["performance"]["target"][0] - initial["performance"]["target"][0] > .18
        assert initial["performance"]["target"][1] - moved["performance"]["target"][1] > .03
        if not args.project:
            assert moved["performance"]["destination"] != initial["performance"]["destination"]

        objects = call(page, base, "scene_info")["objects"]
        retired = {actor}
        for obj in objects:
            if obj["parent"] in retired:
                retired.add(obj["name"])
        call(page, base, "delete_objects", names=sorted(retired))
        replacement = create_actor(page, base, "Raka", [-1.1, -.6, 0], 1.62)
        page.get_by_role("button", name="Sinkronkan").click()
        character = page.get_by_role("region", name="Jalan lalu tekan tombol").locator("#walk-press-character")
        expect(character.locator(f'option[value="{replacement}"]')).to_have_count(1, timeout=30000)
        swapped = preview(page, base, replacement, button)
        print("SWAPPED", json.dumps(swapped), flush=True)
        assert swapped["performance"]["target"] == moved["performance"]["target"]
        assert abs(swapped["performance"]["distance_m"] - moved["performance"]["distance_m"]) > .15
        assert len({initial["video"], moved["video"], swapped["video"]}) == 3
        assert not errors, errors
        if args.evidence:
            args.evidence.mkdir(parents=True, exist_ok=True)
            panel = page.get_by_role("region", name="Jalan lalu tekan tombol")
            panel.locator("video").evaluate("""(video) => new Promise((resolve) => {
                video.addEventListener("seeked", resolve, { once: true });
                video.currentTime = video.duration * .75;
            })""")
            panel.screenshot(path=args.evidence / "walk-press-studio.png")
            (args.evidence / "walk-press-checks.json").write_text(
                json.dumps([initial, moved, swapped], indent=2), encoding="utf-8")
        browser.close()


if __name__ == "__main__":
    main()
