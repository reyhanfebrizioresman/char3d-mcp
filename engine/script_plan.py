"""Small, deterministic screenplay parser. No Blender imports or scene side effects."""
import copy
import math
import random
import re


HAIR = ("afro01", "bob01", "bob02", "braid01", "long01", "ponytail01",
        "short01", "short02", "short03", "short04")
CLOTHES = tuple(f"male_casualsuit{i:02d}" for i in range(1, 7)) + (
    "male_elegantsuit01", "male_worksuit01", "female_casualsuit01", "female_casualsuit02",
    "female_elegantsuit01", "female_sportsuit01", "fedora01", "fedora_cocked",
) + tuple(f"shoes{i:02d}" for i in range(1, 7))
OUTFITS = ("casual", "formal", "sport", "summer", "winter")
PROPS = {"kursi": "chair", "bangku": "bench", "sofa": "sofa", "meja": "table",
         "cangkir": "cup", "gelas": "cup", "telepon": "phone", "ponsel": "phone",
         "buku": "book", "mikrofon": "handheld_microphone"}
EMOTIONS = {"happy": "smile", "senang": "smile", "bahagia": "smile", "sedih": "sad",
            "marah": "angry", "kaget": "surprised", "surprise": "surprised",
            "takut": "fear", "worried": "fear"}
EXPRESSIONS = set("neutral smile big_smile laugh sad angry furious surprised fear disgust smirk "
                  "wink_left wink_right eyes_closed pout kiss thinking shout sleepy look_left "
                  "look_right look_up look_down tongue_out".split())
VERBS = {"jalan": "walk", "berjalan": "walk", "walk": "walk", "walks": "walk",
         "duduk": "sit", "sits": "sit", "sit": "sit", "berdiri": "stand",
         "stands": "stand", "stand": "stand", "melambai": "gesture", "waves": "gesture",
         "wave": "gesture", "memegang": "hold", "holds": "hold", "hold": "hold",
         "menunjuk": "point", "points": "point", "point": "point", "melihat": "look",
         "looks": "look", "look": "look"}
INTERACTIONS = {
    "handshake": r"bersalaman|berjabat tangan|shakes? hands?",
    "hug": r"berpelukan|memeluk|hugs?",
    "high_five": r"tos|high[ -]fives?",
    "fist_bump": r"adu tinju|fist[ -]bumps?",
}


def _interaction_direction(text):
    handover = re.fullmatch(r"(.+?)\s+(?:memberikan|menyerahkan|hands?|gives?)\s+(?:the\s+)?(.+?)\s+(?:kepada|ke|to)\s+(.+)", text, re.I)
    if handover:
        return {"do": "interact", "who": handover[1], "with": handover[3],
                "kind": "handover", "prop": _target(handover[2])}
    for kind, verbs in INTERACTIONS.items():
        pair = re.fullmatch(r"(.+?)\s+(?:dan|and|&)\s+(.+?)\s+(?:" + verbs + r")", text, re.I)
        if pair:
            return {"do": "interact", "who": pair[1], "with": pair[2], "kind": kind}
        directed = re.fullmatch(r"(.+?)\s+(?:" + verbs + r")(?:\s+(?:(?:dengan|with)\s+)?(.+))?", text, re.I)
        if directed:
            return {"do": "interact", "who": directed[1], "with": directed[2], "kind": kind}
    return None


def _number(value, label, low=0, high=100000):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f"{label} must be in {low}..{high}")
    return n


def _target(text):
    text = re.sub(r"^(?:(?:ke|di|pada|at|to|on|in|the|a|sebuah)\s+)+", "", text.strip(), flags=re.I)
    text = text.strip().rstrip(".")
    coord = re.fullmatch(r"\[?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]?", text)
    return [float(x) for x in coord.groups()] if coord else PROPS.get(text.casefold(), text)


