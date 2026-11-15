"""Dependency-free ID/MS and English pronunciation and relative phoneme timing.

Symbols use lower-case ARPAbet, plus ny, kh and q (a glottal stop). These are
spelling heuristics, not acoustic forced alignment; all times stay inside the word.
This module has no Blender imports and can also be used by the MCP process.
"""
import math
import re
import unicodedata


WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
ID_WORDS = set("""saya aku kamu anda kita kami mereka dia ini itu dan atau yang di ke dari
untuk dengan tidak bukan ada adalah akan sudah belum bisa punya semua selamat halo
apa kabar terima kasih satu dua tiga empat lima enam tujuh delapan sembilan sepuluh
besar kecil bagus baik sangat hari pagi siang malam makan minum rumah orang bahasa
indonesia melayu boleh nak awak mahu bila mana macam juga saja dalam pada baru
sebuah jadi lebih buat karena kenapa bagaimana ayo mari sekarang sampai pulau amboi
ngopi nyanyi syarat akhir anak bebek nenek enak sekolah bekerja bersama ide sulit""".split())
EN_WORDS = set("""a an the i you he she it we they me my your our their his her this that
these those is am are was were be been being have has had do does did don't not no
yes and or but if of to in on at for from with as by can could will would should
one two three four five six seven eight nine ten hello hi world good morning thank
thanks please people some all many more very what why how when where who which
there here now today about say said says want like love make take give go come
look see think know talk speak voice mouth open close small big english""".split())

# Common irregular/function words. Unknown words still go through ordered LTS rules.
EN_EXCEPTIONS = {w: p.split() for w, p in {
    "a": "ax", "i": "ay", "the": "dh ax", "this": "dh ih s", "that": "dh ae t",
    "these": "dh iy z", "those": "dh ow z", "they": "dh ey", "them": "dh eh m",
    "their": "dh eh r", "there": "dh eh r", "then": "dh eh n", "than": "dh ae n",
    "you": "y uw", "your": "y ao r", "we": "w iy", "he": "h iy", "she": "sh iy",
    "me": "m iy", "be": "b iy", "my": "m ay", "of": "ax v", "to": "t uw",
    "do": "d uw", "does": "d ah z", "done": "d ah n", "is": "ih z", "are": "aa r",
    "was": "w ah z", "were": "w er", "have": "h ae v", "has": "h ae z",
    "one": "w ah n", "two": "t uw", "three": "th r iy", "four": "f ao r",
    "eight": "ey t", "hello": "h ax l ow", "world": "w er l d", "people": "p iy p ax l",
    "some": "s ah m", "come": "k ah m", "love": "l ah v", "give": "g ih v",
    "said": "s eh d", "says": "s eh z", "any": "eh n iy", "many": "m eh n iy",
    "what": "w ah t", "who": "h uw", "where": "w eh r", "why": "w ay",
    "how": "h aw", "now": "n aw", "our": "aw r", "hour": "aw r", "eye": "ay",
    "good": "g uh d", "look": "l uh k", "book": "b uh k", "food": "f uw d",
    "blood": "b l ah d", "would": "w uh d", "could": "k uh d", "should": "sh uh d",
    "through": "th r uw", "though": "dh ow", "thought": "th ao t", "enough": "ih n ah f",
    "laugh": "l ae f", "cough": "k ao f", "rough": "r ah f", "bought": "b ao t",
    "don't": "d ow n t", "can't": "k ae n t", "won't": "w ow n t",
    "i'm": "ay m", "you're": "y ao r", "it's": "ih t s", "we're": "w iy r",
    "i've": "ay v", "i'll": "ay l", "isn't": "ih z ax n t",
}.items()}


def choose_language(text, language=None):
    """Explicit id/ms/en, or lexicon hit rates over the utterance (ties use id)."""
    code = (language or "auto").lower().replace("_", "-").split("-")[0]
    code = {"indonesian": "id", "malay": "ms", "english": "en"}.get(code, code)
    if code != "auto":
        if code not in ("id", "ms", "en"):
            raise ValueError("lip sync language must be auto, id, ms or en")
        return code
    words = [m.group().lower().replace("’", "'")
             for m in WORD_RE.finditer(unicodedata.normalize("NFC", text))]
    count = max(len(words), 1)
    id_rate = sum(w in ID_WORDS for w in words) / count
    en_rate = sum(w in EN_WORDS or w in EN_EXCEPTIONS for w in words) / count
    return "en" if en_rate > id_rate else "id"


def _id_sounds(word):
    # Unmarked e defaults to schwa, except clear-e words and a final closed syllable.
    clear_e = {"bebek", "nenek", "lele", "sate", "sore", "enak", "merah", "beda", "meja"}
    pairs = {"ng": "ng", "ny": "ny", "sy": "sh", "kh": "kh",
             "ai": "ay", "au": "aw", "oi": "oy"}
    letters = dict(zip("aiouécjqx", ("aa", "iy", "ow", "uw", "eh", "ch", "jh", "k", "k s")))
    out, i = [], 0
    while i < len(word):
        pair = word[i:i + 2]
        if pair in pairs:
            out.append(pairs[pair])
            i += 2
            continue
        ch = word[i]
        if ch == "e":
            closed = i == len(word) - 2 and word[-1] not in "aiueo"
            out.append("eh" if word in clear_e or closed else "ax")
        elif ch == "k" and i == len(word) - 1:
            out.append("q")
        elif ch in letters:
            out.extend(letters[ch].split())
        elif ch == "y":
            out.append("y")
        elif ch in "bdfghklmnprstvwz":
            out.append(ch)
        i += 1
    return out


