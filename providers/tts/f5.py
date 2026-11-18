"""Optional local F5 Indonesian. Import lazily; require every model file locally.

    voices/<name>.json: {voice_reference, reference_text, language?, gender?}.
    The reference must be the user's own voice or used with the owner's permission.
"""
import importlib.util
import json
import threading
from pathlib import Path

from .audio import pitch_shift, write


class Backend:
    online = False
    license = "F5 code/Indonesian finetune: Apache-2.0; upstream base weights: CC-BY-NC (non-commercial)."

    def __init__(self, root):
        self.root = Path(root) / "f5"
        self._model = None
        self._lock = threading.Lock()

    def install_hint(self):
        return "scripts/install_tts.sh f5 --yes"

    def available(self):
        return (importlib.util.find_spec("f5_tts") is not None and all(
            (self.root / f).is_file() for f in ("model.safetensors", "vocab.txt", "vocos/config.yaml", "vocos/pytorch_model.bin")))

    def voices(self, language=None):
        result = []
        for file in sorted((self.root / "voices").glob("*.json")):
            try:
                cfg = self.config(file.stem)
            except (ValueError, OSError):
                continue
            lang = cfg.get("language", "id")
            if not language or lang.startswith(language):
                result.append({"id": "f5:" + file.stem, "name": file.stem, "language": lang,
                               "gender": cfg.get("gender", "variant"), "installed": self.available()})
        return result

    def config(self, name):
        if not name or Path(name).name != name:
            raise ValueError("F5 voice must be a registered name")
        path = self.root / "voices" / (name + ".json")
        cfg = json.loads(path.read_text())
        if not isinstance(cfg, dict):
            raise ValueError("F5 voice JSON must be an object")
        ref = Path(cfg.get("voice_reference", "")).expanduser()
        ref = ref if ref.is_absolute() else path.parent / ref
        if not ref.is_file() or not str(cfg.get("reference_text", "")).strip():
            raise ValueError("F5 needs voice_reference and its reference_text transcript; use only your own/permitted voice")
        return dict(cfg, voice_reference=str(ref))

    def fingerprint(self, voice):
        import hashlib
        cfg = self.config(voice)
        ref_hash = hashlib.sha256(Path(cfg["voice_reference"]).read_bytes()).hexdigest()
        model = self.root / "model.safetensors"
        return f"{cfg}:{ref_hash}:{model.stat().st_mtime_ns if model.exists() else 'missing'}"

    def synthesize(self, text, voice, language, rate, pitch, out_path):
        if not self.available():
            raise RuntimeError(f"F5 TTS is not installed locally. Run: {self.install_hint()}")
        cfg = self.config(voice)
        from f5_tts.api import F5TTS
        # Local ckpt/vocab/vocoder prevent F5's implicit HF/Whisper model downloads.
        with self._lock:
            if self._model is None:
                self._model = F5TTS(model="F5TTS_Base", ckpt_file=str(self.root / "model.safetensors"),
                                   vocab_file=str(self.root / "vocab.txt"), device="cpu",
                                   vocoder_local_path=str(self.root / "vocos"))
            x, sr, _ = self._model.infer(ref_file=cfg["voice_reference"], ref_text=cfg["reference_text"],
                                       gen_text=text, speed=rate, seed=0, show_info=lambda *a: None,
                                       progress=None)
        return write(out_path, pitch_shift(x, pitch, sr), sr)
