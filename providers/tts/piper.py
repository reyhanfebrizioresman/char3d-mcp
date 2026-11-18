"""Offline Piper. Models must be installed explicitly; never downloads on use."""
import importlib.util
import json
import threading
import wave
from pathlib import Path

import numpy as np

from .audio import pitch_shift, write

DEFAULT_VOICE = "id_ID-news_tts-medium"


class Backend:
    online = False
    license = ("piper-tts runtime: GPL-3.0. Voices have separate licenses. Indonesian repo is "
               "MIT-labelled but its dataset link is unclear: treat news_tts as personal use.")

    def __init__(self, root):
        self.root = Path(root) / "piper"
        self._models = {}
        self._lock = threading.Lock()

    def install_hint(self):
        return "scripts/install_tts.sh piper"

    def available(self):
        return importlib.util.find_spec("piper") is not None and any(
            p.with_suffix(p.suffix + ".json").is_file() for p in self.root.rglob("*.onnx"))

    def voices(self, language=None):
        result = []
        for model in sorted(self.root.rglob("*.onnx")):
            try:
                cfg = json.loads(Path(str(model) + ".json").read_text())
            except (OSError, ValueError):
                continue
            locale = cfg.get("language", {}).get("code", model.stem.split("-")[0])
            speakers = cfg.get("speaker_id_map") or {"": 0}
            for speaker in speakers:
                name = model.stem + ("#" + speaker if speaker else "")
                result.append({"id": "piper:" + name, "name": name, "language": locale,
                               "gender": "variant", "installed": True})
        if not any(v["name"].split("#")[0] == DEFAULT_VOICE for v in result):
            result.insert(0, {"id": "piper:" + DEFAULT_VOICE, "name": DEFAULT_VOICE,
                              "language": "id_ID", "gender": "variant", "installed": False})
        return [v for v in result if not language or v["language"].lower().replace("_", "-").startswith(language.lower().replace("_", "-"))]

    def model_path(self, voice):
        model = voice.split("#", 1)[0]
        return next((p for p in self.root.rglob("*.onnx") if p.stem == model), None)

    def fingerprint(self, voice):
        model = self.model_path(voice)
        if not model:
            return "missing"
        # Model replacements invalidate audio without rehashing 63 MB on every line.
        cfg = Path(str(model) + ".json")
        if not cfg.is_file():
            return "missing-config"
        return f"{model.stat().st_size}:{model.stat().st_mtime_ns}:{cfg.read_text()}"

    def synthesize(self, text, voice, language, rate, pitch, out_path):
        model = self.model_path(voice)
        if not self.available() or not model or not Path(str(model) + ".json").is_file():
            raise RuntimeError(f"Piper voice {voice!r} is not installed. Run: {self.install_hint()}. "
                               f"Other voices: place .onnx + .onnx.json in {self.root}")
        from piper import PiperVoice, SynthesisConfig
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        with self._lock:
            key = (str(model), self.fingerprint(voice))
            if key not in self._models:
                self._models.clear()  # one resident ONNX model on small CPU machines
                self._models[key] = PiperVoice.load(str(model))
            speaker = self._models[key]
            speaker_id = None
            if "#" in voice:
                name = voice.split("#", 1)[1]
                mapping = json.loads(Path(str(model) + ".json").read_text()).get("speaker_id_map", {})
                if name not in mapping:
                    raise ValueError(f"Unknown Piper speaker {name!r}; choose from list_voices")
                speaker_id = mapping[name]
            config = SynthesisConfig(length_scale=speaker.config.length_scale / rate, speaker_id=speaker_id)
            with wave.open(str(out_path), "wb") as wav:
                speaker.synthesize_wav(text, wav, syn_config=config)
        if pitch:
            with wave.open(str(out_path), "rb") as wav:
                sr = wav.getframerate()
                samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2") / 32768.
            return write(out_path, pitch_shift(samples, pitch, sr), sr)
        with wave.open(str(out_path), "rb") as wav:
            return {"path": str(out_path), "duration_s": wav.getnframes() / wav.getframerate(),
                    "sample_rate": wav.getframerate()}
