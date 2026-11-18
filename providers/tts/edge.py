"""Explicit opt-in Microsoft Edge service. No implicit online fallback."""
import asyncio
import importlib.util

from .audio import read, write

FALLBACK = [
    ("id-ID-ArdiNeural", "id-ID", "Male"), ("id-ID-GadisNeural", "id-ID", "Female"),
    ("ms-MY-OsmanNeural", "ms-MY", "Male"), ("ms-MY-YasminNeural", "ms-MY", "Female"),
    ("en-US-GuyNeural", "en-US", "Male"), ("en-US-JennyNeural", "en-US", "Female"),
    ("en-GB-RyanNeural", "en-GB", "Male"), ("en-GB-SoniaNeural", "en-GB", "Female"),
]


class Backend:
    online = True
    license = "edge-tts: LGPL-3.0; unofficial Microsoft online API, subject to service terms and changes."
    privacy = "Online: dialog text is sent to Microsoft through the unofficial Edge TTS API."

    def __init__(self, root):
        self._catalog = None

    def available(self):
        return importlib.util.find_spec("edge_tts") is not None

    def install_hint(self):
        return "scripts/install_tts.sh edge"

    def voices(self, language=None, refresh=False):
        if refresh and self.available():
            import edge_tts
            try:
                self._catalog = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), 12))
            except Exception:
                pass  # catalog remains usable offline; synthesis surfaces network errors
        catalog = self._catalog or [dict(ShortName=n, Locale=l, Gender=g) for n, l, g in FALLBACK]
        return [{"id": "edge:" + v["ShortName"], "name": v["ShortName"],
                 "language": v["Locale"], "gender": v["Gender"].lower(), "installed": self.available()}
                for v in catalog if not language or v["Locale"].lower().startswith(language.lower().replace("_", "-"))]

    def synthesize(self, text, voice, language, rate, pitch, out_path):
        if not self.available():
            raise RuntimeError(f"Edge TTS is not installed. Run: {self.install_hint()}")
        import edge_tts

        async def generate():
            # Edge's pitch is in Hz; a perceptual semitone offset about a typical f0.
            hz = round(180 * (2 ** (pitch / 12) - 1))
            client = edge_tts.Communicate(text, voice, rate=f"{round((rate - 1) * 100):+d}%",
                                          pitch=f"{hz:+d}Hz", connect_timeout=15, receive_timeout=45)
            await asyncio.wait_for(client.save(str(out_path)), 90)
        try:
            asyncio.run(generate())
            samples, sr = read(out_path)  # Edge returns MP3, normalize to WAV for all consumers
            return write(out_path, samples, sr)
        except Exception as exc:
            raise RuntimeError(f"Edge TTS request failed ({type(exc).__name__}). "
                               "Check your network/service availability; no engine fallback was used.") from None
