"""Offline unit checks: .venv/bin/python tests/test_tts.py (no Blender/network)."""
import asyncio
import importlib.machinery
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.script_plan import parse_script
from providers.tts import TTS, cache_key, controls, online_request, parse_voice
from providers.tts import audio
from providers.tts.edge import Backend as Edge
from providers.tts.f5 import Backend as F5


def tone(rate=22050, seconds=1, hz=220):
    t = np.arange(round(rate * seconds)) / rate
    return np.sin(2 * np.pi * hz * t) * .2


class FakeBackend:
    online = False
    license = "test"
    calls = 0

    def available(self):
        return True

    def voices(self, language=None):
        return [{"id": "piper:test", "language": "id", "gender": "variant", "installed": True}]

    def install_hint(self):
        return "scripts/install_tts.sh piper"

    def synthesize(self, text, voice, language, rate, pitch, out_path):
        self.calls += 1
        return audio.write(out_path, np.pad(tone(), (2205, 4410)), 22050)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = TTS(self.temp.name, self.temp.name)

    def test_specs_and_invalid_controls(self):
        self.assertEqual(parse_voice("edge:id-ID-GadisNeural"), ("edge", "id-ID-GadisNeural"))
        self.assertEqual(parse_voice("piper:id_ID-news_tts-medium"), ("piper", "id_ID-news_tts-medium"))
        self.assertEqual(parse_voice("f5:Ana"), ("f5", "Ana"))
        for args in [("unknown:voice",), ("edge:",), (12,)]:
            with self.assertRaises(ValueError):
                parse_voice(*args)
        for rate, pitch in [(0, 0), (float("nan"), 0), (1, float("inf")), (1, 13)]:
            with self.assertRaises(ValueError):
                controls(rate, pitch)

    def test_casting_deterministic_distinct_and_never_implicit_edge(self):
        self.service.backends["piper"] = FakeBackend()
        chars = [{"id": name, "gender": gender, "age": age} for name, gender, age in
                 [("Ana", 0, 25), ("Maya", 0, 25), ("Budi", 1, 65), ("Anak", 0, 10)]]
        a = self.service.cast(chars, seed=42)
        self.assertEqual(a, self.service.cast(chars, seed=42))
        self.assertNotEqual(a, self.service.cast(chars, seed=43))
        self.assertEqual(len({(v["voice"], v["pitch"], v["rate"]) for v in a.values()}), 4)
        self.assertTrue(all(v["engine"] == "piper" and not v["online"] for v in a.values()))
        edge = self.service.cast(chars, engine="edge")
        self.assertEqual(edge["Ana"]["voice"], "edge:id-ID-GadisNeural")
        self.assertEqual(edge["Budi"]["voice"], "edge:id-ID-ArdiNeural")
        self.assertNotEqual(edge["Ana"]["pitch"], edge["Maya"]["pitch"])
        explicit = self.service.cast(chars, overrides={"Ana": {"voice": "edge:id-ID-ArdiNeural", "pitch": 1, "rate": 1.1}})
        self.assertEqual(explicit["Ana"]["pitch"], 1)
        self.assertEqual(explicit["Ana"]["voice"], "edge:id-ID-ArdiNeural")

    def test_cache_key_all_inputs_and_no_plaintext_name(self):
        values = ["piper", "test", "Halo!", "id", 1, 0, "v1"]
        base = cache_key(*values)
        self.assertEqual(len(base), 64)
        self.assertEqual(base, cache_key(*values))
        for i, value in enumerate(values):
            changed = values.copy()
            changed[i] = value + 1 if isinstance(value, (int, float)) else value + "x"
            self.assertNotEqual(base, cache_key(*changed))

    def test_cache_normalized_reuse_and_output_boundary(self):
        backend = FakeBackend()
        self.service.backends["piper"] = backend
        a = self.service.synthesize("Halo", voice="piper:test")
        b = self.service.synthesize("Halo", voice="piper:test", output="audio/copy.wav")
        self.assertFalse(a["cached"])
        self.assertTrue(b["cached"])
        self.assertEqual(backend.calls, 1)
        self.assertEqual((Path(self.temp.name) / "imports" / a["path"]).read_bytes(),
                         (Path(self.temp.name) / "imports" / b["path"]).read_bytes())
        with wave.open(str(Path(self.temp.name) / "imports" / b["path"])) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (48000, 1, 2))
        for path in ("../../escape.wav", "/tmp/escape.wav", "audio/test.mp3"):
            with self.assertRaises(ValueError):
                self.service.synthesize("Halo", voice="piper:test", output=path)

    def test_missing_piper_model_hint_and_no_online_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "scripts/install_tts.sh piper"):
            self.service.synthesize("Halo")
        casting = self.service.cast([{"id": "Ana"}])
        with patch.object(self.service.backends["edge"], "synthesize", side_effect=AssertionError("online!")):
            lines, report = self.service.prepare([{"say": "Ana", "text": "Halo"}], casting)
        self.assertNotIn("audio", lines[0])
        self.assertIn("scripts/install_tts.sh piper", report["warnings"][0])
        self.assertFalse((Path(self.temp.name) / "imports").exists())

    def test_existing_audio_wins_and_failed_backend_does_not_fallback(self):
        self.service.backends["piper"] = FakeBackend()
        casting = self.service.cast([{"id": "Ana"}])
        original = [{"say": "Ana", "text": "Halo", "audio": "my.wav"}]
        lines, report = self.service.prepare(original, casting)
        self.assertEqual(original, lines)
        self.assertEqual(report["generated_files"], [])

    def test_descriptors_preserve_case_and_hints(self):
        p = parse_script("ANA (perempuan, 28, suara: edge:id-ID-GadisNeural): Halo!\nBUDI (laki-laki, 60, suara berat): Ya.")
        self.assertEqual(p["characters"][0]["voice"], "edge:id-ID-GadisNeural")
        self.assertEqual(p["characters"][1]["pitch_offset"], -3)
        self.assertFalse(p["warnings"], p["warnings"])
        p = parse_script("ANA (female, 28, voice: piper:id_ID-news_tts-medium, high voice): Hi!")
        self.assertEqual(p["characters"][0]["pitch_offset"], 3)
        self.assertEqual(p["characters"][0]["age"], 28)

    def test_hints_shift_cast_and_limits_stay_distinct(self):
        old = [{"id": n, "gender": 1, "age": 75, "pitch_offset": -3} for n in ("A", "B", "C")]
        cast = self.service.cast(old + [{"id": "D", "gender": 0, "age": 30}], "piper")
        pitches = [cast[n]["pitch"] for n in "ABC"]
        self.assertTrue(all(-12 <= p <= 12 for p in pitches), pitches)
        self.assertEqual(len({round(p) for p in pitches}), 3)
        plain = self.service.cast([{"id": "D", "gender": 0, "age": 30}], "piper")["D"]["pitch"]
        hinted = self.service.cast([{"id": "D", "gender": 0, "age": 30, "pitch_offset": -3}],
                                   "piper")["D"]["pitch"]
        self.assertAlmostEqual(hinted, plain - 3, places=1)

    def test_catalog_default_never_refreshes_online(self):
        with patch.object(self.service.backends["edge"], "voices", wraps=self.service.backends["edge"].voices) as voices:
            catalog = self.service.catalog("id")
            voices.assert_called_once_with("id", refresh=False)
        self.assertEqual(set(catalog["engines"]), {"piper", "edge", "f5", "chatterbox"})
        self.assertIn("license", catalog["engines"]["f5"])

    def test_installed_other_piper_language_and_speakers(self):
        folder = Path(self.temp.name) / "piper"
        folder.mkdir()
        (folder / "en_US-example-medium.onnx").touch()
        (folder / "en_US-example-medium.onnx.json").write_text(json.dumps({
            "language": {"code": "en_US"}, "speaker_id_map": {"alice": 0, "bob": 1}}))
        backend = self.service.backends["piper"]
        self.assertEqual([v["id"] for v in backend.voices("en")],
                         ["piper:en_US-example-medium#alice", "piper:en_US-example-medium#bob"])
        self.assertEqual(backend.model_path("en_US-example-medium#bob").name, "en_US-example-medium.onnx")

    def test_consent_covers_text_dict_overrides_and_parse_only(self):
        text = "ANA (perempuan, suara: edge:id-ID-GadisNeural): Halo!"
        for script in [text, {"characters": [{"id": "Ana", "voice": "edge:id-ID-GadisNeural"}],
                               "beats": [{"say": "Ana", "text": "Halo"}]}]:
            self.assertTrue(online_request("script_to_scene", {"script": script}))
            self.assertFalse(online_request("script_to_scene", {"script": script, "build": False}))
            self.assertFalse(online_request("script_to_scene", {"script": script, "voice": False}))
        self.assertTrue(online_request("text_to_speech", {"voice": "edge:id-ID-ArdiNeural"}))
        self.assertFalse(online_request("text_to_speech", {}))
        self.assertFalse(online_request("dialog", {"tts_engine": "edge"}))
        self.assertTrue(online_request("dialog", {"voice": True, "voices": {"Ana": "edge:id-ID-GadisNeural"}}))


