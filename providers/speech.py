"""Local speech recognition with word timestamps (faster-whisper, MIT, CPU).

The model is downloaded once from Hugging Face on first use (tiny ~75 MB by default;
set CHAR3D_WHISPER_MODEL=base|small for better accuracy at more size/time).
Runs in the MCP server process; nothing leaves the machine after the model download.
"""
import os
import threading

_MODEL = None
_LOCK = threading.Lock()


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def model_name():
    return os.environ.get("CHAR3D_WHISPER_MODEL", "tiny")


def _model():
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            _MODEL = WhisperModel(model_name(), device="cpu", compute_type="int8")
        return _MODEL


def _decode_16k_mono(path):
    """Decode any audio/video file to float32 mono 16 kHz (PyAV API, version-agnostic)."""
    import av
    import numpy as np
    chunks = []
    with av.open(path) as container:
        stream = container.streams.audio[0]
        resampler = av.audio.resampler.AudioResampler(format="flt", layout="mono", rate=16000)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):   # flush
            chunks.append(out.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


def transcribe(path, language=None):
    """Return {"text", "language", "words": [{"word", "start", "end", "probability"}]}."""
    if not available():
        raise RuntimeError("faster-whisper is not installed (pip install -r requirements.txt)")
    # decode ourselves: faster-whisper's own decoder breaks on newer PyAV releases
    audio = _decode_16k_mono(path)
    segments, info = _model().transcribe(audio, language=language, word_timestamps=True,
                                         vad_filter=True, beam_size=1)
    words, texts = [], []
    for seg in segments:
        texts.append(seg.text.strip())
        for w in seg.words or []:
            token = w.word.strip()
            if token:
                words.append({"word": token, "start": round(float(w.start), 3),
                              "end": round(float(w.end), 3),
                              "probability": round(float(w.probability), 3)})
    return {"text": " ".join(texts).strip(), "language": info.language,
            "language_probability": round(float(info.language_probability), 3),
            "duration": round(float(info.duration), 2), "words": words,
            "model": model_name()}