def _en_sounds(word):
    if word in EN_EXCEPTIONS:
        return EN_EXCEPTIONS[word][:]
    if word.endswith("s") and word[:-1] in EN_EXCEPTIONS:
        root = EN_EXCEPTIONS[word[:-1]][:]
        return root + (["ih", "z"] if root[-1] in ("s", "z", "sh", "ch", "jh") else ["z"])
    word = word.replace("é", "e")
    if word.startswith(("kn", "gn", "wr")):
        word = word[1:]
    groups = (("tion", "sh ax n"), ("sion", "zh ax n"), ("tch", "ch"),
              ("dge", "jh"), ("igh", "ay"), ("eigh", "ey"), ("ch", "ch"),
              ("sh", "sh"), ("th", "th"), ("ph", "f"), ("ng", "ng"),
              ("qu", "k w"), ("ck", "k"), ("wh", "w"), ("ee", "iy"),
              ("ea", "iy"), ("oo", "uw"), ("ai", "ey"), ("ay", "ey"),
              ("oa", "ow"), ("ow", "ow"), ("ou", "aw"), ("oi", "oy"),
              ("oy", "oy"), ("au", "ao"), ("aw", "ao"), ("er", "er"),
              ("ir", "er"), ("ur", "er"), ("ar", "aa r"), ("or", "ao r"))
    short = {"a": "ae", "e": "eh", "i": "ih", "o": "aa", "u": "ah"}
    long = {"a": "ey", "e": "iy", "i": "ay", "o": "ow", "u": "uw"}
    out, i = [], 0
    while i < len(word):
        ch = word[i]
        tail = word[i:]
        if tail == "ed" and out:
            out.extend(["ih", "d"] if out[-1] in ("t", "d") else
                       ["t"] if out[-1] in ("p", "k", "f", "s", "sh", "ch") else ["d"])
            break
        if tail == "le" and i > 0 and word[i - 1] not in "aeiou":
            out.extend(["ax", "l"])
            break
        if tail == "e" and i > 1:
            break                         # silent final e; single-syllable be/me use exceptions
        match = next(((g, p) for g, p in groups if tail.startswith(g)), None)
        if match:
            out.extend(match[1].split())
            i += len(match[0])
            continue
        if ch in short:
            magic_e = (len(tail) == 3 and tail[-1] == "e" and tail[1] not in "aeiouwxy")
            out.append(long[ch] if magic_e else short[ch])
        elif ch in "cg":
            soft = i + 1 < len(word) and word[i + 1] in "eiy"
            out.append(("s" if ch == "c" else "jh") if soft else ("k" if ch == "c" else "g"))
        elif ch == "y":
            out.append("iy" if i == len(word) - 1 and i > 1 else "ay" if i else "y")
        elif ch == "x":
            out.extend(["k", "s"])
        elif ch == "j":
            out.append("jh")
        elif ch == "q":
            out.append("k")
        elif ch in "bdfhklmnprstvwz":
            if not (ch == "b" and i == len(word) - 1 and word[i - 1:i] == "m"):
                out.append(ch)
        i += 1
    # Double letters normally represent a single sustained sound.
    return [p for j, p in enumerate(out) if not j or p != out[j - 1]]


def sounds(word, language):
    word = unicodedata.normalize("NFC", word)
    word = "".join(m.group() for m in WORD_RE.finditer(word.lower())).replace("’", "'")
    return _en_sounds(word) if language == "en" else _id_sounds(word)


PHONEME_VISEMES = {
    **dict.fromkeys(("aa", "ae"), "aa_02"), **dict.fromkeys(("ah", "ax"), "aa_ah_ax_01"),
    "ao": "ao_03", **dict.fromkeys(("eh", "ey"), "ey_eh_uh_04"), "er": "er_05",
    **dict.fromkeys(("iy", "ih", "y", "ny"), "y_iy_ih_ix_06"),
    **dict.fromkeys(("uw", "uh", "w"), "w_uw_07"), "ow": "ow_08",
    "aw": "aw_09", "oy": "oy_10", "ay": "ay_11", "h": "h_12", "q": "h_12",
    "r": "r_13", "l": "l_14", **dict.fromkeys(("s", "z"), "s_z_15"),
    **dict.fromkeys(("sh", "ch", "jh", "zh"), "sh_ch_jh_zh_16"),
    **dict.fromkeys(("th", "dh"), "th_dh_17"), **dict.fromkeys(("f", "v"), "f_v_18"),
    **dict.fromkeys(("d", "t", "n"), "d_t_n_19"),
    **dict.fromkeys(("k", "g", "ng", "kh"), "k_g_ng_20"),
    **dict.fromkeys(("m", "b", "p"), "p_b_m_21"),
}
VOWELS = set("aa ae ah ax ao eh ey er iy ih uw uh ow aw oy ay".split())
BILABIALS = {"m", "b", "p"}
ROUND = {"ow", "ao", "uw", "uh", "w", "aw", "oy"}


