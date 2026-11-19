"""Offline GM rendering through TinySoundFont (never opens an audio device).

Programs are zero based. Nusantara is an original equal-tempered, GM approximation,
not a reconstruction of any regional tuning, repertoire or gamelan ensemble.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

DEFAULT_FONT = "~/.local/share/char3d/soundfonts/GeneralUser-GS.sf2"
# keys, sustained harmony, lead, counterline, bass. General MIDI, bank zero.
PROGRAMS = {
    "happy": (25, 89, 73, 0, 33),       # steel guitar, warm pad, flute, piano
    "warm": (4, 89, 24, 71, 32),        # electric piano, nylon, clarinet, upright
    "sad": (0, 48, 42, 68, 32),         # piano, strings, cello, oboe
    "romantic": (24, 48, 0, 46, 32),    # nylon guitar, piano, harp
    "tense": (45, 48, 68, 60, 33),      # pizzicato, oboe, French horn
    "mysterious": (8, 91, 71, 10, 32),  # celesta, bowed pad, clarinet, music box
    "epic": (0, 48, 60, 61, 33),        # strings, French horn, brass section
    "calm": (4, 89, 73, 46, 32),        # e-piano, warm pad, flute, harp
    "playful": (12, 45, 72, 9, 32),     # marimba, pizzicato, piccolo, glock
    "nostalgic": (4, 48, 24, 71, 32),
    "dreamy": (8, 52, 11, 46, 32),      # celesta, choir, vibraphone, harp
    "nusantara": (11, 14, 12, 108, 43), # vibes, tubular bells, marimba, kalimba
}
DRUMS = dict(kick=36, snare=38, rim=37, hat=42, shaker=82, tom=45, frame_drum=41)


def font_path():
    return Path(os.environ.get("CHAR3D_SOUNDFONT", DEFAULT_FONT)).expanduser()


def available():
    if not font_path().is_file():
        return False
    if importlib.util.find_spec("tinysoundfont") is not None:
        return True
    python = helper_python()
    return python.is_file() and any(python.parent.parent.glob('lib/python*/site-packages/tinysoundfont/__init__.py'))


def helper_python():
    # Blender's bundled Python cannot load the MCP virtualenv's native extension.
    # Use its existing interpreter, never add a foreign ABI to Blender's sys.path.
    return Path(os.environ.get('CHAR3D_MUSIC_PYTHON', str(Path(__file__).resolve().parents[2]/'.venv/bin/python'))).expanduser()


def resolve_backend(backend="auto"):
    if backend not in ("auto", "soundfont", "synth"):
        raise ValueError("music backend must be auto, soundfont or synth")
    if backend == "auto":
        return "soundfont" if available() else "synth"
    if backend == "soundfont" and not available():
        raise RuntimeError(f"SoundFont unavailable: {font_path()}. Run scripts/install_soundfont.sh; "
                           "set CHAR3D_SOUNDFONT or choose backend='synth'.")
    return backend


def track(event):
    if event.get('gm_track'):
        return event['gm_track']
    inst, role = event["instrument"], event["role"]
    if inst in DRUMS:
        return "drums"
    if inst == "gong":
        return "gong"
    if role in ("melody", "counter", "bass", "cut"):
        return role
    return "harmony" if inst in ("strings", "pad") else "keys"


def arrangement(mood):
    keys, harmony, lead, counter, bass = PROGRAMS[mood]
    result = dict(keys=keys, harmony=harmony, melody=lead, counter=counter, bass=bass,
                  cut=9, gong=55, drums=0)
    if mood == "nusantara":
        result.update(cut=9, gong=55, bass=116, koto=107, steel=114, celesta=8, low_hits=47)
    return result


def render_raw(score, rate):
    if importlib.util.find_spec('tinysoundfont') is None:
        with tempfile.TemporaryDirectory(prefix='char3d-sf-') as folder:
            output = Path(folder)/'audio.npy'
            completed = subprocess.run([str(helper_python()), '-m', 'engine.music.soundfont', str(output)],
                input=json.dumps(score), text=True, capture_output=True, timeout=max(60, score['duration']*3),
                cwd=str(Path(__file__).resolve().parents[2]))
            if completed.returncode:
                raise RuntimeError('SoundFont renderer failed: '+completed.stderr[-3000:])
            score['renderer'] = json.loads(completed.stdout)
            return np.load(output, allow_pickle=False)
    from tinysoundfont import Synth
    synth = Synth(gain=-12, samplerate=rate)
    sfid = synth.sfload(str(font_path()), max_voices=256)
    programs = arrangement(score["mood"])
    names = sorted({track(e) for e in score["events"]} - {"drums"})
    channels = dict(zip(names, [c for c in range(16) if c != 9]))
    if any(track(e) == "drums" for e in score["events"]):
        channels["drums"] = 9  # MIDI channel 10, zero-based API
    levels = dict(harmony=50, keys=91, melody=95, counter=65, bass=78, cut=52, gong=48, drums=82,
                  koto=70, steel=60, celesta=64, low_hits=70)
    for name, chan in channels.items():
        synth.program_select(chan, sfid, 0, programs[name], is_drums=name == "drums")
        synth.control_change(chan, 7, levels[name])
        synth.control_change(chan, 10, dict(keys=48, counter=82, harmony=68).get(name, 64))
    n = round(score["duration"]*rate)
    # Warm up periodic note/release state before capturing a loop. Reverb is periodic
    # in the shared mixer; there is no fade or silence dip at the join.
    repeats = 3 if score["loop"] else 1
    schedule = []
    notes = {}
    for repeat in range(repeats):
        for e in score["events"]:
            name = track(e)
            chan = channels[name]
            note = DRUMS[e["instrument"]] if name == "drums" else e["note"]
            reference = dict(harmony=.055, keys=.25, melody=.22, counter=.12,
                             bass=.45, cut=.095, gong=.55, drums=.24,
                             koto=.16, steel=.16, celesta=.16, low_hits=.24)[name]
            velocity = max(1, min(112, round(78*(max(e["velocity"], .0001)/reference)**.55)))
            start = repeat*n+round(e["time"]*rate)
            end = start+round(e["duration"]*rate)
            notes.setdefault((chan, note), []).append((start, end, velocity))
    for (chan, note), events in notes.items():
        events.sort()
        for index, (start, end, velocity) in enumerate(events):
            # A later note-on owns this pitch; an older release must not stop it.
            if index+1 < len(events):
                end = min(end, events[index+1][0])
            schedule.extend([(start, 2, chan, note, velocity), (end, 0, chan, note, 0)])
    # CC11 continuously shapes held strings/woodwinds as well as new note velocity.
    for sample in range(0, n*repeats, max(1, rate//20)):
        t = (sample % n)/rate
        sections = [s for s in score["sections"] if "frames" in s]
        centers = [(sum(s["frames"])/2-score["first"])/score["fps"] for s in sections]
        dynamic = float(np.interp(t, centers, [s["intensity"] for s in sections]))
        for cue in score["emotion_cues"]:
            center = (cue["frame"]-score["first"])/score["fps"]
            dynamic += .18*float(cue.get("strength", .6))*max(0, 1-abs(t-center)/2)
        for cue in score["sections"]:
            if "time" in cue:
                dynamic += .2*cue["intensity"]*max(0, 1-abs(t-cue["time"])/2)
        expression = round(np.clip(65+45*dynamic, 50, 122))
        for name, chan in channels.items():
            schedule.append((sample, 1, chan, 11, expression))
            schedule.append((sample, 1, chan, 7, round(np.clip(levels[name]*(.91+.09*dynamic), 1, 127))))
    schedule.sort()
    out = np.zeros((n, 2), np.float32)
    at = 0
    try:
        for sample, kind, chan, key, value in schedule + [(n*repeats, 3, 0, 0, 0)]:
            sample = min(sample, n*repeats)
            while at < sample:
                size = min(4096, sample-at)
                block = np.frombuffer(synth.generate(size), np.float32).reshape(-1, 2)
                if at+size > n*(repeats-1):
                    lo = max(at, n*(repeats-1))
                    out[lo-n*(repeats-1):at+size-n*(repeats-1)] = block[lo-at:]
                at += size
            if at >= n*repeats:
                break
            if kind == 0:
                synth.noteoff(chan, key)
            elif kind == 1:
                synth.control_change(chan, key, value)
            elif kind == 2:
                synth.noteon(chan, key, value)
    finally:
        synth.sfunload(sfid)
    score["renderer"] = dict(backend="soundfont", font=str(font_path()),
                             sha256=hashlib.sha256(font_path().read_bytes()).hexdigest(),
                             programs=programs, drum_channel=10, controllers=[7, 10, 11], expression_hz=20)
    return out


if __name__ == '__main__':
    score = json.load(sys.stdin)
    np.save(sys.argv[1], render_raw(score, 48000), allow_pickle=False)
    print(json.dumps(score['renderer']))
