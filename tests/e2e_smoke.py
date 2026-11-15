"""End-to-end check: real MCP client -> MCP server (stdio) -> Blender engine.

    .venv/bin/python tests/e2e_smoke.py
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CHAR3D_PORT", "9899")  # don't collide with a running engine
# keep the test's render-speed measurements out of the user's real calibration
CALIB = os.path.join(ROOT, "output", "e2e_render_speed.json")
os.environ["CHAR3D_RENDER_CALIB"] = CALIB
if os.path.exists(CALIB):
    os.remove(CALIB)


def _synthetic_speech(path, rate=22050):
    """Deterministic speech-like test signal: voiced vowels, a hiss and pauses."""
    import math
    import struct
    import wave
    import random
    rnd = random.Random(1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    formants = {"a": (750, 1200), "e": (500, 1900), "o": (450, 850), "i": (300, 2300)}
    plan = ["a", "e", None, "o", "s", "i", None, "a"]
    out = []
    for part in plan:
        n = int(rate * 0.35)
        if part is None:
            out += [0.0] * int(rate * 0.2)
            continue
        if part == "s":
            out += [rnd.uniform(-0.25, 0.25) for _ in range(n)]
            continue
        f1, f2 = formants[part]
        for k in range(n):
            t = k / rate
            env = math.sin(math.pi * k / n)
            src = sum(math.sin(2 * math.pi * 120 * h * t) / h for h in range(1, 30))
            out.append(0.3 * env * (0.6 * math.sin(2 * math.pi * f1 * t) + 0.4 * math.sin(2 * math.pi * f2 * t)
                                    + 0.15 * src / 3))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, x)) * 32000)) for x in out))
    return path


def text_of(res):
    return [c.text for c in res.content if c.type == "text"]


async def _graphics_checks(call):
    """Decode real draft movies to check graphics timing, mixing and exact frame counts."""
    import av
    import numpy as np

    def frames(path):
        with av.open(path) as movie:
            return [f.to_ndarray(format="rgb24") for f in movie.decode(video=0)]

    def save_png(path, pixels):
        with av.open(path, "w", format="image2") as image:
            stream = image.add_stream("png", rate=1)
            stream.width, stream.height = pixels.shape[1], pixels.shape[0]
            stream.pix_fmt = "rgb24"
            for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                image.mux(packet)
            for packet in stream.encode():
                image.mux(packet)

    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[0])

    async def video(path, start=1, end=48, **args):
        v = await data("render_video", path=path, quality="draft", width=640, height=360,
                       frame_start=start, frame_end=end, wait=True, **args)
        assert v["status"] == "done" and "warning" not in v, v
        decoded = frames(v["path"])
        assert len(decoded) == end - start + 1, (v, len(decoded))
        return v, decoded

    await call("new_scene", frame_end=48)
    await call("add_primitive", kind="monkey", name="Blue", location=[-2, 0, 1])
    await call("add_primitive", kind="cube", name="Orange", location=[2, 0, 1])
    await call("set_material", objects=["Blue"], color=[0.03, 0.2, 0.9])
    await call("set_material", objects=["Orange"], color=[0.95, 0.18, 0.02])
    await call("set_lighting", preset="studio", ground=False)
    await call("camera_shot", subject=["Blue"], shot="full", angle=0,
               start_frame=1, end_frame=24, name="BlueShot")
    await call("camera_shot", subject=["Orange"], shot="full", angle=30,
               start_frame=25, end_frame=48, name="OrangeShot")
    _, plain = await video("e2e_graphics_plain.mp4")
    await call("add_transition", kind="fade_in", duration_s=0.25, name="intro")
    await call("add_transition", shot="OrangeShot", duration_s=0.5, name="cut")
    await call("add_transition", kind="fade_out", duration_s=0.25, name="outro")
    await call("add_title", text="Reyhan", subtitle="Character artist", style="lower_third",
               start_s=0.25, duration_s=1.5, name="speaker")
    for args in ({"at_frame": 26}, {"shot": "BlueShot"},
                 {"at_frame": 25, "shot": "OrangeShot"},
                 {"at_frame": 25, "kind": "fade_black"}, {"duration_s": -1}):
        try:
            await call("add_transition", **args)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"invalid transition accepted: {args}")
    assert len((await data("list_graphics"))["graphics"]) == 4
    project = await data("save_project", path="e2e_graphics.blend")
    await call("remove_graphics", all=True)
    await call("open_project", path=project["path"])
    assert len((await data("list_graphics"))["graphics"]) == 4
    assert (await data("render_options", quality="draft"))["handle_frames"] == 12
    preview = await data("render_frames", frames=[17], camera="scene", size=320)
    assert preview["titles"] is True, preview
    title_image = frames(preview["path"])[0]
    bare = await data("render_frames", frames=[17], camera="scene", size=320, graphics=False)
    bare_image = frames(bare["path"])[0]
    assert np.abs(title_image.astype(float) - bare_image).mean() > 1
    # Captions, title and transitions must all survive the same composition pass.
    await call("add_subtitles", style="classic", position="top",
               lines=[{"text": "Graphics on the timeline", "start": 0.4, "end": 1.7}])
    v, mixed = await video("e2e_graphics.mp4")
    assert v["graphics"] == {"titles": 1, "transitions": 3, "handle_frames": 12}, v
    assert v["subtitles"]["captions"] == 1, v
    assert mixed[0].mean() < 3 and mixed[-1].mean() < 3, (mixed[0].mean(), mixed[-1].mean())
    assert mixed[7].mean() > 15
    roi = np.s_[65:110, 100:220, :]
    diff = lambda a, b: np.abs(a[roi].astype(float) - b[roi]).mean()
    # Full outgoing camera at the cut, both pictures halfway, incoming at the end.
    assert diff(mixed[24], plain[23]) < 6, diff(mixed[24], plain[23])
    assert diff(mixed[29], plain[29]) > 8 and diff(mixed[29], plain[23]) > 8
    assert diff(mixed[35], plain[35]) < 6, diff(mixed[35], plain[35])
    tag_roi = np.s_[125:165, 15:95, :]
    tag_diff = lambda i: np.abs(mixed[i][tag_roi].astype(float) - plain[i][tag_roi]).mean()
    assert tag_diff(6) < 4 and tag_diff(13) > 5 and tag_diff(41) < 4
    for frame in (1, 17, 25, 30, 36, 48):
        save_png(os.path.join(ROOT, "output", "renders", f"e2e_graphics_f{frame:04d}.png"), mixed[frame - 1])
    _, cropped = await video("e2e_graphics_crop.mp4", start=29, end=38)
    assert diff(cropped[0], mixed[28]) < 6, diff(cropped[0], mixed[28])
    await call("remove_subtitles")
    await call("remove_graphics", name="speaker")
    # Color dips and their alias, plus non-1 scene starts, must use local movie frames.
    await call("set_timeline", frame_start=5)
    for kind in ("fade_black", "fade_white", "dip_black"):
        await call("remove_graphics", all=True)
        await call("add_transition", at_frame=25, kind=kind, duration_s=0.5, name="dip")
        _, dipped = await video(f"e2e_{kind}.mp4", start=19, end=30, subtitles=False)
        mean = dipped[6].mean()  # scene frame 25: exact color at the cut
        assert mean > 250 if kind == "fade_white" else mean < 3, (kind, mean)
    await call("remove_graphics", name="all")
    await call("add_transition", kind="fade_in", duration_s=0.25)
    _, fade_only = await video("e2e_fade_only.mp4", start=5, end=10)
    assert fade_only[0].mean() < 3 and fade_only[-1].mean() > 15
    await call("remove_graphics", all=True)
    for style in ("center", "corner"):
        await call("add_title", text="A new chapter", subtitle="Video graphics", style=style,
                   name="card", animation="fade" if style == "center" else "none",
                   start_s=0, duration_s=1)
        result = await data("render_frames", frames=[17], camera="scene", size=320)
        assert result["titles"] is True
    # Title-only composition, with captions disabled, no transition trigger to hide bugs.
    assert len((await data("list_graphics"))["graphics"]) == 1
    _, titled = await video("e2e_title_only.mp4", start=17, end=18, subtitles=False)
    assert np.abs(titled[0].astype(float) - plain[16]).mean() > 1
    assert (await data("remove_graphics", all=True))["graphics"] == []
    print("graphics: 48/48 frames | fade in/out black | crossfade 12 handles | lower third + captions | crop + color dips + title-only OK")


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        assert "char3d" in (init.instructions or ""), "server instructions missing"
        tools = {t.name for t in (await s.list_tools()).tools}
        print("tools:", sorted(tools))

        async def call(tool, **args):
            res = await s.call_tool(tool, args)
            if res.isError:
                raise RuntimeError(f"{tool} failed: {text_of(res)}")
            return res

        print("status:", text_of(await call("engine_status")))
        await call("new_scene")
        await call("add_primitive", kind="monkey", name="Hero", location=[0, 0, 1])
        await call("transform_object", name="Hero", rotation_deg=[0, 0, 0])
        exp = json.loads(text_of(await call("export_asset", path="e2e_hero.glb", objects=["Hero"]))[0])
        await call("new_scene")
        imp = json.loads(text_of(await call("import_model", path=exp["path"]))[0])
        assert imp["imported"][0]["name"] == "Hero", imp
        prev = await call("render_preview", view="front", width=256, height=256)
        kinds = [c.type for c in prev.content]
        assert "image" in kinds, kinds
        sheet = await call("render_views", views=["front", "right"], size=128)
        assert [c.type for c in sheet.content].count("image") == 2
        saved = await call("save_project", path="e2e.blend")
        # phase 2: character -> rig -> pose -> export
        await call("new_scene")
        await call("create_human", name="Hero", style="stylized")
        for rig_type in ("basic", "rigify"):
            rep = json.loads(text_of(await call("auto_rig_humanoid", mesh="Hero",
                                                rig_type=rig_type))[0])
            assert rep["ok"] and rep["unweighted_vertices"] == 0, rep
            assert rep["max_influences"] <= 4, rep
        await call("set_pose", armature="Hero_rig",
                   bones={"upper_arm_fk.L": [0, 0, 60], "shin_fk.R": [-45, 0, 0]})
        posed = await call("render_preview", view="three_quarter", width=256, height=256)
        assert "image" in [c.type for c in posed.content]
        glb = json.loads(text_of(await call("export_asset", path="e2e_hero_rigged.glb"))[0])
        assert glb["bytes"] > 10000, glb
        print("phase 2 rig:", rep["rig_type"], rep["deform_bones"], "deform bones")

        # phase 3: poses, clips, chaining, BVH round-trip mocap, animated glb
        await call("new_scene")
        await call("create_human", name="Walker", style="stylized")
        await call("auto_rig_humanoid", mesh="Walker")
        w = json.loads(text_of(await call("animate", armature="Walker_rig", clip="walk", cycles=1))[0])
        a = json.loads(text_of(await call("animate", armature="Walker_rig", clip="wave",
                                          start_frame=w["next_start_frame"], cycles=1))[0])
        assert a["frames"][0] == w["frames"][1] + 1, (w, a)
        fl = w["foot_lock"]["contacts"]
        assert fl["L"] and fl["R"], w
        assert a["crossfade"]["blend_frames"] >= 4, a      # wave blends in from the walk
        assert a["foot_lock"]["contacts"]["L"], a          # feet planted through the blend
        cut = json.loads(text_of(await call("animate", armature="Walker_rig", clip="nod",
                                            start_frame=a["next_start_frame"], cycles=1,
                                            blend_frames=0))[0])
        assert "crossfade" not in cut, cut
        lk = json.loads(text_of(await call("lock_feet", armature="Walker_rig", frame_start=1,
                                           frame_end=w["frames"][1]))[0])
        assert lk["feet"]["L"]["contacts"] and lk["max_ik_error_m"] < 0.01, lk
        bvh = json.loads(text_of(await call("export_asset", path="e2e_walk.bvh",
                                            objects=["Walker_rig"]))[0])
        await call("create_human", name="Pro", style="realistic", location=[2, 0, 0])
        await call("auto_rig_humanoid", mesh="Pro", rig_type="rigify")
        await call("apply_pose", armature="Pro_rig", pose="cheer")
        mo = json.loads(text_of(await call("import_mocap", path=bvh["path"], armature="Pro_rig",
                                           start_frame=1))[0])
        assert mo["bones"] >= 18, mo
        assert mo["foot_lock"]["contacts"]["L"] and mo["foot_lock"]["contacts"]["R"], mo
        frames = await call("render_frames", frames=[1, 9], view="right", size=128, objects=["Pro"])
        assert [c.type for c in frames.content].count("image") == 2
        anim_glb = json.loads(text_of(await call("export_asset", path="e2e_walker.glb",
                                                 objects=["Walker_rig"]))[0])
        import struct
        raw = open(anim_glb["path"], "rb").read()
        gltf = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
        assert len(gltf.get("animations", [])) == 1, gltf.get("animations")
        print("phase 3: mocap bones", mo["bones"], "| glb animations", len(gltf["animations"]),
              "| foot contacts", fl)

        # phase 4: lighting, two shots, scene-camera check, draft video
        await call("set_lighting", preset="studio", subject=["Walker"])
        s1 = json.loads(text_of(await call("camera_shot", subject=["Walker"], shot="full",
                                           move="tracking_side", start_frame=1, end_frame=20))[0])
        await call("camera_shot", subject=["Walker"], shot="medium", move="crash_zoom",
                   start_frame=s1["next_start_frame"], end_frame=36)
        shots = json.loads(text_of(await call("list_shots"))[0])["shots"]
        assert [x["camera"] for x in shots][:2] == ["Shot1", "Shot2"], shots
        look = await call("render_frames", frames=[1, 30], camera="scene", size=160)
        assert [c.type for c in look.content].count("image") == 2
        vid = json.loads(text_of(await call("render_video", path="e2e.mp4", quality="draft",
                                            frame_start=1, frame_end=36, wait=True))[0])
        assert vid["status"] == "done" and vid["bytes"] > 1000, vid
        opts = json.loads(text_of(await call("render_options", quality="final", vertical=True))[0])
        sizes = {o["resolution"]: o["size"] for o in opts["options"]}
        assert sizes["1080p"] == "1080x1920" and sizes["4k"] == "2160x3840", opts
        times = [o["total_s"] for o in opts["options"]]
        assert times == sorted(times) and times[0] > 0, opts
        vid2 = json.loads(text_of(await call("render_video", path="e2e_480.mp4", quality="draft",
                                             resolution="480p", frame_start=1, frame_end=6,
                                             wait=True))[0])
        assert vid2["status"] == "done" and vid2["size"] == [854, 480], vid2
        # subtitles: explicit lines -> preview frame with caption, burned-in video + .srt
        sub = json.loads(text_of(await call("add_subtitles", style="tiktok", lines=[
            {"text": "Halo semua, ini tes subtitle.", "start": 0.1, "end": 1.4}]))[0])
        assert sub["captions"] == 2 and sub["preview"][0]["text"] == "Halo semua,", sub
        capf = await call("render_frames", frames=[8], camera="scene", size=200)
        assert json.loads(text_of(capf)[0])["caption"] is True
        vs = json.loads(text_of(await call("render_video", path="e2e_subs.mp4", quality="draft",
                                           frame_start=1, frame_end=36, wait=True))[0])
        assert vs["status"] == "done" and vs["subtitles"]["captions"] == 2, vs
        assert "warning" not in vs and os.path.exists(vs["subtitles"]["srt"]), vs
        import av
        with av.open(vs["path"]) as mv:
            assert mv.streams.video[0].frames == 36, mv.streams.video[0].frames
        await call("remove_subtitles")
        # speed calibration: finished renders teach workbench speed, a test frame eevee
        assert vid["learned_speed"]["engine"] == "workbench", vid
        cal = json.loads(text_of(await call("render_options", quality="preview",
                                            calibrate=True))[0])
        assert cal["test_frame"]["engine"] == "eevee" and cal["test_frame"]["measured_s"] > 0, cal
        assert cal["machine_speed"]["measurements"] >= 1, cal
        speeds = json.load(open(CALIB))
        assert {"workbench", "eevee"} <= set(speeds), speeds
        print("phase 4: shots", len(shots), "| video", vid["progress"], vid["bytes"], "bytes",
              "| options final 1080p", next(o["total"] for o in opts["options"]
                                            if o["resolution"] == "1080p"),
              "| test frame", cal["test_frame"], "| preview 1080p",
              next(o["total"] for o in cal["options"] if o["resolution"] == "1080p"))
        await _graphics_checks(call)

        # realistic humans (skipped when MPFB is not installed)
        mp = await s.call_tool("mpfb_assets", {})
        if mp.isError:
            print("mpfb: not installed, skipped")
        else:
            await call("new_scene")
            h = json.loads(text_of(await call("create_realistic_human", name="Rina", gender=0.0,
                                              age=30, hair="ponytail01",
                                              clothes=["female_sportsuit01", "shoes03"]))[0])
            assert h["armature"] == "Rina_rig" and h["mapped_bones"] >= 20, h
            vr = json.loads(text_of(await call("validate_rig", mesh="Rina"))[0])
            assert vr["unweighted_vertices"] == 0, vr
            an = json.loads(text_of(await call("animate", armature="Rina_rig", clip="wave",
                                               cycles=1))[0])
            assert an["via"] == "proxy-retarget", an
            img = await call("render_preview", objects=["Rina_rig"], width=160, height=160)
            assert "image" in [c.type for c in img.content]
            print("mpfb:", h["skin"], h["height_m"], "m,", len(h["parts"]), "parts, wave OK")
            # Rigify + face: expression, lip sync, blink
            await call("new_scene")
            d = json.loads(text_of(await call("create_realistic_human", name="Dani", gender=1.0,
                                              age=28, rig="rigify"))[0])
            assert d["face_rig"] and any("teeth" in p for p in d["parts"]), d
            vr = json.loads(text_of(await call("validate_rig", mesh="Dani"))[0])
            assert vr["ok"] and vr["rig_type"] == "rigify", vr
            ex = json.loads(text_of(await call("set_expression", character="Dani_rig",
                                               expression="laugh", frame=1, keyframe=True))[0])
            assert ex["active_units"].get("jawOpen", 0) > 0 and len(ex["meshes"]) >= 3, ex
            ls = json.loads(text_of(await call("lip_sync", character="Dani_rig",
                                               text="Halo semuanya", start_frame=5))[0])
            assert ls["mouth_shapes"] >= 8 and ls["next_start_frame"] > 20, ls
            bl = json.loads(text_of(await call("auto_blink", character="Dani_rig",
                                               frame_start=1, frame_end=200))[0])
            assert len(bl["blinks"]) >= 1, bl
            an = json.loads(text_of(await call("animate", armature="Dani_rig", clip="nod",
                                               cycles=1))[0])
            assert an["via"] == "proxy-retarget", an
            print("mpfb rigify+face:", vr["bones_total"], "bones,", len(ex["meshes"]),
                  "face meshes, lip sync", ls["mouth_shapes"], "shapes")

        # audio: synthetic "speech" (vowels via formant filters, hiss, pauses) -> timeline,
        # lip sync from audio/text, and a draft video that must carry an AAC track
        wav = _synthetic_speech(os.path.join(ROOT, "output", "imports", "audio", "e2e_synth.wav"))
        await call("new_scene")
        await call("add_primitive", kind="monkey", name="Mic")
        mp = await s.call_tool("mpfb_assets", {})
        if not mp.isError:
            await call("create_realistic_human", name="Vo", gender=0.0, age=30, location=[1, 0, 0])
            for timing in ("audio", "text"):
                la = json.loads(text_of(await call(
                    "lip_sync_audio", character="Vo_rig", audio=wav, timing=timing,
                    text="aa ee oo ss aa", add_sound=False))[0])
                assert la["mode"] == timing and la["mouth_shapes"] >= 4, la
            print("audio lip sync: audio/text modes OK")
            await call("add_audio", path=wav, start_frame=1)
            await call("animate", armature="Vo_rig", clip="idle", cycles=1)
            await call("camera_shot", subject=["Vo_rig"], shot="close_up", start_frame=1,
                       end_frame=60)
            tm = json.loads(text_of(await call("talk_motion", character="Vo_rig",
                                               frame_start=1, frame_end=60))[0])
            assert tm["driven_by"].startswith("audio:") and tm["saccades"] >= 1, tm
            rng = tm["head_range_deg"]
            assert max(abs(v) for pair in rng.values() for v in pair) < 25, rng
            print("talk_motion:", tm["driven_by"], "emphasis", len(tm["emphasis_frames"]),
                  "saccades", tm["saccades"])
            tg = json.loads(text_of(await call("talk_gestures", character="Vo_rig",
                                               frame_start=1, frame_end=60,
                                               style="energetic"))[0])
            assert tg["talking_frames"] > 10 and len(tg["arm_bones"]) == 4, tg
            assert tg["finger_bones"] == 30, tg
            hp = json.loads(text_of(await call("set_hand_pose", character="Vo_rig", shape="point",
                                               side="right", frame=70, keyframe=True))[0])
            assert hp["bones"] == 15 and hp["keyed"], hp
            print("talk_gestures (MPFB):", [g["type"] for g in tg["gestures"]])
            # meaning gestures from stored word times (lip_sync text)
            ls2 = json.loads(text_of(await call(
                "lip_sync", character="Vo_rig", start_frame=1,
                text="Saya punya dua ide besar, dan ini tidak sulit."))[0])
            tgs = json.loads(text_of(await call("talk_gestures", character="Vo_rig",
                                                frame_start=1, frame_end=ls2["frames"][1]))[0])
            kinds = [g["type"] for g in tgs["semantic"]]
            assert tgs["words_known"] >= 9 and "two" in kinds, tgs
            assert tgs["hand_bones"] == ["hand_l", "hand_r"] and tgs["max_palm_twist_deg"] > 10, tgs
            print("talk_gestures semantic:", [(g["word"], g["type"]) for g in tgs["semantic"]])
            await call("remove_audio")
        aa = json.loads(text_of(await call("add_audio", path=wav, start_frame=1))[0])
        assert aa["seconds"] > 2, aa
        await call("create_human", name="Mq", style="stylized", location=[-1.2, 0, 0])
        await call("auto_rig_humanoid", mesh="Mq", rig_type="rigify")
        tgm = json.loads(text_of(await call("talk_gestures", character="Mq_rig",
                                            frame_start=1, frame_end=50))[0])
        assert tgm["talking_frames"] > 10, tgm
        print("talk_gestures (rigify mannequin):", tgm["arm_bones"])
        tgc = json.loads(text_of(await call("talk_gestures", character="Mq_rig", frame_start=1,
                                            frame_end=50, semantic=False,
                                            cues=[{"frame": 25, "gesture": "stop"}]))[0])
        assert [g["type"] for g in tgc["semantic"]] == ["stop"], tgc
        print("talk_gestures cue on mannequin OK")
        await call("camera_shot", shot="medium", start_frame=1, end_frame=aa["frames"][1])
        await call("add_title", text="Audio + graphics", style="corner", duration_s=2)
        await call("add_transition", kind="fade_in", duration_s=0.25)
        v = json.loads(text_of(await call("render_video", path="e2e_audio.mp4", quality="draft",
                                          wait=True))[0])
        assert v["status"] == "done" and v["has_audio"], v
        import av
        with av.open(v["path"]) as c:
            kinds = sorted(st.type for st in c.streams)
        assert kinds == ["audio", "video"], kinds
        assert v["graphics"]["titles"] == 1 and v["graphics"]["transitions"] == 1, v
        print("audio: strip + AAC video with graphics OK")

        guide = await s.read_resource("char3d://guide")
        assert "Working loop" in guide.contents[0].text
        await call("engine_shutdown")
        print("saved:", text_of(saved))
        print("E2E OK")


if __name__ == "__main__":
    asyncio.run(main())