class AudioTests(unittest.TestCase):
    def test_pitch_frequency_duration_and_no_clicks(self):
        x = tone(seconds=1.5)
        for semitones in (-4, 4):
            y = audio.pitch_shift(x, semitones)
            self.assertEqual(len(y), len(x))
            middle = y[3000:-3000]
            fft = np.abs(np.fft.rfft(middle * np.hanning(len(middle))))
            peak = np.fft.rfftfreq(len(middle), 1 / 22050)[np.argmax(fft)]
            self.assertLess(abs(peak / (220 * 2 ** (semitones / 12)) - 1), .015)
            self.assertLess(np.max(np.abs(np.diff(y))), .09)

    def test_large_voice_shift_reaches_male_f0_with_stable_duration(self):
        # Glottal-like pulse train through a vowel-ish resonance: a 250 Hz "female" source.
        rate, hz = 22050, 250.
        t = np.arange(rate * 2) / rate
        pulses = (np.sin(2 * np.pi * hz * t) > .995).astype(float)
        kernel = np.exp(-np.arange(200) / 40.) * np.sin(2 * np.pi * 700 * np.arange(200) / rate)
        x = np.convolve(pulses, kernel)[:len(t)] * .3
        self.assertLess(abs(audio.median_f0(x, rate) / hz - 1), .03)
        for semitones in (-11, -6, 3):
            y = audio.pitch_shift(x, semitones, rate)
            self.assertEqual(len(y), len(x))
            self.assertLess(abs(audio.median_f0(y, rate) / (hz * 2 ** (semitones / 12)) - 1), .04)

    def test_casting_targets_typical_f0_by_gender_and_age(self):
        from providers.tts import target_f0
        self.assertLess(target_f0(1, 40), 130)
        self.assertGreater(target_f0(0, 30), 200)
        self.assertGreater(target_f0(0, 8), target_f0(0, 30))
        self.assertLess(target_f0(1, 70), target_f0(1, 30))
        self.assertLess(target_f0(.5, 30), target_f0(0, 30))
        self.assertGreater(target_f0(.5, 30), target_f0(1, 30))

    def test_normalization_trim_fades_peak_and_loudness(self):
        for gain in (.05, 1, 5):
            x = np.pad(tone(rate=48000) * gain, (24000, 48000))
            y = audio.normalize(x)
            self.assertLess(np.max(np.abs(y)), .9)
            self.assertLess(abs(len(y) / 48000 - 1.08), .03)
            self.assertLess(abs(np.sqrt(np.mean(y[3000:-3000] ** 2)) - .12), .01)
            self.assertEqual(y[0], 0)
            self.assertEqual(y[-1], 0)
            self.assertLess(np.max(np.abs(np.diff(y))), .03)
        with self.assertRaisesRegex(ValueError, "silent"):
            audio.normalize(np.zeros(1000))


