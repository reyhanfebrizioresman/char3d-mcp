"""Readable instrument inventory from the same note events and GM mapping as rendering."""
from .compose import compose
from .soundfont import arrangement, resolve_backend, track

SYNTH_NAMES = {
    'piano': ('piano', 'piano'), 'epiano': ('piano elektrik', 'electric piano'),
    'pad': ('pad nada panjang', 'sustained pad'), 'pluck': ('petikan', 'plucked synth'),
    'bass': ('bas', 'bass'), 'strings': ('gesek', 'strings'), 'bell': ('lonceng', 'bells'),
    'kick': ('drum bas', 'kick'), 'snare': ('snare', 'snare'), 'rim': ('ketukan rim', 'rim'),
    'hat': ('hi-hat', 'hi-hat'), 'shaker': ('shaker', 'shaker'), 'tom': ('tom', 'tom'),
    'frame_drum': ('gendang bingkai', 'frame drum'), 'gong': ('gong', 'gong'),
    'metallophone': ('metalofon', 'metallophone'),
}
GM_NAMES = {
    0: ('piano akustik', 'acoustic piano'), 4: ('piano elektrik', 'electric piano'),
    8: ('celesta', 'celesta'), 9: ('glockenspiel', 'glockenspiel'), 10: ('kotak musik', 'music box'),
    11: ('vibrafon', 'vibraphone'), 12: ('marimba', 'marimba'), 14: ('lonceng tabung', 'tubular bells'),
    24: ('gitar nilon', 'nylon guitar'), 25: ('gitar baja', 'steel guitar'),
    32: ('kontrabas', 'upright bass'), 33: ('bas elektrik', 'electric bass'),
    42: ('selo', 'cello'), 43: ('kontrabas gesek', 'contrabass'), 45: ('gesek pizzicato', 'pizzicato strings'),
    46: ('harpa', 'harp'), 47: ('timpani', 'timpani'), 48: ('ansambel gesek', 'string ensemble'),
    52: ('paduan suara', 'choir'), 55: ('pukulan orkestra', 'orchestra hit'),
    60: ('horn', 'French horn'), 61: ('ansambel tiup logam', 'brass section'), 68: ('obo', 'oboe'),
    71: ('klarinet', 'clarinet'), 72: ('pikolo', 'piccolo'), 73: ('seruling', 'flute'),
    89: ('pad hangat', 'warm pad'), 91: ('pad gesek', 'bowed pad'),
    107: ('koto', 'koto'), 108: ('kalimba', 'kalimba'), 114: ('steel drum', 'steel drum'),
    116: ('taiko', 'taiko'),
}


def describe(mood, seconds=30, tempo=None, seed=0, backend='auto', language='id'):
    if mood is None:
        return 'Tanpa instrumen' if language != 'en' else 'No instruments'
    en = int(language == 'en')
    score = compose(max(.25, seconds), mood, tempo=tempo, seed=seed)
    chosen = resolve_backend(backend)
    if chosen == 'synth':
        names = sorted({e['instrument'] for e in score['events']})
        return ('Sintesis: ' if not en else 'Synth: ')+', '.join(SYNTH_NAMES.get(n, (n, n))[en] for n in names)
    programs = arrangement(mood)
    tracks = {track(e) for e in score['events']}
    names = [f"GM {p} {GM_NAMES.get(p, ('program', 'program'))[en]}" for p in sorted({programs[t] for t in tracks-{'drums'}})]
    if 'drums' in tracks:
        names.append('perkusi GM' if not en else 'GM percussion')
    return 'SoundFont ('+('program nol-basis' if not en else 'zero-based programs')+'): '+', '.join(names)
