"""Seeded tonal grammar, motifs, voice leading and duration-aware score form."""
import itertools
import math
import random
import re

from .catalog import PALETTES, mood_name, infer_mood

NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
VERSION = 2


def number(value, label, lo, hi):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label} must be numeric") from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{label} must be in {lo}..{hi}")
    return value


def settings(mood="auto", seed=0, tempo=None, key=None, **context):
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    mood = mood_name(mood)
    if mood is None:
        return None
    mood = infer_mood(**context) if mood == "auto" else mood
    p = PALETTES[mood]
    rng = random.Random(seed*101+p.key_offset)
    bpm = round(rng.uniform(*p.tempo), 2) if tempo is None else number(tempo, "tempo", 40, 180)
    tonic = NOTES[(seed*5+p.key_offset) % 12]
    mode = p.modes[seed % len(p.modes)] if p.modes else p.mode
    if key is not None:
        if not isinstance(key, str):
            raise ValueError("key must be e.g. C, D minor or F# major")
        match = re.fullmatch(r"([A-Ga-g])([#b]?)(?:\s+(major|minor|dorian|lydian|phrygian|mixolydian|pentatonic))?", key.strip(), re.I)
        if not match:
            raise ValueError("key must be e.g. C, D minor or F# major")
        tonic = FLATS.get(match[1].upper()+match[2], match[1].upper()+match[2])
        if tonic not in NOTES:
            raise ValueError("unsupported tonic")
        mode = match[3].lower() if match[3] else mode
    scales = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10),
              "dorian": (0, 2, 3, 5, 7, 9, 10), "lydian": (0, 2, 4, 6, 7, 9, 11),
              "phrygian": (0, 1, 3, 5, 7, 8, 10), "mixolydian": (0, 2, 4, 5, 7, 9, 10),
              "pentatonic": (0, 2, 5, 7, 9)}
    scale = scales[mode]
    if mood == "nusantara" and mode == "pentatonic" and seed % 2:
        scale = (0, 1, 5, 7, 8)  # pelog-inspired equal-tempered subset
    return dict(mood=mood, tempo=bpm, key=f"{tonic} {mode}", tonic=NOTES.index(tonic), scale=list(scale))


def script_settings(value="auto", seed=0, beats=(), look=None, weather=None, environment=None):
    """A plan stores the request AND resolution so re-parsing never loses opt-outs."""
    if isinstance(value, dict):
        value = value.get("requested", value.get("mood", "auto"))
    result = settings(value, seed, beats=beats, look=look, weather=weather, environment=environment)
    return dict(result, requested=mood_name(value)) if result else None


def voice_lead(pitches, previous):
    candidates = [sorted(v) for v in itertools.product(*[[p-12, p, p+12] for p in pitches])
                  if len(set(v)) == len(v) and min(v) >= 45 and max(v) <= 81]
    return min(candidates, key=lambda v: sum(abs(a-b) for a, b in zip(v, previous)) + .15*(max(v)-min(v)))