def _descriptors(text, char, warnings):
    # Preserve case in engine voice IDs (Edge names are case-sensitive), before
    # age/catalog parsing can mistake digits/underscores inside a voice for assets.
    voice = re.search(r"\b(?:suara|voice)\s*:\s*([^\s,()]+)", text, re.I)
    if voice:
        char["voice"] = voice[1]
        text = text[:voice.start()] + " " + text[voice.end():]
    rest = text.lower()
    for pattern, pitch in ((r"suara\s+berat|deep\s+voice", -3),
                            (r"suara\s+tinggi|high\s+voice", 3)):
        if re.search(pattern, rest):
            char["pitch_offset"] = pitch
            rest = re.sub(pattern, " ", rest)
    genders = {"perempuan": 0, "wanita": 0, "female": 0, "laki-laki": 1, "pria": 1, "male": 1}
    for word, gender in genders.items():
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", rest):
            char["gender"] = gender
            rest = re.sub(r"(?<!\w)" + re.escape(word) + r"(?!\w)", " ", rest)
    age = re.search(r"\b\d{1,3}\b", rest)
    if age:
        char["age"] = int(age.group())
        rest = rest[:age.start()] + " " + rest[age.end():]
    for asset in sorted(HAIR + CLOTHES, key=len, reverse=True):
        pattern = r"(?<![\w-])" + re.escape(asset) + r"(?![\w-])"
        if re.search(pattern, rest):
            if asset in HAIR:
                char["hair"] = asset
            else:
                char.setdefault("clothes", []).append(asset)
            rest = re.sub(pattern, " ", rest)
    # Pack names cannot be classified without Blender's installed catalog. Keep
    # their exact spelling for build-time resolution (including hair and beards).
    for asset in re.findall(r"\b[\w-]*_[\w-]+\b", rest):
        char.setdefault("assets", []).append(asset)
        rest = rest.replace(asset, " ")
    for words, asset in ((r"ponytail|ekor kuda", "ponytail01"), (r"braid|kepang", "braid01"),
                         (r"long|panjang", "long01"), (r"short|pendek", "short01"),
                         (r"bob", "bob01"), (r"afro", "afro01")):
        if re.search(r"\b(?:" + words + r")\b", rest):
            char["hair"] = asset
            rest = re.sub(r"\b(?:" + words + r")\b", " ", rest)
    sex = "female" if char.get("gender", 0.5) < 0.5 else "male"
    # A literal suit keeps the original system mapping; style descriptors use
    # the installed, seeded outfit picker instead of forcing a system suit.
    if re.search(r"\bsuit\b", rest):
        char.setdefault("clothes", []).append(f"{sex}_elegantsuit01")
        rest = re.sub(r"\bsuit\b", " ", rest)
    for words, outfit in ((r"casual|kasual", "casual"),
                          (r"formal|jas|resmi|elegant", "formal"),
                          (r"sport|sports|olahraga", "sport"),
                          (r"musim panas|summer", "summer"),
                          (r"musim dingin|winter|jaket|coat", "winter")):
        if re.search(r"\b(?:" + words + r")\b", rest):
            char["outfit"] = outfit
            rest = re.sub(r"\b(?:" + words + r")\b", " ", rest)
    if re.search(r"\b(?:gaun|dress|rok|skirt)\b", rest) and sex == "female":
        char["outfit"] = "summer"
        rest = re.sub(r"\b(?:gaun|dress|rok|skirt)\b", " ", rest)
    for words, field, value in ((r"jenggot|brewok|beard|kumis|moustache|mustache", "beard", True),
                                (r"kacamata|glasses", "accessories", "glasses"),
                                (r"topi|hat", "accessories", "hat")):
        if re.search(r"\b(?:" + words + r")\b", rest):
            if field == "accessories":
                char.setdefault(field, []).append(value)
            else:
                char[field] = value
            rest = re.sub(r"\b(?:" + words + r")\b", " ", rest)
    rest = re.sub(r"\b(?:rambut|hair|baju|clothes|clothing|tahun|years?|old|berusia|aged?|with|dengan)\b", " ", rest)
    unknown = " ".join(re.findall(r"[\w-]+", rest))
    if unknown:
        warnings.append(f"{char['id']}: unknown descriptors: {unknown}")


