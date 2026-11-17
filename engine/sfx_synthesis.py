"""Original, seeded Foley synthesis. Pure numpy; no Blender, samples or downloads."""
import hashlib
import os
import wave

import numpy as np

RATE = 48000
# cutoff Hz, noise decay seconds, body Hz, body decay, scuff gain
SURFACES = {
    "wood": (2200, .075, 145, .12, .20),
    "concrete": (5500, .045, 230, .055, .24),
    "carpet": (650, .055, 85, .065, .10),
    "grass": (3100, .13, 100, .045, .55),
    "gravel": (8500, .17, 190, .065, .75),
    "sand": (1500, .20, 95, .045, .65),
}


def rng_for(seed, *identity):
    key = repr((int(seed), identity)).encode()
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key).digest()[:8], "little"))


def _noise(rng, n, cutoff, low=35):
    f = np.fft.rfftfreq(n, 1 / RATE)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    spectrum *= 1 / np.sqrt(1 + (f / cutoff) ** 6)
    spectrum *= f / np.sqrt(f * f + low * low)
    out = np.fft.irfft(spectrum, n)
    return out / max(np.sqrt(np.mean(out * out)), 1e-9)


def _finish(x, peak=.65):
    x = x - x.mean()
    fade = min(240, len(x) // 8)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x * (peak / max(np.max(np.abs(x)), 1e-9))


def footstep(surface, rng):
    """Heel attack, damped sole/body resonance, delayed toe and granular scuff."""
    cutoff, decay, body, ring, scuff = SURFACES[surface]
    pitch = rng.uniform(.89, 1.12)
    t = np.arange(int(RATE * .62)) / RATE
    heel = _noise(rng, len(t), cutoff * pitch) * np.exp(-t / decay)
    resonance = np.sin(2 * np.pi * body * pitch * t) * np.exp(-t / ring)
    toe_t = np.maximum(0, t - rng.uniform(.045, .075))
    toe = _noise(rng, len(t), cutoff * .72) * np.exp(-toe_t / (decay * .85))
    toe *= (t > .075) * scuff
    if surface in ("grass", "gravel", "sand"):
        # Many small moving grains/blades instead of a single broadband impact.
        grains = np.zeros(len(t))
        for _ in range(28 if surface == "gravel" else 15):
            at = rng.uniform(.012, .24)
            dt = np.maximum(0, t - at)
            grains += (t >= at) * np.exp(-dt / rng.uniform(.002, .012)) * rng.uniform(.2, .6)
        toe += _noise(rng, len(t), cutoff) * grains * scuff * .5
    x = .32 * heel + .40 * resonance + .18 * toe
    # Sub-frame microtiming is in the sample, never shifts the touchdown strip.
    jitter = int(rng.uniform(0, .010) * RATE)
    return np.pad(_finish(x, rng.uniform(.52, .69)), (jitter, 0))


def movement(kind, soft, rng):
    t = np.arange(int(RATE * .85)) / RATE
    rustle = _noise(rng, len(t), 3700, 450)
    env = (1 - np.exp(-t / .012)) * np.exp(-t / .15)
    rustle *= env * (.65 + .35 * np.sin(2 * np.pi * 31 * t) ** 2)
    if kind == "cloth":
        return _finish(rustle, .18)
    creak = sum(np.sin(2 * np.pi * (f * t + 13 * t * t)) / (i + 1)
                for i, f in enumerate((165, 329, 493)))
    creak *= np.exp(-t / (.14 if soft else .25)) * (1 - np.exp(-t / .009))
    thump = np.sin(2 * np.pi * 78 * t) * np.exp(-t / .06)
    x = .22 * rustle + (.035 if soft else .09) * creak
    x += (.10 if soft else .22) * thump * (1 if kind == "sit" else .35)
    return _finish(x, .30 if soft else .43)


def ambience(preset, rng, seconds=8):
    """Periodic noise/oscillators: a seamless bed at -30 dBFS RMS before strip fades."""
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    # FFT noise is periodic; every modulator makes an integer number of cycles.
    x = _noise(rng, n, 1250, 55) * .24
    if preset in ("office", "living_room", "cafe_terrace"):
        x += .16 * np.sin(2 * np.pi * 100 * t) + .07 * np.sin(2 * np.pi * 200 * t)
    if preset in ("classroom", "cafe_terrace"):
        for i in range(12):
            freq = rng.integers(140 * seconds, 650 * seconds) / seconds
            env = (.5 + .5 * np.sin(2 * np.pi * (i + 2) * t / seconds + rng.uniform(0, 6.28))) ** 3
            x += .06 * env * (np.sin(2 * np.pi * freq * t) + .3 * np.sin(4 * np.pi * freq * t))
    if preset in ("city_street", "cafe_terrace"):
        rumble = _noise(rng, n, 240, 25)
        x += rumble * (.35 + .25 * np.sin(2 * np.pi * t / seconds))
    if preset == "park":
        for _ in range(9):
            at, length = rng.uniform(0, seconds), rng.uniform(.15, .45)
            dt = (t - at) % seconds
            envelope = np.sin(np.pi * np.clip(dt / length, 0, 1)) ** 2
            x += .35 * envelope * np.sin(2 * np.pi * (rng.uniform(1800, 3200) * dt + 900 * dt ** 2))
    if preset == "beach":
        x = _noise(rng, n, 4800, 90) * (.25 + .75 * (.5 + .5 * np.sin(2 * np.pi * t / seconds)) ** 2)
    # Match the two endpoint values without introducing a fade at each repeat.
    x -= np.linspace(0, x[-1] - x[0], n)
    x -= x.mean()
    return x * (10 ** (-30 / 20) / max(np.sqrt(np.mean(x * x)), 1e-9))


def write_cached(samples, directory):
    """Hash PCM content, so even equivalent recipes share one 48 kHz 16-bit WAV."""
    pcm = np.round(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    digest = hashlib.sha256(pcm).hexdigest()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, digest + ".wav")
    if not os.path.isfile(path):
        temporary = path + ".tmp"
        with wave.open(temporary, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(RATE)
            stream.writeframes(pcm)
        os.replace(temporary, path)
    return path, digest