def compose(duration=30, mood="warm", tempo=None, key=None, intensity=.6, seed=0,
            cuts=(), emotions=(), sections=None, fps=24, first=1, loop=False):
    duration = number(duration, "duration", .25, 600)
    intensity = number(intensity, "intensity", 0, 1)
    fps = number(fps, "fps", 1, 240)
    cfg = settings(mood, seed, tempo, key)
    if cfg is None:
        raise ValueError("compose requires an enabled mood")
    palette = PALETTES[cfg["mood"]]
    rng = random.Random(seed*101+palette.key_offset)
    beat = 60 / cfg["tempo"]
    if loop and tempo is not None and abs(duration/(beat*4)-round(duration/(beat*4))) > 1e-6:
        raise ValueError("an explicit loop tempo needs a duration containing whole 4-beat bars")
    if loop and tempo is None:
        # Exactly N bars per loop, preserving a stable pulse at the seam.
        bars = max(1, round(duration / (beat*4)))
        beat = duration/(bars*4)
        cfg["tempo"] = 60/beat
    bar = 4*beat
    nbar = max(1, math.ceil(duration/bar))
    scale, tonic = cfg["scale"], cfg["tonic"]
    size = len(scale)

    def pitch(degree, octave=4):
        return 12*(octave+1) + tonic + 12*(degree//size) + scale[degree % size]

    def register(note, low, high):
        while note > high:
            note -= 12
        while note < low:
            note += 12
        return note

    # Short cues compress the form; long cues develop a repeated four-bar motif.
    if duration < bar*2:
        form = [("A", 0., duration*.72, .8), ("outro", duration*.72, duration, .6)]
    else:
        form = [("intro", 0., min(bar, duration*.15), .48), ("A", min(bar, duration*.15), duration*.50, .76),
                ("B", duration*.50, duration*.80, 1.), ("outro", duration*.80, duration, .60)]
    cues = []
    for section in sections or []:
        if not isinstance(section, dict) or "frame" not in section:
            raise ValueError("sections need {frame, name?, intensity?}")
        at = (number(section["frame"], "section frame", first, first+duration*fps)-first)/fps
        cues.append(dict(frame=section["frame"], time=at, name=str(section.get("name", "cue")),
                         intensity=number(section.get("intensity", .7), "section intensity", 0, 1)))
    events, chords = [], []

    def add(instrument, at, length, note=60, velocity=.3, pan=0, role="accompaniment", exact=False):
        at = at if exact else at+rng.uniform(-.009, .009)
        if not 0 <= at < duration:
            at = max(0., at)
        if at >= duration:
            return
        dynamic = next((d for _name, a, b, d in form if a <= at < b), .6)
        for cue in cues:
            distance = abs(at-cue["time"])
            dynamic *= 1+(cue["intensity"]-.5)*.6*max(0, 1-distance/2)
        for e in emotions:
            center = (e["frame"]-first)/fps
            distance = abs(at-center)
            direction = -.30 if e.get("emotion") in ("sad", "fear", "angry", "anger") else .28
            dynamic *= 1+direction*float(e.get("strength", .6))*max(0, 1-distance/2)
        events.append(dict(instrument=instrument, time=round(at, 7), duration=round(max(.04, length), 6),
                           note=int(note), velocity=round(velocity*dynamic*palette.dynamics*(.5+.5*intensity)*rng.uniform(.92, 1.08), 6),
                           pan=pan, role=role))

    grammar = rng.choice(palette.grammar)
    motif = [0, rng.choice((1, 2)), rng.choice((2, 4)), 1, 0, 2, 1, 0]
    previous = [pitch(0), pitch(2), pitch(4)]
    ending = max(0, duration-min(bar, duration*.20))
    for b in range(nbar):
        at = b*bar
        if at >= ending and not loop:
            break
        degree = grammar[b % len(grammar)] % size
        if b % 4 == 3 and not loop:
            degree = 4 if size == 7 else 3
        triad_degrees = (degree, degree+2, degree+4) if size == 7 else (degree, degree+2)
        pitches = [pitch(d) for d in triad_degrees]
        voiced = voice_lead(pitches, previous[:len(pitches)])
        previous = voiced
        chords.append(dict(time=round(at, 6), duration=min(bar, duration-at), degree=degree, notes=voiced))
        sustain = "strings" if cfg['mood'] in ('sad', 'romantic', 'tense', 'epic', 'nostalgic') else "pad"
        if intensity < .3:
            sustain = "pad"
        for j, note in enumerate(voiced):
            add(sustain, at, min(bar*1.05, duration-at), note, palette.pad_level, (j-1)*.28)
        # A root/third/fifth line in G1..Bb2. Previously degree offsets let later
        # chord roots/fifths drift above 120 Hz; the pad-heavy mix masked the rest.
        for k, (offset, interval, length) in enumerate(palette.bass_steps):
            bass = register(pitch(degree+interval, 1), 31, 46)
            add('bass', at+offset*beat, beat*length, bass,
                palette.bass_level*(1 if k == 0 else .83), 0, 'bass')
        keys = next(i for i in palette.instruments if i in ("piano", "epiano", "pluck", "bell", "metallophone"))
        for step in palette.arp_steps:
            if intensity < .4 and step % 2:
                continue
            swing = .10*beat if step % 2 and palette.feel in ("swing", "lilt") else 0
            arpat = at+step*.5*beat+swing
            if arpat >= ending and not loop:
                continue
            length = beat*(.38 if cfg['mood'] == 'playful' else .65 if cfg['mood'] == 'tense' else 1.2)
            add(keys, arpat, length, voiced[step % len(voiced)], palette.keys_level,
                -.3 if step % 2 else .25)
        # The second voice is actually arranged, rather than merely named in a
        # palette whose first keyboard then played every part.
        if cfg['mood'] in ('warm', 'nostalgic', 'romantic') and b % 2 == 1:
            secondary = 'piano' if keys == 'pluck' else 'pluck'
            for k in (1, 3):
                add(secondary, at+k*beat, beat*1.3, voiced[k % len(voiced)]+12, .11, -.4)
        if (b or duration < bar*2) and (intensity >= .35 or b % 2 == 0):
            for step, offset in enumerate(palette.melody_beats):
                m = motif[((b % 2)*4+step) % len(motif)]
                # Repeat → diatonic sequence → rhythmic/melodic variation → cadence.
                if b >= 4 and b % 4 in (0, 1):
                    m += 1
                md = degree+(0, 2, 4)[m % 3] if step in (0, 2) else degree+m
                if b % 4 == 3 and step == len(palette.melody_beats)-1:
                    md = degree
                melat = at+offset*beat
                if melat < ending or loop:
                    low, high = ((84, 100) if palette.lead_octave == 6 else (65, 88))
                    note = register(pitch(md, palette.lead_octave), low, high)
                    add(palette.lead, melat, beat*(1.65 if len(palette.melody_beats) <= 2 else .75),
                        note, palette.lead_level, .15, "melody")
        if (b > 0 or duration < bar*2) and intensity >= .25:
            for k in range(4):
                if "kick" in palette.instruments:
                    if k % 2 == 0:
                        add("kick", at+k*beat, .42, velocity=.34*palette.drums, exact=True, role="pulse")
                if intensity > .8 and k % 2 == 0 and cfg['mood'] in ('epic', 'tense', 'happy'):
                    add('tom', at+(k+.5)*beat, .22, note=pitch(0, 2), velocity=.055, pan=.25)
                for inst in ("rim", "snare", "frame_drum", "tom"):
                    if inst in palette.instruments and (k % 2 or inst == "frame_drum"):
                        add(inst, at+k*beat, .42, note=register(pitch(degree, 1), 31, 46),
                            velocity=(.12 if inst != "tom" else .20)*palette.drums,
                            pan=-.15, role="pulse", exact=True)
            for inst in ("hat", "shaker"):
                if inst in palette.instruments:
                    for k in range(8):
                        swing = .10*beat if k % 2 and palette.feel == 'swing' else 0
                        add(inst, at+k*beat*.5+swing, .19 if inst == 'shaker' else .12,
                            velocity=(.16 if k % 2 else .12)*palette.drums, pan=.35,
                            role="pulse", exact=True)
        if "gong" in palette.instruments and b % 4 == 0:
            add("gong", at, min(5, duration-at), register(pitch(0, 1), 27, 38), .55, 0)
    if not loop:
        # End tonic is independent of the rounded bar grid and lands before the tail.
        voiced = voice_lead([pitch(d) for d in ((0, 2, 4) if size == 7 else (0, 2))], previous)
        chords.append(dict(time=ending, duration=duration-ending, degree=0, notes=voiced, cadence=True))
        for note in voiced:
            add(keys, ending, duration-ending, note, palette.keys_level*.9, -.1, "cadence", exact=True)
            add(sustain, ending, duration-ending, note, palette.pad_level, .1, "cadence", exact=True)
        add("bass", ending, duration-ending, register(pitch(0, 1), 31, 46),
            palette.bass_level*.8, 0, "cadence", exact=True)
    accents = []
    for frame in sorted(set(cuts) | {c["frame"] for c in cues}):
        at = (number(frame, "cut frame", first, first+duration*fps)-first)/fps
        if at >= duration:
            continue
        chord = next((c for c in reversed(chords) if c["time"] <= at), chords[0])
        add("bell", at, min(1.3, duration-at), chord["notes"][-1]+12, .095, .15, "cut", exact=True)
        accents.append(dict(frame=frame, time=at, kind="cut"))
    return dict(version=VERSION, duration=duration, intensity=intensity, seed=seed, loop=bool(loop),
                fps=fps, first=first, **cfg, instruments=sorted({e['instrument'] for e in events}), feel=palette.feel,
                sections=[dict(name=n, frames=[first+round(a*fps), first+round(b*fps)-1], intensity=d)
                          for n, a, b, d in form]+cues, chords=chords, accents=accents,
                emotion_cues=list(emotions), events=sorted(events, key=lambda e: e["time"]))
