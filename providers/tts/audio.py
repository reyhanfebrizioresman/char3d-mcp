"""Small numpy speech DSP; no torch, scipy or model/network access."""
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48000
DSP_VERSION = "wsola-normalize-1"


def read(path):
    import av
    chunks = []
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            chunks.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
        chunks.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(None))
    if not chunks:
        raise ValueError("TTS returned empty audio")
    return np.concatenate(chunks).astype(np.float32), SAMPLE_RATE


def write(path, samples, sample_rate):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pcm = np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())
    return {"path": str(path), "duration_s": len(pcm) / sample_rate, "sample_rate": sample_rate}


def resample(samples, length):
    """Band-limited Fourier resampling, with even-length Nyquist handling."""
    x = np.asarray(samples, dtype=np.float64)
    length = max(1, int(length))
    if len(x) == length:
        return x.copy()
    spectrum = np.fft.rfft(x)
    out = np.zeros(length // 2 + 1, dtype=complex)
    n = min(len(x), length)
    out[:n // 2 + 1] = spectrum[:n // 2 + 1]
    if n % 2 == 0:
        if length < len(x):
            out[n // 2] *= 2
        elif len(x) < length:
            out[n // 2] *= .5
    return np.fft.irfft(out, n=length) * length / len(x)


def time_stretch(samples, length, sample_rate=22050):
    """WSOLA: align overlapping speech waveforms, preserving local pitch/transients.

    Only modest character variations are intended. Analysis positions follow a fixed
    clock (no accumulated drift); normalized correlation aligns the next overlap.
    """
    x = np.asarray(samples, dtype=np.float64)
    length = max(1, int(length))
    if len(x) == length:
        return x.copy()
    window = max(128, round(sample_rate * .04))
    hop = window // 2
    search = round(sample_rate * .012)
    if min(len(x), length) < window * 2:
        return resample(x, length)
    padded = np.pad(x, (window, window * 2))
    out = np.zeros(length + window * 2)
    weights = np.zeros_like(out)
    win = np.hanning(window)
    previous = None
    ratio = len(x) / length
    for dest in range(0, length, hop):
        expected = window + round(dest * ratio)
        source = expected
        if previous is not None:
            reference = padded[previous + hop:previous + window]
            lo = max(window, expected - search)
            hi = min(len(padded) - window, expected + search)
            candidates = np.lib.stride_tricks.sliding_window_view(
                padded[lo:hi + hop], hop)
            # Strided einsum avoids allocating a large window matrix or spinning BLAS threads.
            correlation = np.einsum("ij,j->i", candidates, reference)
            energy = np.sqrt(np.einsum("ij,ij->i", candidates, candidates) + 1e-12)
            source = lo + int(np.argmax(correlation / energy))
        out[dest:dest + window] += padded[source:source + window] * win
        weights[dest:dest + window] += win
        previous = source
    return (out / np.maximum(weights, 1e-8))[:length]


def pitch_shift(samples, semitones, sample_rate=22050):
    """Change pitch by resampling, then WSOLA back to the exact input duration.

    Local waveform/formant relationships survive the time stretch; this is a timbre
    variation, not a new speaker or a full formant/voice conversion model.
    """
    x = np.asarray(samples, dtype=np.float64)
    if abs(semitones) < 1e-6:
        return x.copy()
    pitched = resample(x, round(len(x) / (2 ** (semitones / 12))))
    return time_stretch(pitched, len(x), sample_rate)


def normalize(samples, sample_rate=SAMPLE_RATE):
    x = np.nan_to_num(np.asarray(samples, dtype=np.float64), nan=0, posinf=0, neginf=0)
    if not len(x):
        raise ValueError("TTS returned empty audio")
    x -= np.mean(x)
    # Use window RMS so quiet fricatives survive trimming, then retain a 40 ms pad.
    block = max(1, round(sample_rate * .01))
    envelope = np.sqrt(np.mean(np.pad(x, (0, (-len(x)) % block)).reshape(-1, block) ** 2, axis=1))
    active = np.flatnonzero(envelope > max(.0003, float(envelope.max()) * .012))
    if not len(active):
        raise ValueError("TTS returned silent audio")
    x = x[max(0, int(active[0]) * block):min(len(x), (int(active[-1]) + 1) * block)]
    voiced = envelope[active]
    rms = float(np.sqrt(np.mean(voiced ** 2)))
    x *= min(.12 / max(rms, 1e-9), .89 / max(float(np.max(np.abs(x))), 1e-9))
    fade = min(round(sample_rate * .008), len(x) // 2)
    if fade:
        ramp = np.sin(np.linspace(0, np.pi / 2, fade)) ** 2
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    return np.pad(x, (round(sample_rate * .04),) * 2).astype(np.float32)
