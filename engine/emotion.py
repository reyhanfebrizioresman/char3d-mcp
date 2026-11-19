"""Small, local sentence-emotion matcher for Indonesian/Malay and English.

Uses the same word normalization and suffix rules as semantic gestures. No model,
network or Blender dependency; negation suppresses a nearby match, without guessing
its opposite emotion.
"""
import re

SUFFIXES = ("nya", "lah", "kah", "pun", "kan", "an", "ku", "mu")


def normalize(word):
    return re.sub(r"[^\w']+", "", word.lower().replace("’", "'")).strip("'")

# emotion -> (Indonesian/Malay words, English words)
LEXICON = {
    "joy": ("senang bahagia gembira hebat mantap bagus keren sukacita seronok suka",
            "happy glad joyful delighted great good awesome wonderful love"),
    "sad": ("sedih maaf kecewa dukacita menyesal",
            "sad sorry unfortunately unhappy disappointed grief regret"),
    "surprise": ("wow wah astaga ternyata terkejut kaget menakjubkan",
                 "wow amazing surprised surprising incredible unexpected"),
    "anger": ("marah kesal benci geram jengkel",
              "angry annoyed hate furious frustrating frustrated"),
    "fear": ("takut khawatir risau bimbang bahaya cemas ngeri",
             "afraid scared worried worry danger dangerous terrified anxious"),
    "thinking": ("hmm mungkin pikir berpikir fikir berfikir renung",
                 "hmm maybe perhaps think thinking consider wonder"),
}
PHRASES = {
    "id": {("sayang", "sekali"): "sad", ("luar", "biasa"): "joy",
           ("coba", "pikir"): "thinking", ("cuba", "fikir"): "thinking",
           ("terima", "kasih"): "joy"},
    "en": {("what", "a", "pity"): "sad", ("so", "sorry"): "sad",
           ("think", "about"): "thinking"},
}
NEGATIONS = {
    "id": set("tidak tak bukan jangan nggak gak enggak tiada belum tanpa".split()),
    "en": set("not no never without hardly don't doesn't didn't isn't aren't wasn't "
              "weren't can't cannot won't wouldn't shouldn't couldn't".split()),
}
CLAUSES = {"tapi", "tetapi", "namun", "melainkan", "but", "however", "yet"}
EXPRESSION = {"joy": "big_smile", "sad": "sad", "surprise": "surprised",
              "anger": "angry", "fear": "fear", "thinking": "thinking", "neutral": "neutral"}


def _root(word, vocabulary):
    if word in vocabulary:
        return word
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            root = word[:-len(suffix)]
            if root in vocabulary:
                return root
    return word


def sentences(words):
    """Split stored (word, start, end) tuples at . ! ?, retaining original word times."""
    group = []
    for word in words:
        group.append(word)
        if re.search(r"[.!?]", word[0]):
            yield group
            group = []
    if group:
        yield group


def classify(words, language="auto"):
    """Return emotion, unscaled strength and question flag for one sentence.

    auto matches both vocabularies (including code-switching); id and ms share one.
    Phrases win over individual words. Negation covers the previous three tokens,
    stopping at a comma, colon, semicolon or a contrasting conjunction.
    """
    if language not in ("auto", "id", "ms", "en"):
        raise ValueError("language must be 'auto', 'id', 'ms' or 'en'")
    langs = ("id", "en") if language == "auto" else ("id" if language == "ms" else language,)
    vocab = {w: e for e, columns in LEXICON.items() for lang in langs
             for w in columns[0 if lang == "id" else 1].split()}
    phrases = {p: e for lang in langs for p, e in PHRASES[lang].items()}
    phrase_order = sorted(phrases, key=len, reverse=True)
    negations = set().union(*(NEGATIONS[lang] for lang in langs))
    norm = [_root(normalize(w[0]), vocab.keys() | negations) for w in words]
    scores, negated = {}, False
    i = 0
    while i < len(words):
        phrase = next((p for p in phrase_order
                       if tuple(norm[i:i + len(p)]) == p), None)
        emotion = phrases[phrase] if phrase else vocab.get(norm[i])
        if emotion:
            scope = []
            for j in range(i - 1, max(-1, i - 4), -1):
                if norm[j] in CLAUSES or re.search(r"[,;:]", words[j][0]):
                    break
                scope.append(norm[j])
            if sum(w in negations for w in scope) % 2:
                negated = True
            else:
                scores[emotion] = scores.get(emotion, 0) + (1.3 if phrase else 1.0)
        i += len(phrase) if phrase else 1
    text = " ".join(w[0] for w in words)
    question = "?" in text
    if scores:
        emotion = max(scores, key=scores.get)
        strength = (0.4 if emotion == "thinking" else 0.6) + min(0.2, (scores[emotion] - 1) * 0.1)
        strength += 0.15 if "!" in text else 0
    elif question:
        emotion, strength = "thinking", 0.25
    else:
        emotion, strength = ("neutral", 0.0) if negated else ("base", 0.0)
    return emotion, round(strength, 3), question
