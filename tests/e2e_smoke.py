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
# Test-only introspection: inspect the actual Blender animation curves, including
# sibling face meshes, to prove speech and blinks survive expression generation.
os.environ["CHAR3D_ALLOW_PYTHON"] = "1"
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


FACE_CURVES = '''
from engine.commands.face import _basemesh, _face_meshes
from engine.commands.talk import _fcurves
result = {}
for mesh in _face_meshes(_basemesh("Dani_rig")):
    sk = mesh.data.shape_keys
    action = sk.animation_data.action if sk.animation_data else None
    result[mesh.name] = {
        fc.data_path: [[list(k.co), k.interpolation] for k in fc.keyframe_points]
        for fc in _fcurves(action)
    }
'''


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        assert "char3d" in (init.instructions or ""), "server instructions missing"
        tools = {t.name for t in (await s.list_tools()).tools}
        print("tools:", sorted(tools))
        assert "auto_expression" in tools

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

            # Sentence emotions: bilingual phrases, negation, punctuation and real
            # MPFB shape keys. Compare protected curves before/after, not just reports.
            await call("set_expression", character="Dani_rig", expression="neutral",
                       frame=1, keyframe=True)
            ls3 = json.loads(text_of(await call(
                "lip_sync", character="Dani_rig", start_frame=12, chars_per_second=22,
                text="Senang sekali! Sayang sekali. Wow amazing! Saya kesal. "
                     "Takut bahaya. Hmm mungkin? Tidak senang."))[0])
            face_end = ls3["frames"][1] + 24
            await call("set_timeline", frame_end=face_end)
            await call("auto_blink", character="Dani_rig", frame_end=face_end)

            async def face_curves():
                return json.loads(text_of(await call("run_blender_python", code=FACE_CURVES))[0])["result"]

            before = await face_curves()
            ae = json.loads(text_of(await call("auto_expression", character="Dani_rig"))[0])
            emotions = [e["emotion"] for e in ae["sentences"]]
            assert emotions == ["joy", "sad", "surprise", "anger", "fear", "thinking", "neutral"], ae
            assert len(ae["meshes"]) >= 3 and ae["frames"] == [1, face_end], ae
            assert ae["sentences"][-1]["relax_frame"] is not None, ae
            for event in ae["sentences"]:
                peak, hold = event["frames"]
                assert 1 <= peak <= hold <= face_end, event
                assert abs(event["sentence_frames"][0] - peak - 5) <= 0.6, event
            assert ae["sentences"][0]["strength"] > ae["sentences"][3]["strength"], ae
            after = await face_curves()
            paths = {f'key_blocks["{name}"].value' for name in ae["keyed_units"]}
            protected = 0
            for mesh, curves in before.items():
                for path, points in curves.items():
                    if path not in paths:
                        assert after[mesh][path] == points, (mesh, path)
                        protected += 1
            assert protected > 20, protected
            # Re-running replaces its layer instead of accumulating old expression keys.
            await call("auto_expression", character="Dani_rig")
            assert await face_curves() == after
            await call("auto_blink", character="Dani_rig", frame_end=face_end)
            blinked = await face_curves()
            for mesh, curves in after.items():
                for path in curves.keys() & paths:
                    assert blinked[mesh][path] == curves[path], (mesh, path)

            # Check evaluated weights and visemes during speech, also on brows/lashes.
            check = '''
from engine.commands.face import _basemesh, _face_meshes, VISEMES
mesh = _basemesh("Dani_rig")
sk = mesh.data.shape_keys.key_blocks
samples = []
for event in EVENTS[:6]:
    bpy.context.scene.frame_set(event["frames"][0])
    unit = {"joy": "cheekSquintLeft", "sad": "browInnerUp",
            "surprise": "eyeWideLeft", "anger": "browDownLeft",
            "fear": "eyeWideLeft", "thinking": "browInnerUp"}[event["emotion"]]
    value = sk[unit].value
    assert value > 0.05, (event, unit, value)
    for part in _face_meshes(mesh):
        key = part.data.shape_keys.key_blocks.get(unit)
        if key is not None:
            assert abs(key.value - value) < 1e-5, (part.name, unit)
    samples.append(round(value, 3))
bpy.context.scene.frame_set(EVENTS[-1]["frames"][0])
assert sk["mouthSmileLeft"].value < 1e-5     # negated joy has no smile
bpy.context.scene.frame_set(EVENTS[-1]["relax_frame"])
assert abs(sk["mouthSmileLeft"].value - 0.7 * 0.35) < 1e-5  # back to base in pause
assert sk["browInnerUp"].value < 1e-5
assert any(fc.evaluate(f) > 0.1 for fc in _fcurves(mesh.data.shape_keys.animation_data.action)
           if any(v in fc.data_path for v in VISEMES) for f in range(12, END))
result = samples
'''
            checked = json.loads(text_of(await call("run_blender_python", code=(
                "from engine.commands.talk import _fcurves\nEVENTS = " + repr(ae["sentences"])
                + "\nEND = " + str(face_end) + "\n" + check)))[0])
            await call("set_lighting", preset="studio", subject=["Dani_rig"])
            await call("camera_shot", subject=["Dani_rig"], shot="close_up",
                       start_frame=1, end_frame=face_end)
            # Render inside each sentence, while the mouth is also speaking.
            view_frames = [round(sum(e["sentence_frames"]) / 2) for e in ae["sentences"][:6]]
            faces = await call("render_frames", frames=view_frames, camera="scene",
                               engine_name="eevee", size=512)
            assert [c.type for c in faces.content].count("image") == 6
            print("auto_expression:", emotions, "| protected curves", protected,
                  "| evaluated weights", checked["result"], "| close_up frames", view_frames)
            await call("save_project", path="e2e_auto_expression.blend")

            # Explicit cues work without word times and stay within the requested range.
            cue_start, cue_end = face_end + 10, face_end + 60
            cued = json.loads(text_of(await call(
                "auto_expression", character="Dani", frame_start=cue_start, frame_end=cue_end,
                base="neutral", cues=[{"frame": cue_start + 10, "expression": "sad", "strength": 0.8}]))[0])
            assert cued["sentences"][0]["source"] == "cue", cued
            assert cued["sentences"][0]["frames"][0] == cue_start + 10, cued
            limited = await face_curves()
            for mesh, curves in blinked.items():
                for path, points in curves.items():
                    assert ([p for p in limited[mesh][path] if p[0][0] <= face_end]
                            == [p for p in points if p[0][0] <= face_end]), (mesh, path)
            no_words = await s.call_tool("auto_expression", {"character": "Dani_rig",
                                        "frame_start": cue_end + 10, "frame_end": cue_end + 20})
            assert no_words.isError and "no word times" in str(text_of(no_words)), no_words
            forced = json.loads(text_of(await call(
                "auto_expression", character="Dani_rig",
                cues=[{"frame": ae["sentences"][0]["frames"][0], "expression": "sad", "strength": 0.9},
                      {"frame": ae["sentences"][0]["frames"][0] + 2,
                       "expression": "angry", "strength": 0.8}]))[0])
            assert forced["sentences"][0]["source"] == "cue", forced
            assert forced["sentences"][0]["expression"] == "sad", forced
            assert forced["sentences"][1]["source"] == "cue", forced
            assert forced["sentences"][1]["sentence"] == forced["sentences"][0]["sentence"], forced
            # Matcher edge cases exercise phrases, suffixes, language selection,
            # clause-scoped negation and the question-only fallback.
            lexicon = '''
from engine.commands.emotion import classify
def emotion(text, language="auto"):
    return classify([(w, i, i + 1) for i, w in enumerate(text.split())], language)[0]
for text, expected in [("Tidak senang.", "neutral"), ("not very happy!", "neutral"),
                       ("not sad but great!", "joy"), ("tidak marah, senang!", "joy"),
                       ("mantapnya!", "joy"), ("sayang sekali.", "sad"),
                       ("Unfortunately.", "sad"), ("coba pikir.", "thinking"),
                       ("Apa?", "thinking"), ("Hello.", "base")]:
    assert emotion(text) == expected, (text, emotion(text))
assert emotion("senang", "en") == "base"
assert emotion("seronok", "ms") == "joy"
assert emotion("happy", "en") == "joy"
result = "phrases, suffixes, negation, questions, id/ms/en OK"
'''
            lex = json.loads(text_of(await call("run_blender_python", code=lexicon))[0])
            print("auto_expression cues/ranges:", lex["result"])

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
                    text="Happy! Sorry. Wow! Afraid.", add_sound=False))[0])
                assert la["mode"] == timing and la["mouth_shapes"] >= 4, la
                if timing == "audio":
                    missing = await s.call_tool("auto_expression", {"character": "Vo_rig"})
                    assert missing.isError and "no word times" in str(text_of(missing)), missing
                else:
                    audio_face = json.loads(text_of(await call(
                        "auto_expression", character="Vo_rig", intensity=0.5,
                        base="neutral", base_strength=0, language="en"))[0])
                    assert [e["emotion"] for e in audio_face["sentences"]] == [
                        "joy", "sad", "surprise", "fear"], audio_face
                    assert audio_face["sentences"][0]["strength"] == 0.375, audio_face
            print("audio lip sync: audio/text modes OK")
            print("auto_expression audio: text timing + intensity OK; audio-only needs cues")
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
        v = json.loads(text_of(await call("render_video", path="e2e_audio.mp4", quality="draft",
                                          wait=True))[0])
        assert v["status"] == "done" and v["has_audio"], v
        import av
        with av.open(v["path"]) as c:
            kinds = sorted(st.type for st in c.streams)
        assert kinds == ["audio", "video"], kinds
        print("audio: strip + AAC video OK")

        guide = await s.read_resource("char3d://guide")
        assert "Working loop" in guide.contents[0].text
        await call("engine_shutdown")
        print("saved:", text_of(saved))
        print("E2E OK")


asyncio.run(main())
