"""Word meaning -> gesture: lexicon (Indonesian / Malay / English) and word-time storage.

lip_sync / lip_sync_audio store the spoken words with their frames on the face mesh
(custom property ``char3d_words``); talk_gestures reads them and turns meaningful words into
iconic gestures ("dua" -> two fingers, "saya" -> hand on chest, "besar" -> wide hands, ...).
Pure Python (no bpy) so the matcher can be tested anywhere.
"""
import json
import re

# gesture -> words that trigger it (lower case; Indonesian/Malay first, then English)
LEXICON = {
    "one": "satu pertama kesatu one first 1",
    "two": "dua kedua two second 2",
    "three": "tiga ketiga three third 3",
    "four": "empat keempat four fourth 4",
    "five": "lima kelima five fifth 5",
    "self": "saya aku kami daku i me my mine myself we our",
    "you": "kamu anda kalian engkau kau awak you your yours yourself",
    "this": "ini sini here this these",
    "that": "itu sana situ there that those",
    "big": "besar banyak semua seluruh segala luas raksasa big huge large many all everyone "
           "everything whole massive enormous",
    "small": "kecil sedikit mungil small little tiny few bit",
    "no": "tidak tak bukan jangan nggak gak enggak ndak tiada no not never nothing nobody "
          "don't can't won't isn't",
    "good": "bagus hebat keren mantap sempurna top great good awesome excellent perfect amazing",
    "question": "mungkin apa kenapa mengapa bagaimana gimana apakah maybe perhaps why how what",
    "stop": "tunggu berhenti stop wait",
    "up": "naik tinggi meningkat atas bangkit tumbuh up rise grow higher increase",
    "down": "turun rendah menurun bawah jatuh down lower decrease drop fall",
    "together": "bersama kita bersatu gabung together join connect",
    "think": "pikir berpikir ide ingat bayangkan think idea remember imagine",
    "love": "cinta sayang hati love heart",
}
# two-word phrases checked before single words: (w1, w2) -> gesture (None = suppress)
PHRASES = {
    ("luar", "biasa"): "good", ("salah", "satu"): None, ("one", "of"): None,
    ("tidak", "apa"): "no", ("apa", "kabar"): None, ("terima", "kasih"): "love",
    ("thank", "you"): "love", ("semua", "orang"): "big",
}
# 3 = must show (numbers), 2 = strong meaning, 1 = frequent function words (shown sparingly)
PRIORITY = {"one": 3, "two": 3, "three": 3, "four": 3, "five": 3,
            "self": 1, "you": 1, "this": 1, "that": 1, "question": 1, "together": 1}
NUMBERS = ("one", "two", "three", "four", "five")
SUFFIXES = ("nya", "lah", "kah", "pun", "kan", "an", "ku", "mu")

WORD_TO_GESTURE = {w: g for g, ws in LEXICON.items() for w in ws.split()}


def normalize(word):
    return re.sub(r"[^\w']+", "", word.lower().replace("’", "'")).strip("'")


def gesture_for(word):
    """Gesture name for one word (with Indonesian suffixes stripped), or None."""
    w = normalize(word)
    if not w:
        return None
    if w in WORD_TO_GESTURE:
        return WORD_TO_GESTURE[w]
    for suf in SUFFIXES:                      # bukannya, kamulah, besarnya, pikirkan
        if w.endswith(suf) and len(w) - len(suf) >= 3 and w[:-len(suf)] in WORD_TO_GESTURE:
            return WORD_TO_GESTURE[w[:-len(suf)]]
    return None


def match(words):
    """[(word, frame_start, frame_end)] -> [(index, gesture)] for words with a meaning."""
    out = []
    skip = set()
    norm = [normalize(w[0]) for w in words]
    for i in range(len(words)):
        if i in skip:
            continue
        if i + 1 < len(words) and (norm[i], norm[i + 1]) in PHRASES:
            g = PHRASES[(norm[i], norm[i + 1])]
            skip.add(i + 1)
            if g:
                out.append((i, g))
            continue
        g = gesture_for(words[i][0])
        if g:
            out.append((i, g))
    return out


def select(candidates, fps, min_gap_s=1.0, rng=None, sparse_prob=0.8):
    """Pick gestures that fit: highest priority first, keep them apart in time.

    candidates: [(frame, gesture, word)]. Numbers may follow each other quickly (counting);
    everything else needs min_gap_s; frequent words (priority 1) also need ~4 s between
    repeats of the same gesture and pass a probability check.
    """
    order = sorted(candidates, key=lambda c: (-PRIORITY.get(c[1], 2), c[0]))
    chosen = []
    for frame, g, word in order:
        pr = PRIORITY.get(g, 2)
        if pr == 1 and rng is not None and rng.random() > sparse_prob:
            continue
        ok = True
        for f2, g2, _w in chosen:
            gap = abs(frame - f2) / fps
            need = 0.35 if (g in NUMBERS and g2 in NUMBERS) else min_gap_s
            if g == g2 and pr == 1:
                need = max(need, 4.0)
            elif g == g2:
                need = max(need, 2.0)
            if gap < need:
                ok = False
                break
        if ok:
            chosen.append((frame, g, word))
    return sorted(chosen)


# ---- word timing storage (on the face/body mesh)
PROP = "char3d_words"


def store_words(obj, words, frame_start, frame_end):
    """Replace stored words inside [frame_start, frame_end] with words [(w, f0, f1)]."""
    try:
        old = json.loads(obj.get(PROP, "[]"))
    except (TypeError, ValueError):
        old = []
    keep = [w for w in old if w[2] < frame_start or w[1] > frame_end]
    new = [[str(w), round(float(a), 2), round(float(b), 2)] for w, a, b in words]
    obj[PROP] = json.dumps(sorted(keep + new, key=lambda w: w[1]))
    return len(new)


def load_words(obj, frame_start=None, frame_end=None):
    try:
        words = json.loads(obj.get(PROP, "[]"))
    except (TypeError, ValueError):
        return []
    return [tuple(w) for w in words
            if (frame_start is None or w[2] >= frame_start) and (frame_end is None or w[1] <= frame_end)]


def text_word_frames(text, start, step, tokenize):
    """Per-word frames for text lip sync (tokens advance `step` frames each from start+1)."""
    out = []
    for m in re.finditer(r"[\w'’]+([.,!?;:…]+)?", text):    # keep punctuation for captions
        a = len(tokenize(text[:m.start()]))
        b = len(tokenize(text[:m.start() + len(m.group(0)) - len(m.group(1) or "")]))
        out.append((m.group(0), start + 1 + a * step, start + 1 + b * step))
    return out