class BackendTests(unittest.TestCase):
    def test_edge_mock_success_privacy_and_failure(self):
        calls = []
        class Communicate:
            def __init__(self, text, voice, **kwargs):
                calls.append((text, voice, kwargs))
            async def save(self, path):
                audio.write(path, tone(), 22050)
        module = ModuleType("edge_tts")
        module.Communicate = Communicate
        module.__spec__ = importlib.machinery.ModuleSpec("edge_tts", loader=None)
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"edge_tts": module}):
            service = TTS(folder)
            r = service.synthesize("Halo", "edge:id-ID-GadisNeural", rate=1.1, pitch=2)
            self.assertIn("Microsoft", r["privacy"])
            self.assertEqual(calls[0][2]["rate"], "+10%")
            self.assertTrue(service.synthesize("Halo", "edge:id-ID-GadisNeural", rate=1.1, pitch=2)["cached"])
            with patch.object(Communicate, "save", new=AsyncMock(side_effect=OSError("network secret"))):
                with self.assertRaisesRegex(RuntimeError, "no engine fallback"):
                    service.synthesize("Different", "edge:id-ID-GadisNeural")

    def test_f5_lazy_local_mock_reference_and_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = F5(folder)
            self.assertFalse(backend.available())
            with self.assertRaisesRegex(RuntimeError, "f5 --yes"):
                backend.synthesize("Halo", "Ana", "id", 1, 0, Path(folder) / "x.wav")
            for file in ("model.safetensors", "vocab.txt", "vocos/config.yaml", "vocos/pytorch_model.bin"):
                dest = Path(folder) / "f5" / file
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.touch()
            voices = Path(folder) / "f5/voices"
            voices.mkdir()
            audio.write(voices / "ref.wav", tone(), 22050)
            (voices / "Ana.json").write_text(json.dumps({"voice_reference": "ref.wav", "reference_text": "Suara saya"}))
            calls = []
            class F5TTS:
                def __init__(self, **kwargs): calls.append(kwargs)
                def infer(self, **kwargs):
                    calls.append(kwargs)
                    return tone(), 22050, None
            module = ModuleType("f5_tts")
            module.__spec__ = importlib.machinery.ModuleSpec("f5_tts", loader=None)
            api = ModuleType("f5_tts.api")
            api.F5TTS = F5TTS
            with patch.dict(sys.modules, {"f5_tts": module, "f5_tts.api": api}):
                self.assertTrue(backend.available())
                self.assertEqual(backend.voices()[0]["id"], "f5:Ana")
                result = backend.synthesize("Halo", "Ana", "id", 1.1, 0, Path(folder) / "out.wav")
                self.assertEqual(result["sample_rate"], 22050)
                self.assertIn(folder, calls[0]["ckpt_file"])
                self.assertIn(folder, calls[0]["vocoder_local_path"])
                self.assertEqual(calls[1]["ref_text"], "Suara saya")
                self.assertEqual(calls[1]["speed"], 1.1)


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_dialog_opt_in_and_generated_text_skips_asr(self):
        from mcp_server import server
        with tempfile.TemporaryDirectory() as folder:
            service = TTS(folder, folder)
            service.backends["piper"] = FakeBackend()
            run = AsyncMock(return_value={"warnings": [], "lines": [], "frames": [1, 24]})
            lines = [{"speaker": "Ana_rig", "text": "Halo"}]
            with patch.object(server, "tts", service), patch.object(server, "run", run), patch.object(server.speech, "transcribe", side_effect=AssertionError("ASR")):
                result = await server.dialog(lines)
                self.assertEqual(result["voices"], {})
                self.assertNotIn("audio", run.call_args.kwargs["lines"][0])
                result = await server.dialog(lines, voice=True, language="id", voices={"Ana_rig": {"pitch": 1, "rate": 1.1}})
                self.assertEqual(len(result["generated_files"]), 1)
                self.assertTrue(run.call_args.kwargs["lines"][0]["audio"].endswith(".wav"))
                self.assertEqual(result["voices"]["Ana_rig"]["pitch"], 1)

    async def test_parse_only_no_synthesis_or_network_and_text_preparation(self):
        from mcp_server import server
        from providers.tts import TTS
        with tempfile.TemporaryDirectory() as folder:
            service = TTS(folder, folder)
            service.backends["piper"] = FakeBackend()
            async def run(command, **kwargs):
                p = parse_script(kwargs["script"])
                return {"plan": p, "characters": {}, "warnings": [], "timings": {"total": 0}}
            with patch.object(server, "tts", service), patch.object(server, "run", new=run), patch.object(server.speech, "transcribe", side_effect=AssertionError("ASR")):
                text = "ANA (perempuan, suara: edge:id-ID-GadisNeural): Halo!"
                with patch.object(service, "synthesize", side_effect=AssertionError("synthesis")):
                    r = await server.script_to_scene(text, build=False)
                self.assertTrue(r["voices"]["ANA"]["online"])
                self.assertEqual(r["generated_files"], [])
                self.assertEqual(list(Path(folder).iterdir()), [])
                r = await server.script_to_scene("ANA (perempuan): Halo!")
                self.assertEqual(len(r["generated_files"]), 1)
                self.assertTrue(r["plan"]["beats"][0]["audio"].endswith(".wav"))
                self.assertIn("tts", r["timings"])


if __name__ == "__main__":
    result = unittest.main(exit=False)
    if result.result.wasSuccessful():
        print("TTS UNIT OK")
    else:
        sys.exit(1)
