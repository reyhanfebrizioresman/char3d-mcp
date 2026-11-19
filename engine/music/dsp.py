"""Numpy-only instruments, Schroeder room, K-weighting and PCM mastering, 48 kHz.

Harmonic oscillators are explicitly band limited. Filters/reverb use FFT transfer
functions with zero padding, avoiding Python sample loops and scipy dependencies.
"""
import hashlib
import math
import os
import tempfile
import wave

import numpy as np

RATE = 48000


def filter_fft(x, low=25, high=9000):
    n = len(x)
    f = np.fft.rfftfreq(n, 1/RATE)
    response = (f/np.sqrt(f*f+low*low))**2 / np.sqrt(1+(f/high)**8)
    return np.fft.irfft(np.fft.rfft(x)*response, n)


def _bandlimit(x, rate=RATE):
    """Antialias guard with a FLAT audible passband through 14 kHz.

    This is a reconstruction filter, not the old 4.8/6.5 kHz timbre low-pass.
    Instruments can retain their actual 8–14 kHz harmonics and percussion air.
    """
    freq = np.fft.rfftfreq(len(x), 1/rate)
    gain = .5+.5*np.cos(np.pi*np.clip((freq-14000)/2000, 0, 1))
    return np.fft.irfft(np.fft.rfft(x)*gain, len(x))


def _polyblep_saw(phase, step):
    """Polynomial band-limited step correction at the saw discontinuity."""
    out = 2*phase-1
    at = phase < step
    u = phase[at]/step
    out[at] -= 2*u-u*u-1
    at = phase > 1-step
    u = (phase[at]-1)/step
    out[at] -= u*u+2*u+1
    return out


def saw(hz, seconds, detune=0, oversample=2):
    """PolyBLEP at 2x + reconstruction before decimation, no folded saw teeth."""
    n = max(64, round(seconds*RATE))
    rate = RATE*oversample
    freq = hz*(1+detune)
    phase = (np.arange(n*oversample)*freq/rate) % 1
    return _bandlimit(_polyblep_saw(phase, freq/rate), rate)[::oversample]