def _direction(text, warnings):
    interaction = _interaction_direction(text)
    if interaction:
        return interaction
    pause = re.fullmatch(r"(?:pause|jeda|tunggu)\s+(\d+(?:\.\d+)?)(?:\s+(?:seconds?|detik))?", text, re.I)
    if pause:
        return {"do": "pause", "seconds": float(pause[1])}
    match = re.match(r"^(.+?)\s+(" + "|".join(VERBS) + r")\b\s*(.*)$", text, re.I)
    if not match:
        warnings.append(f"Unknown stage direction: {text}")
        return None
    who, verb, tail = match.groups()
    action = VERBS[verb.casefold()]
    beat = {"do": "gesture" if action == "point" else action, "who": who.strip()}
    if action == "walk":
        beat["to"] = _target(tail)
    elif action == "sit":
        beat["on"] = _target(tail) or "chair"
    elif action == "hold":
        hand = re.search(r"\b(?:left|kiri|right|kanan)\b", tail, re.I)
        beat["hand"] = "left" if hand and hand[0].lower() in ("left", "kiri") else "right"
        tail = re.sub(r"\b(?:with|in|the|hand|tangan|dengan|left|right|kiri|kanan)\b", " ", tail, flags=re.I)
        beat["prop"] = _target(" ".join(tail.split()))
    elif action in ("gesture", "point"):
        beat["name"] = "point_forward" if action == "point" else "wave"
        if tail:
            warnings.append(f"{who}: gesture target ignored: {tail}")
    elif action == "look":
        beat["at"] = _target(tail)
    elif tail.lower() not in ("", "up"):
        warnings.append(f"{who}: unknown stage words: {tail}")
    return beat