def relative_duration(phone, final=False):
    duration = (2.0 if phone in ("ay", "aw", "oy", "ey", "ow") else
                1.1 if phone == "ax" else 1.7 if phone in VOWELS else
                0.55 if phone in ("p", "b", "t", "d", "k", "g", "q") else 0.9)
    return duration * (0.65 if final and phone not in VOWELS else 1.0)


def timed_phonemes(words, language):
    """(word, start_frame, end_frame) -> phones with exact floating word boundaries."""
    events = []
    for word, start, end in words:
        start, end = float(start), float(end)
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("word times must be finite and end >= start")
        phones = sounds(word, language)
        if not phones or end == start:
            continue
        weights = [relative_duration(p, j == len(phones) - 1) for j, p in enumerate(phones)]
        durations = [(end - start) * w / sum(weights) for w in weights]
        # At normal speech rates reserve at least one video frame per sound. Keep
        # relative durations for the remaining sounds; never lengthen a fast word.
        if end - start >= len(phones):
            active, remaining = set(range(len(phones))), end - start
            while active:
                scale = remaining / sum(weights[j] for j in active)
                short = {j for j in active if weights[j] * scale < 1.0}
                if not short:
                    for j in active:
                        durations[j] = weights[j] * scale
                    break
                for j in short:
                    durations[j] = 1.0
                remaining -= len(short)
                active -= short
        cursor = start
        for j, (phone, duration) in enumerate(zip(phones, durations)):
            stop = end if j == len(phones) - 1 else cursor + duration
            events.append({"word": word, "phoneme": phone, "viseme": PHONEME_VISEMES[phone],
                           "start": cursor, "end": stop})
            cursor = stop
    return events


def viseme_frames(events, start, end, fps, strength, loudness=None):
    """Smooth, normalized mouth targets per frame, with protected closure/contact peaks.

    Each phoneme gets a peak at an integer frame inside its interval, when one exists.
    Sub-frame phones can be lost at the scene's frame rate; never stretch word timing.
    Smoothstep between peaks has zero slope at held sounds and no Bezier overshoot.
    """
    strength = min(1.0, max(0.0, float(strength)))
    anchors = {int(start): ({}, 0), int(end): ({}, 0)}
    if events:
        anchors.setdefault(math.floor(events[0]["start"]) - 1, ({}, 0))
        anchors.setdefault(math.ceil(events[-1]["end"]), ({}, 0))
    for i, event in enumerate(events):
        p, vis = event["phoneme"], event["viseme"]
        if i + 1 < len(events) and events[i + 1]["start"] - event["end"] > fps * 0.12:
            anchors.setdefault(math.ceil(event["end"]), ({}, 0))
            anchors.setdefault(math.floor(events[i + 1]["start"]) - 1, ({}, 0))
        lo, hi = math.ceil(event["start"]), math.floor(event["end"] - 1e-7)
        if lo > hi:
            event["frame"] = None
            continue
        frame = max(lo, min(hi, round((event["start"] + event["end"]) / 2)))
        event["frame"] = frame
        if not start <= frame < end:
            continue
        loud = loudness(frame) if loudness else 1.0
        weight = strength * (1.0 if p in VOWELS else 0.75) * loud
        priority = event["end"] - event["start"]
        if p in BILABIALS:
            weight = 1.0 if strength else 0.0  # closure cannot be weakened by quiet audio
            priority += 100
        elif p in ("f", "v"):
            weight = max(0.95, strength) if strength else 0.0
            priority += 50
        target = {vis: weight}
        if p not in BILABIALS | {"f", "v"} and p not in ROUND:
            # Start rounding before o/u/w, without carrying it through closed lips.
            for future in events[i + 1:i + 3]:
                gap = max(0.0, future["start"] - event["end"])
                if gap > fps * 0.08 or future["phoneme"] in BILABIALS | {"f", "v"}:
                    break
                if future["phoneme"] in ROUND:
                    anticipation = 0.25 * (1.0 - gap / (fps * 0.08))
                    target[vis] *= 1.0 - anticipation
                    target[future["viseme"]] = weight * anticipation
                    break
        if frame not in anchors or priority > anchors[frame][1]:
            anchors[frame] = (target, priority)
    ordered = sorted((f, values) for f, (values, _) in anchors.items() if start <= f <= end)
    j = 0
    for frame in range(int(start), int(end) + 1):
        while j + 1 < len(ordered) and ordered[j + 1][0] <= frame:
            j += 1
        f0, a = ordered[j]
        f1, b = ordered[min(j + 1, len(ordered) - 1)]
        t = (frame - f0) / (f1 - f0) if f1 > f0 else 0.0
        t = t * t * (3.0 - 2.0 * t)
        yield frame, {v: a.get(v, 0.0) * (1.0 - t) + b.get(v, 0.0) * t for v in a.keys() | b.keys()}