def instrument(kind, note, duration, velocity, seed=0):
    """Additive piano/FM keys, detuned harmonic strings, KS resonator and drums."""
    n = max(64, round(duration*RATE))
    t = np.arange(n)/RATE
    hz = 440*2**((note-69)/12)
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    if kind in ("pad", "strings"):
        for detune in (-.0025, 0, .0025):
            if kind == 'strings':
                x += saw(hz, duration, detune)/3
            else:
                for h in range(1, min(18, int(14000/hz))+1):
                    x += np.sin(2*np.pi*hz*h*(1+detune)*t+.08*h)/h**1.7/3
        if kind == 'strings':
            x *= 1.45  # equal fundamental to the additive pad, with live upper partials
            # Broad body resonance, rather than a dull low-pass on a naked saw.
            freq = np.fft.rfftfreq(n, 1/RATE)
            resonance = 1+2.2*np.exp(-.5*(np.log2(np.maximum(freq, 1)/2800)/.8)**2)
            x = np.fft.irfft(np.fft.rfft(x)*resonance, n)
        attack = .17 if kind == "strings" else .30
        env = (1-np.exp(-t/attack))*np.minimum(1, (duration-t)/min(.5, duration*.4))
        x *= np.maximum(0, env)*(.96+.04*np.sin(2*np.pi*2.3*t))
    elif kind == "pluck":
        # Modal solution of the Karplus–Strong delay/loss loop. Sampling a narrow
        # feedback transfer on a short FFT grid missed fundamental poles and made
        # some notes random, hissy and weak. Here each pole's phase and decay are
        # resolved directly, with no grid quantization or aliased high modes.
        harmonic = np.arange(1, int(14000/hz)+1)
        damping = .025
        delay = RATE/hz-damping
        omega = 2*np.pi*harmonic*hz/RATE
        for _ in range(4):
            loss = (1-damping)+damping*np.exp(-1j*omega)
            derivative = np.imag(-1j*damping*np.exp(-1j*omega)/loss)
            omega -= (omega*delay-np.angle(loss)-2*np.pi*harmonic)/(delay-derivative)
        loop_gain = np.exp(-1/(hz*1.3))
        magnitude = abs((1-damping)+damping*np.exp(-1j*omega))
        decay = -1/(hz*np.log(loop_gain*magnitude))
        amplitudes = rng.uniform(.9, 1.1, len(harmonic))/harmonic**.55
        amplitudes[0] = 1
        for w, amplitude, tau in zip(omega, amplitudes, decay):
            x += amplitude*np.sin(w*RATE*t)*np.exp(-t/tau)
        x *= .65/np.sqrt(.5*np.sum(amplitudes**2))
    elif kind in ("piano", "epiano", "bass"):
        if kind == "epiano":
            # FM is generated at 4x; reject out-of-band sidebands BEFORE downsampling.
            fast = np.arange(n*4)/(RATE*4)
            index = (1.3+velocity*1.7)*np.exp(-fast/.35)
            signal = np.sin(2*np.pi*hz*fast+index*np.sin(4*np.pi*hz*fast))
            for harmonic, amount, decay in ((3, .18, 1.3), (5, .30, .85), (7, .24, .6), (9, .16, .4), (11, .10, .25)):
                signal += amount*np.sin(2*np.pi*hz*harmonic*fast)*np.exp(-fast/decay)
            x = _bandlimit(signal, RATE*4)[::4]
        elif kind == 'bass':
            # Round low fundamental, restrained growl; no octave-doubled "bass".
            x = np.sin(2*np.pi*hz*t)+.22*np.sin(4*np.pi*hz*t)+.08*np.sin(6*np.pi*hz*t)
            x *= (1-np.exp(-t/.006))*np.exp(-t/1.35)
        else:
            for h in range(1, min(64, int(14500/hz))+1):
                amp = (.72+.50*velocity)/h**.88 if h > 1 else 1
                x += amp*np.sin(2*np.pi*hz*h*t)*np.exp(-t*(.55+h*.045))
        if kind != 'bass':
            x *= (1-np.exp(-t/.0018))*np.exp(-t/2.1)
    elif kind in ("bell", "metallophone", "gong"):
        ratios = ((1, 2, 3, 4, 5, 6, 8, 10, 12) if kind == 'bell' else
                  (1, 2, 3.99, 5.42, 6.76, 8, 10.3, 12.4) if kind == 'metallophone' else
                  (1, 1.49, 2.08, 2.63, 3.37, 4.18, 6.23, 9.1))
        for i, ratio in enumerate(ratios):
            if hz*ratio < 14500:
                x += np.sin(2*np.pi*hz*ratio*t+.08*np.sin(2*np.pi*.8*t))*np.exp(
                    -t*(1+i*.16)/(3.1 if kind == 'gong' else 1.1))/(1+i)**.85
        x *= 1-np.exp(-t/(.025 if kind == "gong" else .002))
    else:
        noise = filter_fft(rng.standard_normal(n), low=3400 if kind in ("hat", "shaker") else 220,
                           high=14500 if kind in ("hat", "shaker") else 11000)
        if kind == "kick":
            phase = 2*np.pi*(49*t+90*.015*(1-np.exp(-t/.015)))
            x = np.sin(phase)*np.exp(-t/.13)+.045*noise*np.exp(-t/.009)
        elif kind in ("tom", "frame_drum"):
            base = hz*1.25 if kind == "tom" else 82
            x = sum(np.sin(2*np.pi*base*r*t)*np.exp(-t/(.10/(1+i*.3)))/(i+1)
                    for i, r in enumerate((1, 1.59, 2.14))) + .10*noise*np.exp(-t/.04)
        elif kind == "rim":
            x = (np.sin(2*np.pi*820*t)+.5*np.sin(2*np.pi*1730*t))*np.exp(-t/.015)
        elif kind == "snare":
            x = .45*np.sin(2*np.pi*180*t)*np.exp(-t/.06)+.75*noise*np.exp(-t/.07)
        elif kind in ("hat", "shaker"):
            envelope = np.exp(-t/(.038 if kind == "hat" else .052))
            if kind == 'shaker':
                envelope *= (.65+.35*np.sin(2*np.pi*115*t)**2)
            x = noise*envelope*1.0
        else:
            raise ValueError(f"unknown instrument {kind}")
    # Remove rumble from upper voices, but don't discard their harmonics/air.
    low = 24 if kind in ('bass', 'gong', 'kick', 'tom', 'frame_drum') else 95 if kind == 'pad' else 45
    x = filter_fft(x, low, 22000)
    x = _bandlimit(x)
    fade = min(48 if kind not in ('pad', 'strings') else 240, n//4)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-min(n//3, 2400):] *= np.linspace(1, 0, min(n//3, 2400))
    return (x*velocity).astype(np.float32)


def reverb(x, loop=False):
    """Schroeder parallel damped feedback combs → two series allpasses, stereo."""
    n = len(x)
    size = n if loop else 1 << (n+RATE*3-1).bit_length()
    w = 2*np.pi*np.fft.rfftfreq(size)
    wet = np.empty_like(x)
    source = np.fft.rfft(x.mean(axis=1), size)
    for channel in range(2):
        response = np.zeros(len(w), complex)
        damp = .55+.45*np.exp(-1j*w)
        for delay in (1423, 1789, 1999, 2137):
            z = np.exp(-1j*w*(delay+channel*113))
            response += z/(1-.72*damp*z)/4
        for delay in (241, 83):
            z = np.exp(-1j*w*(delay+channel*17))
            response *= (z-.5)/(1-.5*z)
        freq = np.fft.rfftfreq(size, 1/RATE)
        response *= 1/np.sqrt(1+(freq/3800)**6)
        wet[:, channel] = np.fft.irfft(source*response, size)[:n]
    return x*.88+wet*.18


def _k_weight(x):
    # BS.1770 48 kHz shelf and RLB high-pass coefficients; zero state, padded FFT.
    size = 1 << (len(x)+RATE-1).bit_length()
    z = np.exp(-2j*np.pi*np.fft.rfftfreq(size))
    response = np.ones(len(z), complex)
    for b, a in (((1.53512485958697, -2.69169618940638, 1.19839281085285), (1, -1.69065929318241, .73248077421585)),
                 ((1, -2, 1), (1, -1.99004745483398, .99007225036621))):
        response *= (b[0]+b[1]*z+b[2]*z*z)/(a[0]+a[1]*z+a[2]*z*z)
    return np.fft.irfft(np.fft.rfft(x, size, axis=0)*response[:, None], size, axis=0)[:len(x)]


def loudness(x):
    """BS.1770-ish stereo LUFS: K weighting, 400 ms blocks/100 ms hop, -70/-10 gates."""
    y = _k_weight(np.asarray(x, dtype=float))
    win, hop = round(.4*RATE), round(.1*RATE)
    if len(y) < win:
        y = np.pad(y, ((0, win-len(y)), (0, 0)))
    power = (y*y).sum(axis=1)
    sums = np.concatenate(([0], np.cumsum(power)))
    indices = np.arange(0, len(y)-win+1, hop)
    energy = (sums[indices+win]-sums[indices])/win
    absolute = energy[-.691+10*np.log10(energy+1e-20) > -70]
    if not len(absolute):
        return -100.
    relative = absolute[absolute > absolute.mean()*.1]
    return float(-.691+10*np.log10(relative.mean()+1e-20))


def true_peak(x):
    """4x, 48-tap windowed-sinc polyphase intersample peak estimate."""
    peak = float(np.max(np.abs(x)))
    taps = np.arange(-24, 25)
    for fraction in (.25, .5, .75):
        kernel = np.sinc(taps-fraction)*np.kaiser(len(taps), 8.6)
        kernel /= kernel.sum()
        for ch in range(x.shape[1]):
            peak = max(peak, float(np.max(np.abs(np.convolve(x[:, ch], kernel, mode="same")))))
    return peak


def master(x, loop=False, fade_in=.02, fade_out=.04):
    x = x.astype(float)
    for ch in range(2):
        x[:, ch] = filter_fft(x[:, ch], 22, 22000)
    x -= x.mean(axis=0)
    # Slow, linked RMS compressor (120 ms windows, 2:1 above average + 3 dB).
    hop = 2400
    blocks = [np.sqrt(np.mean(x[i:i+hop]**2)+1e-12) for i in range(0, len(x), hop)]
    level = np.asarray(blocks)
    threshold = np.sqrt(np.mean(x*x))*1.4
    gain = np.minimum(1, (threshold/np.maximum(level, 1e-9))**.5)
    x *= np.interp(np.arange(len(x)), np.arange(len(gain))*hop+hop/2, gain)[:, None]
    if not loop:
        for seconds, reverse in ((fade_in, False), (fade_out, True)):
            n = min(len(x)//2, max(2, round(seconds*RATE)))
            ramp = np.sin(np.linspace(0, np.pi/2, n))**2
            if reverse:
                x[-n:] *= ramp[::-1, None]
            else:
                x[:n] *= ramp[:, None]
    else:
        # Reverb/note tails are already periodic. A tiny local endpoint correction
        # removes sub-sample phase mismatch without dipping to silence each loop.
        n = min(480, len(x)//8)
        delta = x[-1]-x[0]
        x[-n:] -= np.linspace(0, 1, n)[:, None]*delta
    for _ in range(4):
        x *= 10**((-16-loudness(x))/20)
        if true_peak(x) <= 10**(-1.05/20):
            break
        # Smooth peak compression, then remeasure the gated integrated level.
        # Nonlinearity at 2x, then reconstruction before decimation. Clipping at
        # 48 kHz would fold bright string/bell harmonics back into the mix.
        size = len(x)
        fast = np.fft.irfft(np.fft.rfft(x, axis=0), size*2, axis=0)*2
        fast = .82*np.tanh(fast/.82)
        for ch in range(2):
            fast[:, ch] = _bandlimit(fast[:, ch], RATE*2)
        x = fast[::2]
    if loop:
        n = min(480, len(x)//8)
        x[-n:] -= np.linspace(0, 1, n)[:, None]*(x[-1]-x[0])
    peak = true_peak(x)
    x *= min(1, 10**(-1.05/20)/max(peak, 1e-12))
    return x.astype(np.float32)


def render(score, fade_in=.02, fade_out=.04):
    x = np.zeros((round(score["duration"]*RATE), 2), np.float32)
    cache = {}
    for event in score["events"]:
        key = event["instrument"], event["note"], event["duration"], max(.25, round(event["velocity"]*4)/4)
        if key not in cache:
            seed = int.from_bytes(hashlib.sha256(repr((score["seed"], key)).encode()).digest()[:4], "little")
            cache[key] = instrument(*key, seed=seed)
        sample = cache[key]
        # Velocity controls both level and piano/FM brightness, without a sample per
        # tiny humanization change. Parallel filtered component darkens softer notes.
        v = event["velocity"]/key[3]
        pan = min(1, max(-1, event["pan"]))
        stereo = np.array([math.cos((pan+1)*np.pi/4), math.sin((pan+1)*np.pi/4)])*v
        start = round(event["time"]*RATE)
        offset = 0
        while offset < len(sample):
            if not score["loop"] and start+offset >= len(x):
                break
            lo = (start+offset) % len(x)
            length = min(len(sample)-offset, len(x)-lo)
            x[lo:lo+length] += sample[offset:offset+length, None]*stereo
            offset += length
    return master(reverb(x, score["loop"]), score["loop"], fade_in, fade_out)


def spectral_metrics(x, seconds=20):
    """First 20 s, mono sum/2, whole-window Hann FFT; ratios are power fractions.

    The same specified window/method is used for before/after, tests and demos.
    Above-16k energy alone is NOT an alias detector: folded aliasing can be lower.
    Oscillator folding is tested separately against forbidden harmonic positions.
    """
    mono = np.asarray(x[:round(seconds*RATE)], dtype=float).mean(axis=1)
    p = np.abs(np.fft.rfft(mono*np.hanning(len(mono))))**2
    freq = np.fft.rfftfreq(len(mono), 1/RATE)
    total = max(float(p.sum()), 1e-20)
    result = {f'above_{name}_ratio': float(p[freq >= hz].sum()/total)
              for name, hz in (('2k', 2000), ('4k', 4000), ('8k', 8000), ('16k', 16000))}
    result.update(below_120_ratio=float(p[freq < 120].sum()/total),
                  below_30_ratio=float(p[freq < 30].sum()/total),
                  air_8_16k_ratio=float(p[(freq >= 8000) & (freq < 16000)].sum()/total),
                  centroid_hz=round(float((p*freq).sum()/total), 2),
                  spectral_seconds=round(len(mono)/RATE, 4),
                  spectral_method='mono (L+R)/2, first min(20,duration) s, Hann FFT')
    return result


def metrics(x, score=None):
    """Full-clip loudness/peak/chroma; explicitly specified 20 s mono spectrum."""
    mono = x.mean(axis=1)
    # Bounded overlapping spectral windows, never one huge FFT in a report.
    n = 8192
    power = np.zeros(n//2+1)
    chroma = np.zeros(12)
    f = np.fft.rfftfreq(n, 1/RATE)
    bins = (f >= 65) & (f < 4200)
    for at in range(0, max(1, len(mono)-n), n):
        part = mono[at:at+n]
        if len(part) != n:
            continue
        p = np.abs(np.fft.rfft(part*np.hanning(n)))**2
        power += p
        # Narrow local spectral peaks reduce leakage bias in pitch-class checks.
        peaks = (p[1:-1] > p[:-2]) & (p[1:-1] > p[2:])
        mask = np.pad(peaks, (1, 1)) & bins
        np.add.at(chroma, np.round(69+12*np.log2(f[mask]/440)).astype(int) % 12, p[mask])
    total = max(power.sum(), 1e-15)
    rms = float(np.sqrt(np.mean(x.astype(float)**2)))
    peak = true_peak(x)
    result = dict(lufs=round(loudness(x), 3), true_peak_dbfs=round(20*np.log10(max(peak, 1e-12)), 3),
                  crest_db=round(20*np.log10(max(peak, 1e-12)/max(rms, 1e-12)), 3),
                  above_16k_ratio=float(power[f >= 16000].sum()/total),
                  centroid_hz=round(float((power*f).sum()/total), 2),
                  bass_ratio=float(power[f < 250].sum()/total),
                  mid_ratio=float(power[(f >= 250) & (f < 4000)].sum()/total),
                  seam_delta=float(np.max(np.abs(x[-1]-x[0]))),
                  max_sample_delta=float(np.max(np.abs(np.diff(x, axis=0)))),
                  chroma=[round(float(c/max(chroma.sum(), 1e-15)), 5) for c in chroma])
    result.update(spectral_metrics(x))
    if score:
        allowed = [(score["tonic"]+v) % 12 for v in score["scale"]]
        result["key_energy_ratio"] = round(float(chroma[allowed].sum()/max(chroma.sum(), 1e-15)), 4)
        # Acoustic pulse estimate from autocorrelation of 5 ms onset energy.
        hop = 240
        count = len(mono)//hop
        energy = np.sqrt(np.mean(mono[:count*hop].reshape(count, hop)**2, axis=1))
        onset = np.maximum(0, np.diff(energy))
        target = 60/score["tempo"]*RATE/hop
        lags = np.arange(max(1, round(target*.94)), round(target*1.06)+1)
        values = [np.dot(onset[:-lag], onset[lag:]) if lag < len(onset) else 0 for lag in lags]
        found = int(lags[np.argmax(values)])
        result["detected_tempo"] = round(60*RATE/(hop*found), 2)
        result["tempo_error_pct"] = round(abs(result["detected_tempo"]/score["tempo"]-1)*100, 3)
    return result


def write_cached(x, directory):
    pcm = np.round(np.clip(x, -1, 1)*32767).astype("<i2").tobytes()
    digest = hashlib.sha256(pcm).hexdigest()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, digest+".wav")
    if not os.path.exists(path):
        fd, temporary = tempfile.mkstemp(dir=directory, suffix=".wav.tmp")
        os.close(fd)
        try:
            with wave.open(temporary, "wb") as wav:
                wav.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
                wav.writeframes(pcm)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    return path, digest
