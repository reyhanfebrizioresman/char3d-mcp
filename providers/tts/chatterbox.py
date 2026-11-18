"""Adapter to the existing free HF Space recipe (same limits and language list)."""
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .audio import pitch_shift, read, time_stretch, write


class Backend:
    online = True
    license = "Chatterbox: MIT; public Hugging Face Space quota and availability apply. No Indonesian."
    privacy = "Online: dialog text is sent to the public ResembleAI Chatterbox Hugging Face Space."

    def __init__(self, root):
        pass

    def available(self):
        return importlib.util.find_spec("gradio_client") is not None

    def install_hint(self):
        return ".venv/bin/python -m pip install -r requirements.txt"

    def voices(self, language=None):
        from providers.hf import TTS_LANGS
        return [{"id": "chatterbox:" + lang, "name": lang + " · Space default", "language": lang,
                 "gender": "variant", "installed": self.available()} for lang in TTS_LANGS
                if not language or lang == language.split("-")[0].split("_")[0]]

    def synthesize(self, text, voice, language, rate, pitch, out_path):
        from providers.hf import HFClient, TTS_LANGS
        if voice not in TTS_LANGS:
            raise ValueError("Chatterbox has no voice for this language (no Indonesian); choose ms explicitly.")
        job = SimpleNamespace(handles=[], cancel_requested=False)
        with tempfile.TemporaryDirectory(dir=Path(out_path).parent) as dest:
            try:
                path, _ = HFClient().run(job, "text_to_speech", {"text": text, "language": voice},
                                        dest, "speech", recipe="chatterbox")
            except Exception as exc:
                raise RuntimeError(f"Chatterbox Space failed ({type(exc).__name__}); check quota/network.") from None
            x, sr = read(path)
        x = pitch_shift(x, pitch, sr)
        if rate != 1:
            x = time_stretch(x, round(len(x) / rate), sr)
        return write(out_path, x, sr)
