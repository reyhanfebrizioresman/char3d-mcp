"""Original scoring palettes. Intervals are equal-tempered; no borrowed tunes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    tempo: tuple
    mode: str
    scale: tuple
    grammar: tuple
    instruments: tuple
    feel: str = "straight"
    dynamics: float = .75
    # Keys run round the circle of fifths; seed rotates the full chromatic cycle.
    key_offset: int = 0
    lead: str = "piano"
    lead_octave: int = 5
    arp_steps: tuple = (0, 1, 2, 3, 4, 5, 6, 7)
    melody_beats: tuple = (0, 1, 2, 3)
    bass_steps: tuple = ((0, 0, 1.5), (2, 4, 1.5))
    pad_level: float = .055
    keys_level: float = .22
    lead_level: float = .20
    bass_level: float = .55
    drums: float = 1.
    modes: tuple = ()


MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
PALETTES = {
    "happy": Palette((104, 122), "major", MAJOR, ((0, 3, 4, 0), (0, 5, 3, 4)),
        ("piano", "pluck", "pad", "bass", "kick", "shaker", "hat"), key_offset=0,
        lead="pluck", melody_beats=(0, 1.5, 2, 3.5),
        bass_steps=((0, 0, .85), (1.5, 2, .4), (2, 4, .85), (3.5, 6, .4)), bass_level=.42,
        keys_level=.28, lead_level=.32),
    "warm": Palette((72, 88), "major", MAJOR, ((0, 5, 3, 4), (0, 3, 1, 4)),
        ("epiano", "pluck", "pad", "bass", "rim", "shaker"), "swing", .7, key_offset=7,
        lead="pluck", lead_octave=4, arp_steps=(0, 3, 4, 7), melody_beats=(0, 1.5, 3),
        bass_steps=((0, 0, 1.4), (1.5, 2, .45), (2.5, 4, 1.1)), keys_level=.20, lead_level=.30,
        bass_level=.30, drums=.65),
    "sad": Palette((58, 70), "minor", MINOR, ((0, 5, 2, 6), (0, 3, 6, 0)),
        ("piano", "strings", "pad", "bass"), dynamics=.5, key_offset=2, lead="strings", lead_octave=4,
        arp_steps=(0, 3, 6), melody_beats=(0, 2.5), pad_level=.033, keys_level=.25,
        lead_level=.075, bass_level=.28),
    "romantic": Palette((64, 80), "major", MAJOR, ((0, 5, 1, 4), (3, 0, 1, 4)),
        ("pluck", "strings", "piano", "bass", "shaker"), "lilt", .65, key_offset=9,
        lead="piano", arp_steps=(0, 2, 3, 5, 6), melody_beats=(0, 1.5, 2.5),
        pad_level=.040, keys_level=.32, bass_level=.32, drums=.45),
    "tense": Palette((104, 124), "minor", MINOR, ((0, 0, 5, 4), (0, 1, 5, 4)),
        ("strings", "pluck", "bass", "kick", "frame_drum", "tom", "hat"), dynamics=.95, key_offset=4,
        lead="strings", lead_octave=4, melody_beats=(.5, 1, 1.5, 2.5, 3.5),
        bass_steps=((0, 0, .45), (1, 0, .45), (2, 4, .45), (3, 0, .45)),
        pad_level=.065, keys_level=.28, lead_level=.12, bass_level=.48, drums=1.15,
        modes=("minor", "phrygian")),
    "mysterious": Palette((66, 84), "dorian", (0, 2, 3, 5, 7, 9, 10), ((0, 3, 0, 6), (0, 1, 3, 0)),
        ("bell", "pad", "epiano", "bass", "rim"), dynamics=.6, key_offset=11,
        lead="bell", lead_octave=5, arp_steps=(0, 3, 7), melody_beats=(.5, 2.5),
        pad_level=.08, keys_level=.23, lead_level=.42, bass_level=.25, drums=.55,
        modes=("dorian", "minor")),
    "epic": Palette((86, 106), "minor", MINOR, ((0, 5, 2, 6), (3, 5, 6, 0)),
        ("strings", "piano", "bass", "kick", "tom", "snare", "shaker"), dynamics=1, key_offset=6,
        lead="strings", lead_octave=5, pad_level=.095, keys_level=.24, lead_level=.12,
        bass_steps=((0, 0, 1.4), (1.5, 0, .45), (2, 4, .9), (3, 2, .8)), bass_level=.46, drums=1.35),
    "calm": Palette((54, 68), "major", MAJOR, ((0, 3, 0, 4), (0, 5, 3, 0)),
        ("epiano", "pad", "pluck", "bass"), dynamics=.45, key_offset=1, lead="pluck", lead_octave=4,
        arp_steps=(0, 4), melody_beats=(0, 2.5), bass_steps=((0, 0, 3.3),),
        pad_level=.045, keys_level=.20, lead_level=.24, bass_level=.17),
    "playful": Palette((112, 136), "major", MAJOR, ((0, 1, 4, 0), (0, 5, 3, 4)),
        ("pluck", "bell", "epiano", "bass", "kick", "rim", "hat"), "swing", .8, key_offset=8,
        lead="bell", lead_octave=5, arp_steps=(0, 1, 3, 4, 5, 7), melody_beats=(0, .75, 1.5, 2.5, 3.5),
        bass_steps=((0, 0, .65), (1, 2, .6), (2, 4, .6), (3, 2, .65)),
        pad_level=.020, keys_level=.28, lead_level=.28, bass_level=.40, drums=.95),
    "nostalgic": Palette((68, 84), "major", MAJOR, ((0, 2, 3, 4), (5, 3, 0, 4)),
        ("epiano", "strings", "pluck", "bass", "shaker"), "lilt", .6, key_offset=3,
        lead="pluck", lead_octave=4, arp_steps=(0, 2, 5, 7), melody_beats=(0, 1.5, 3),
        pad_level=.040, keys_level=.22, lead_level=.28, bass_level=.28, drums=.65,
        modes=("major", "mixolydian")),
    "dreamy": Palette((58, 78), "lydian", (0, 2, 4, 6, 7, 9, 11), ((0, 1, 4, 0), (0, 4, 1, 0)),
        ("bell", "pad", "strings", "bass"), dynamics=.5, key_offset=10,
        lead="bell", lead_octave=6, arp_steps=(0, 3, 6), melody_beats=(0, 2.5),
        pad_level=.080, keys_level=.17, lead_level=.23, bass_level=.10),
    # Two pentatonic approximations alternate by seed. These are NOT regional
    # tuning reconstructions, named repertoire, or a simulated gamelan ensemble.
    "nusantara": Palette((80, 100), "pentatonic", (0, 2, 5, 7, 9), ((0, 2, 3, 0), (0, 3, 1, 0)),
        ("metallophone", "bell", "pad", "bass", "gong", "frame_drum", "shaker"), "interlock", .8,
        key_offset=5, lead="metallophone", lead_octave=5, arp_steps=(0, 2, 3, 5, 6, 7),
        melody_beats=(.5, 1.25, 2.5, 3.25), bass_steps=((0, 0, 1.8), (2, 0, 1.8)),
        pad_level=.027, keys_level=.27, lead_level=.22, bass_level=.44, drums=1.1),
}
ALIASES = dict(ceria="happy", hangat="warm", haru="sad", sedih="sad", romantis="romantic",
               tegang="tense", misterius="mysterious", epik="epic", tenang="calm", lucu="playful",
               nostalgia="nostalgic", otomatis="auto", tanpa="none")
EMOTION_MOOD = dict(joy="happy", smile="happy", big_smile="happy", laugh="playful", sad="sad",
                    fear="tense", anger="tense", angry="tense", furious="tense", surprised="playful",
                    surprise="playful", thinking="mysterious", sleepy="calm")


def mood_name(value, allow_none=True):
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise ValueError("music mood must be a string or None")
    value = ALIASES.get(value.strip().lower(), value.strip().lower())
    if value == "none" and allow_none:
        return None
    if value not in (*PALETTES, "auto"):
        raise ValueError(f"music mood must be auto, none or one of {list(PALETTES)}")
    return value


def infer_mood(beats=(), look=None, weather=None, environment=None):
    """Explicit beat emotion, then text sentiment, then look/weather/location."""
    scores = {}
    from ..emotion import classify
    for beat in beats:
        emotion = beat.get("emotion", beat.get("expression"))
        if not emotion and beat.get("text"):
            emotion = classify([(w, 0, 1) for w in beat["text"].split()])[0]
        mood = EMOTION_MOOD.get(emotion)
        if mood:
            scores[mood] = scores.get(mood, 0) + float(beat.get("strength", 1))
    if scores:
        return max(scores, key=scores.get)
    preset = look.get("preset") if isinstance(look, dict) else look
    mood = {"golden_hour": "warm", "sunset": "romantic", "night": "mysterious", "blue_hour": "calm",
            "misty_morning": "calm", "dreamy": "dreamy", "epic": "epic", "overcast_soft": "calm"}.get(preset)
    return mood or {"rain": "nostalgic", "snow": "dreamy", "fog": "mysterious"}.get(weather) or {
        "beach": "calm", "park": "warm", "cafe_terrace": "warm", "stage": "epic",
        "rice_terraces": "nusantara", "mountain_village": "nusantara"}.get(environment, "warm")
