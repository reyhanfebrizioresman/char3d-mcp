"""Small numpy speech DSP; no torch, scipy or model/network access."""
import wave
from pathlib import Path

import numpy as np

from engine.music.dsp import true_peak

SAMPLE_RATE = 48000
DSP_VERSION = "psola-formant-normalize-3"


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


def f0_track(samples, sample_rate, hop_s=.005, fmin=60., fmax=500., threshold=.2):
    """YIN-style F0 per hop (Hz; 0 = unvoiced), median-smoothed, short runs removed."""
    x = np.asarray(samples, dtype=np.float64)
    hop = max(1, round(sample_rate * hop_s))
    width = round(sample_rate * .025)
    tmin, tmax = max(2, int(sample_rate / fmax)), int(sample_rate / fmin) + 1
    span = width + tmax
    if len(x) < span + 1:
        return np.zeros(max(1, len(x) // hop)), hop
    frames = len(x) // hop
    padded = np.pad(x, (0, span))
    starts = np.arange(frames) * hop
    rms = np.array([np.sqrt(np.mean(padded[s:s + width] ** 2)) for s in starts])
    gate = max(1e-4, float(rms.max()) * .04)
    size = 1 << int(np.ceil(np.log2(2 * span)))
    f0 = np.zeros(frames)
    taus = np.arange(tmax + 1)
    for i, s in enumerate(starts):
        if rms[i] < gate:
            continue
        frame = padded[s:s + span]
        head = frame[:width]
        corr = np.fft.irfft(np.fft.rfft(frame, size) * np.conj(np.fft.rfft(head, size)), size)[:tmax + 1]
        energy = np.cumsum(np.concatenate(([0.], frame ** 2)))
        e_tau = energy[taus + width] - energy[taus]
        diff = e_tau[0] + e_tau - 2 * corr
        diff[0] = 0
        cmnd = np.ones_like(diff)
        cumulative = np.cumsum(diff[1:])
        cmnd[1:] = diff[1:] * taus[1:] / np.maximum(cumulative, 1e-12)
        below = np.flatnonzero(cmnd[tmin:tmax] < threshold)
        if not len(below):
            continue
        tau = tmin + int(below[0])
        while tau + 1 < tmax and cmnd[tau + 1] < cmnd[tau]:
            tau += 1
        a, b = cmnd[tau - 1], cmnd[tau]
        c = cmnd[tau + 1] if tau + 1 <= tmax else b
        curve = a - 2 * b + c
        shift = .5 * (a - c) / curve if abs(curve) > 1e-12 else 0.
        f0[i] = sample_rate / (tau + float(np.clip(shift, -1, 1)))
    voiced = f0 > 0
    smooth = f0.copy()
    for i in np.flatnonzero(voiced):
        window = f0[max(0, i - 2):i + 3]
        smooth[i] = np.median(window[window > 0])
    # Drop voiced runs shorter than 15 ms (isolated octave errors / noise bursts).
    edges = np.flatnonzero(np.diff(np.concatenate(([0], voiced.astype(int), [0]))))
    for start, end in zip(edges[::2], edges[1::2]):
        if end - start < 3:
            smooth[start:end] = 0
    return smooth, hop


def median_f0(samples, sample_rate):
    f0, _ = f0_track(samples, sample_rate)
    voiced = f0[f0 > 0]
    return float(np.median(voiced)) if len(voiced) else 0.


def _psola(x, sample_rate, factor, length):
    """TD-PSOLA: pitch-synchronous grains keep the spectral envelope (formants)."""
    f0, hop = f0_track(x, sample_rate)
    smooth = np.convolve(x, np.ones(max(1, round(sample_rate * .0008))), "same")
    polarity = 1. if smooth.max() >= -smooth.min() else -1.
    unvoiced = sample_rate * .005
    marks, periods, voiced = [], [], []
    t = 0.
    while t < len(x):
        fi = min(int(t / hop), len(f0) - 1)
        if f0[fi] > 0:
            period = sample_rate / f0[fi]
            if voiced and voiced[-1]:
                lo, hi = int(t - period * .3), int(t + period * .3) + 1
            else:
                lo, hi = int(t), int(t + period) + 1
            lo, hi = max(0, lo), min(len(x), hi)
            mark = lo + int(np.argmax(polarity * smooth[lo:hi])) if hi > lo else int(t)
            if marks and mark <= marks[-1] + period * .5:
                mark = int(marks[-1] + period)
            marks.append(mark)
            periods.append(period)
            voiced.append(True)
            t = mark + period
        else:
            marks.append(int(t))
            periods.append(unvoiced)
            voiced.append(False)
            t += unvoiced
    marks = np.asarray(marks, dtype=np.float64)
    pad = int(max(periods) * 2) + 2
    src = np.pad(x, (pad, pad))
    out = np.zeros(length + 2 * pad)
    ratio = len(x) / max(1, length)
    gain = 1 / np.sqrt(factor)
    ts = 0.
    while ts < length:
        target = ts * ratio
        i = int(np.clip(np.searchsorted(marks, target), 0, len(marks) - 1))
        if i and abs(marks[i - 1] - target) < abs(marks[i] - target):
            i -= 1
        half = max(2, int(round(periods[i])))
        center = int(marks[i]) + pad
        grain = src[center - half:center + half] * np.hanning(2 * half)
        pos = int(round(ts)) + pad - half
        out[pos:pos + 2 * half] += grain * (gain if voiced[i] else 1.)
        ts += periods[i] / factor if voiced[i] else periods[i]
    return out[pad:pad + length]


def pitch_shift(samples, semitones, sample_rate=22050, formant=None):
    """Shift pitch by `semitones`, keeping duration, with an optional formant shift.

    TD-PSOLA moves the fundamental while keeping the vocal-tract envelope; a separate
    resampling step then moves formants by `formant` semitones (default ~28% of the
    pitch shift, the typical female/male ratio, capped at ±3.5). Large shifts turn the
    single Indonesian Piper speaker into clearly lower/higher voices, but this is a
    signal transform, not a newly trained speaker.
    """
    x = np.asarray(samples, dtype=np.float64)
    if formant is None:
        formant = float(np.clip(semitones * .28, -3.5, 3.5))
    if abs(semitones) < 1e-6 and abs(formant) < 1e-6:
        return x.copy()
    k = 2 ** (formant / 12)
    shaped = resample(x, round(len(x) / k)) if abs(formant) > 1e-6 else x
    return _psola(shaped, sample_rate, 2 ** (semitones / 12) / k, len(x))


def normalize(samples, sample_rate=SAMPLE_RATE, *, with_offset=False):
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
    trim_start = int(active[0]) * block
    x = x[trim_start:min(len(x), (int(active[-1]) + 1) * block)]
    voiced_rms = float(np.sqrt(np.mean(envelope[active] ** 2)))
    # Ease loud syllables toward the rest of the line before applying makeup gain.
    # Interpolated gain preserves the shape and duration of internal pauses.
    first, last = int(active[0]), int(active[-1]) + 1
    levels = envelope[first:last]
    gain = np.sqrt(np.minimum(1., (1.5 * voiced_rms) / np.maximum(levels, 1e-9)))
    x *= np.interp(np.arange(len(x)), (np.arange(len(gain)) + .5) * block, gain)
    active_gain = gain[active - first]
    rms = float(np.sqrt(np.mean((envelope[active] * active_gain) ** 2)))
    fade = min(round(sample_rate * .008), len(x) // 2)
    if fade:
        ramp = np.sin(np.linspace(0, np.pi / 2, fade)) ** 2
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    padding = round(sample_rate * .04)
    x = np.pad(x, (padding,) * 2)
    # Leave headroom for other stems and for peaks between PCM samples.
    peak = true_peak(x[:, None])
    x *= min(.12 / max(rms, 1e-9), 10 ** (-2 / 20) / max(peak, 1e-9))
    result = x.astype(np.float32)
    return (result, (padding-trim_start)/sample_rate) if with_offset else result