def parse_script(script, name=None, environment=None, seed=0, fps=24):
    """Normalize dict or bilingual text. Estimated frames never read files or mutate a scene."""
    warnings = []
    if isinstance(script, str):
        raw = {"characters": [], "beats": []}
        chars = {}
        for lineno, line in enumerate(script.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            header = re.match(r"^(JUDUL|TITLE|LOKASI|LOCATION|CUACA|WEATHER)\s*:\s*(.*)$", line, re.I)
            if header:
                key = ("title" if header[1].upper() in ("JUDUL", "TITLE") else
                       "weather" if header[1].upper() in ("CUACA", "WEATHER") else "environment")
                raw[key] = header[2]
            elif line.startswith("[") and line.endswith("]"):
                beat = _direction(line[1:-1].strip(), warnings)
                if beat:
                    raw["beats"].append(beat)
            else:
                match = re.fullmatch(r"([^:()]+?)(?:\s*\(([^)]*)\))?\s*:\s*(.+)", line)
                if not match:
                    warnings.append(f"Line {lineno}: unrecognized text: {line}")
                    continue
                ident, desc, text = match.groups()
                ident = ident.strip()
                key = ident.casefold()
                if key not in chars:
                    chars[key] = {"id": ident}
                    raw["characters"].append(chars[key])
                if desc:
                    _descriptors(desc, chars[key], warnings)
                raw["beats"].append({"say": chars[key]["id"], "text": text})
    elif isinstance(script, dict):
        raw = copy.deepcopy(script)
    else:
        raise ValueError("script must be a dict or screenplay text")
    if not isinstance(raw.get("characters", []), list) or not isinstance(raw.get("beats", []), list):
        raise ValueError("characters and beats must be lists")
    rng = random.Random(seed)
    characters, ids = [], {}
    for char in raw.get("characters", []):
        if not isinstance(char, dict) or not isinstance(char.get("id"), str) or not char["id"].strip():
            raise ValueError("each character needs a nonempty string id")
        ident = char["id"].strip()
        if ident.casefold() in ids:
            raise ValueError(f"duplicate character id: {ident}")
        ids[ident.casefold()] = ident
        char["id"] = ident
        char["gender"] = _number(char.get("gender", 0.5), "gender", 0, 1)
        char["age"] = _number(char.get("age", 28), "age", 1, 90)
        sex = "female" if char["gender"] < 0.5 else "male"
        char.setdefault("hair", "bob01" if sex == "female" else "short01")
        default_clothes = [f"{sex}_casualsuit{rng.randint(1, 2):02d}", "shoes01"]
        if char.get("outfit") is not None and char["outfit"] not in OUTFITS:
            raise ValueError(f"outfit must be one of {list(OUTFITS)} or None")
        if not char.get("outfit") and not char.get("assets"):
            char.setdefault("clothes", default_clothes)
        if char["hair"] is not None and not isinstance(char["hair"], str):
            raise ValueError("hair must be a catalog name or None")
        if char.get("beard") is not None and not isinstance(char["beard"], (str, bool)):
            raise ValueError("beard must be a catalog name, boolean or None")
        for field, known in (("clothes", CLOTHES), ("assets", ()), ("accessories", ("glasses", "hat"))):
            if field not in char:
                continue
            if not isinstance(char[field], list) or not all(isinstance(a, str) for a in char[field]):
                raise ValueError(f"{field} must be a list of string catalog names")
            for asset in char[field]:
                if asset not in known:
                    if field == "accessories":
                        raise ValueError("accessories must contain glasses or hat")
                    warnings.append(f"{ident}: unverified {field} asset {asset!r}; checked at build time")
        for field, known in (("hair", HAIR), ("beard", ())):
            if isinstance(char.get(field), str) and char[field] and char[field] not in known:
                warnings.append(f"{ident}: unverified {field} asset {char[field]!r}; checked at build time")
        if "voice" in char and (not isinstance(char["voice"], str) or not char["voice"].strip()):
            raise ValueError("voice must be a nonempty engine:name string")
        for key, default, low, high in (("pitch", 0, -12, 12), ("pitch_offset", 0, -12, 12), ("rate", 1, .5, 2)):
            if key in char:
                char[key] = _number(char.get(key, default), key, low, high)
        for key in set(char) - {"id", "gender", "age", "hair", "clothes", "race", "muscle", "weight", "height", "proportions", "skin", "outfit", "beard", "assets", "accessories", "voice", "pitch", "pitch_offset", "rate"}:
            warnings.append(f"{ident}: unknown character field {key!r}; ignored")
            del char[key]
        for key in ("muscle", "weight", "height", "proportions"):
            if key in char:
                char[key] = _number(char[key], key, 0, 1)
        if "race" in char:
            if not isinstance(char["race"], dict):
                raise ValueError("race must be a dict of ethnicity weights")
            char["race"] = {k: _number(v, "race weight", 0, 1) for k, v in char["race"].items()}
            if not sum(char["race"].values()):
                raise ValueError("race weights must have a positive total")
        characters.append(char)

    beats, frame = [], 1
    for source in raw.get("beats", []):
        if not isinstance(source, dict):
            raise ValueError("each beat must be a dict")
        beat = dict(source)
        if "say" in beat:
            if not (beat.get("text") or beat.get("audio")):
                raise ValueError("speech needs text or audio")
            if not all(isinstance(beat[k], str) for k in ("text", "audio") if k in beat):
                raise ValueError("speech text/audio must be strings")
            if beat.get("emotion"):
                value = str(beat["emotion"]).lower()
                beat["emotion"] = EMOTIONS.get(value, value)
                if beat["emotion"] not in EXPRESSIONS:
                    warnings.append(f"Unknown emotion: {value}; using neutral")
                    beat["emotion"] = "neutral"
            duration = max(4, round(len(beat.get("text", "")) / 14 * fps) + 3)
        elif "title" in beat:
            duration = max(2, round(_number(beat.get("seconds", 2), "title seconds", 0.1, 60) * fps))
        elif beat.get("do") in ("walk", "sit", "stand", "hold", "gesture", "pose", "look", "pause", "interact"):
            action = beat["do"]
            for key in {"walk": ["to"], "hold": ["prop"], "look": ["at"], "gesture": ["name"], "pose": ["name"]}.get(action, []):
                if not beat.get(key):
                    raise ValueError(f"{action} needs {key}")
            if action == "sit":
                beat.setdefault("on", "chair")
            if action == "hold" and beat.get("hand", "right") not in ("left", "right"):
                raise ValueError("hand must be left or right")
            if action == "pause":
                beat["seconds"] = _number(beat.get("seconds", 1), "pause seconds", 0, 60)
            if action == "interact":
                if beat.get("kind") not in (*INTERACTIONS, "handover", "pat_shoulder"):
                    raise ValueError("unknown interaction kind")
                if str(beat.get("who", "")).casefold() in ("mereka", "they"):
                    if len(characters) != 2:
                        raise ValueError("they/mereka requires exactly two declared characters")
                    beat["who"], beat["with"] = [c["id"] for c in characters]
                partner = str(beat.get("with", "")).strip()
                if partner.casefold() not in ids:
                    raise ValueError(f"unknown interaction partner: {partner!r}")
                beat["with"] = ids[partner.casefold()]
                if beat.get("kind") == "handover" and not beat.get("prop"):
                    raise ValueError("handover needs prop")
                if beat.get("side", "right") not in ("right", "left"):
                    raise ValueError("interaction side must be right or left")
                if not isinstance(beat.get("approach", True), bool):
                    raise ValueError("interaction approach must be a bool")
                if "hold_seconds" in beat:
                    beat["hold_seconds"] = _number(beat["hold_seconds"], "hold_seconds", 0, 30)
            duration = {"walk": 72, "sit": 21, "stand": 21, "hold": 12,
                        "gesture": 37, "pose": 24, "look": 24, "interact": round(3*fps),
                        "pause": max(1, round(beat.get("seconds", 1) * fps))}[action]
        else:
            warnings.append(f"Unknown beat ignored: {source}")
            continue
        who_key = "say" if "say" in beat else "who" if beat.get("do") != "pause" and "title" not in beat else None
        if who_key:
            ident = str(beat.get(who_key, "")).strip()
            if ident.casefold() not in ids:
                raise ValueError(f"unknown character: {ident!r}; declare it in characters or a speech line")
            beat[who_key] = ids[ident.casefold()]
            if beat.get("do") == "interact" and beat["who"] == beat["with"]:
                raise ValueError("interaction needs two different characters")
        for key in ("to", "on", "prop", "at"):
            if key in beat:
                value = beat[key]
                if isinstance(value, str):
                    beat[key] = ids.get(value.casefold(), PROPS.get(value.casefold(), value))
                elif key not in ("to", "at") or not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
                    raise ValueError(f"{key} must name an object or contain XY/XYZ coordinates")
                else:
                    beat[key] = [_number(x, key, -1000, 1000) for x in value]
        beat["estimated_frames"] = [frame, frame + duration - 1]
        frame += duration + (round(0.35 * fps) if "say" in beat else 0)
        beats.append(beat)
    if not characters or len(characters) > 4:
        raise ValueError("script needs 1 to 4 characters")
    if not beats:
        raise ValueError("script has no recognized beats")
    location = environment if environment is not None else raw.get("environment")
    aliases = {"jalan": "city_street", "jalan kota": "city_street", "street": "city_street",
               "taman": "park", "park": "park", "kafe": "cafe_terrace", "cafe": "cafe_terrace",
               "pantai": "beach", "beach": "beach"}
    location = aliases.get(str(location).strip().casefold(), location)
    weather = raw.get("weather")
    extra = {}
    if weather is not None:
        weather = {"hujan": "rain", "salju": "snow", "kabut": "fog", "berangin": "wind",
                   "cerah": "clear"}.get(str(weather).strip().casefold(), str(weather).strip().casefold())
        if weather not in ("clear", "rain", "snow", "fog", "wind"):
            raise ValueError("weather must be clear/rain/snow/fog/wind or Indonesian aliases")
        extra["weather"] = weather
    return {"name": name or raw.get("title") or "ScriptScene", "title": raw.get("title"),
            "environment": location, **extra,
            "characters": characters, "beats": beats, "estimated_frames": [1, max(2, frame - 1)],
            "fps": fps, "seed": seed, "warnings": warnings}
