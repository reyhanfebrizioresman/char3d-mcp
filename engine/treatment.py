"""Original directing contract and seeded template editorial pass. No Blender or IO."""
import math


def obj(properties):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties, 'required': list(properties)}


def array(item, **kw):
    return dict(type='array', items=item, **kw)


TEXT = {'type': 'string', 'minLength': 1}
TIME = {'type': 'number', 'minimum': 0}
TREATMENT_SCHEMA = obj({
    'structures': obj({'candidates': array(TEXT, minItems=3, maxItems=3), 'chosen': TEXT, 'why': TEXT}),
    'logline': TEXT, 'arc': obj({k: TEXT for k in ('setup', 'turn', 'ending')}),
    'hook': TEXT, 'ending_echo': TEXT, 'signature_shot': TEXT,
    'shot_list': array(obj({'beat': {'type': 'integer', 'minimum': 0}, 'size': TEXT, 'angle': {'type': 'number'},
                           'move': TEXT, 'seconds': {'type': 'number', 'exclusiveMinimum': 0}, 'reason': TEXT}), minItems=1),
    'beat_sheet': array(obj({'t': TIME, 'event': TEXT}), minItems=1),
    'cue_map': obj({'tempo': {'type': 'number', 'minimum': 40, 'maximum': 180},
        'sections': array(obj({'name': TEXT, 'start_s': TIME, 'end_s': TIME, 'music_state': TEXT,
                               'instrumentation': TEXT}), minItems=1),
        'cuts': array(TIME), 'silences': array(obj({'t': TIME, 'seconds': {'type': 'number', 'exclusiveMinimum': 0}})),
        'transitions': array(obj({'t': TIME, 'kind': TEXT, 'audio': {'enum': ['j_cut', 'l_cut', None]}}))}),
    'sound_design': array(obj({k: TEXT for k in ('section', 'ambience', 'foley', 'music')}), minItems=1),
    'subtitle_design': TEXT,
})


def check(value, schema, path='treatment'):
    """Small closed-schema validator used for both online transports and offline drafts."""
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: unsupported value')
    kind = schema.get('type')
    valid = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
             'string': lambda: isinstance(value, str), 'number': lambda: type(value) in (int, float) and math.isfinite(value),
             'integer': lambda: type(value) is int}.get(kind, lambda: True)
    if not valid():
        raise ValueError(f'{path}: expected {kind}')
    if kind == 'object':
        if set(value) != set(schema['required']):
            raise ValueError(f'{path}: needs exactly {schema["required"]}')
        for key, val in value.items():
            check(val, schema['properties'][key], path+'.'+key)
    if kind in ('array', 'string'):
        if len(value) < schema.get('minItems', schema.get('minLength', 0)) or len(value) > schema.get('maxItems', 100000):
            raise ValueError(f'{path}: invalid length')
        if kind == 'array':
            for i, val in enumerate(value):
                check(val, schema['items'], f'{path}[{i}]')
    if kind in ('number', 'integer'):
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf) or value <= schema.get('exclusiveMinimum', -math.inf):
            raise ValueError(f'{path}: outside permitted range')


def validate_treatment(value):
    from engine.director_cues import SIZES, MOVES
    check(value, TREATMENT_SCHEMA)
    if value['structures']['chosen'] not in value['structures']['candidates']:
        raise ValueError('treatment.structures.chosen must select a candidate')
    for shot in value['shot_list']:
        if shot['size'] not in SIZES or shot['move'] not in MOVES:
            raise ValueError('treatment shot_list needs executable sizes and moves')
    for section in value['cue_map']['sections']:
        if section['end_s'] <= section['start_s']:
            raise ValueError('treatment section must have positive duration')
    for key in ('cuts',):
        if value['cue_map'][key] != sorted(value['cue_map'][key]):
            raise ValueError('treatment cuts must be chronological')
    return value


def markdown(t):
    lines = ['## Treatment', '', '**Logline:** '+t['logline'], '', '**Structure choices:**']
    lines += ['- '+v for v in t['structures']['candidates']]
    lines += ['', '**Chosen:** '+t['structures']['chosen']+'. '+t['structures']['why'], '']
    lines += [f'**{k.title()}:** {v}' for k, v in t['arc'].items()]
    lines += ['', '**Opening three seconds:** '+t['hook'], '**Opening returned:** '+t['ending_echo'],
              '**Peak shot:** '+t['signature_shot'], '', '| Beat | Size / move / angle | Seconds | Purpose |',
              '| --- | --- | --- | --- |']
    lines += [f"| {s['beat']} | {s['size']} / {s['move']} / {s['angle']:g}° | {s['seconds']:g} | {s['reason']} |" for s in t['shot_list']]
    lines += ['', '### Beat timing', ''] + [f"- {b['t']:g}s: {b['event']}" for b in t['beat_sheet']]
    lines += ['', f"### Sound and cut grid · {t['cue_map']['tempo']:g} BPM", '',
              '| Section | Time | Music | Instruments |', '| --- | --- | --- | --- |']
    lines += [f"| {s['name']} | {s['start_s']:g}–{s['end_s']:g}s | {s['music_state']} | {s['instrumentation']} |" for s in t['cue_map']['sections']]
    lines += ['', 'Cuts (seconds): '+', '.join(str(x) for x in t['cue_map']['cuts'])]
    lines += [f"- Silence: {s['t']:g}s for {s['seconds']:g}s; keep movement sounds." for s in t['cue_map']['silences']]
    lines += [f"- Transition at {s['t']:g}s: {s['kind']}, audio {s['audio'] or 'picture-aligned'}." for s in t['cue_map']['transitions']]
    lines += ['', '| Section | Ambience | Foley | Music |', '| --- | --- | --- | --- |']
    lines += [f"| {s['section']} | {s['ambience']} | {s['foley']} | {s['music']} |" for s in t['sound_design']]
    return '\n'.join(lines+['', '**Captions:** '+t['subtitle_design']])


def template_pass(script, opts, genre, chars):
    """Place decisions at speech beats, then derive timing from the executable plan."""
    import re
    from engine.film_plan import is_film, parse_film
    from engine.script_plan import parse_script
    en = opts['language'] == 'en'
    solo = len(chars) == 1
    parts = re.split(r'(?=^ADEGAN\s+\d+:)', script, flags=re.M) if is_film(script) else [script]
    output = []
    for part in parts:
        raw = part.splitlines()
        speech = [i for i, ln in enumerate(raw) if re.match(r'^[^:[\]]+(?:\([^)]*\))?: .+', ln)
                  and not re.match(r'^(JUDUL|LOKASI|SUASANA|CUACA|ADEGAN|TITLE|LOCATION):', ln)
                  and not ln.startswith(('ADEGAN ', '[', 'MUSIK:', 'MUSIC:'))]
        if not speech:
            output.extend(raw)
            continue
        peak = speech[min(len(speech)-1, max(1, len(speech)*2//3))]
        inserts = {speech[0]: ['[MUSIC: calm]', '[CAMERA: medium two-shot, static]']}
        if len(speech) > 2:
            who = re.match(r'^([^:(]+)', raw[speech[len(speech)//3]])[1].strip()
            inserts.setdefault(speech[len(speech)//3], []).append(f'[CAMERA: medium_close {who}, static]')
        who = re.match(r'^([^:(]+)', raw[peak])[1].strip()
        inserts.setdefault(peak, []).extend(['[SILENCE 1 second]', '[MUSIC: warm]', f'[CAMERA: close-up {who}, push in]'])
        if speech[-1] != peak:
            inserts.setdefault(speech[-1], []).append('[CAMERA: medium two-shot, static]')
        for i, ln in enumerate(raw):
            output.extend(inserts.get(i, []))
            output.append(ln)
        # The ending reaction deliberately lasts longer than an ordinary gap.
        output += ['[pause 2 seconds]']
    script = '\n'.join(output)
    plan = parse_film(script, seed=opts['seed']) if is_film(script) else parse_script(script, seed=opts['seed'])
    scenes = plan.get('scenes') or [{'plan': plan, 'film_frames': plan['estimated_frames'], 'transition_in': {'kind': 'cut'}}]
    beats, shots, silences, transitions, sections = [], [], [], [], []
    for scene in scenes:
        p = scene['plan']; offset = scene['film_frames'][0]-1
        cues = [(i, b) for i, b in enumerate(p['beats']) if b.get('do') == 'camera']
        for j, (i, b) in enumerate(cues):
            start = b['estimated_frames'][0]
            end = cues[j+1][1]['estimated_frames'][0] if j+1 < len(cues) else p['estimated_frames'][1]+1
            shots.append(dict(beat=len(beats)+i, size=b['shot'], angle=b.get('angle', 20), move=b['move'],
                              seconds=round((end-start)/24, 3), reason=(('Hold the changed response' if b['move']=='push_in' else 'Keep the speaker in context' if solo else 'Show how the partners relate') if en else ('Tahan perubahan pada jawaban' if b['move']=='push_in' else 'Perlihatkan pembicara dalam ruangnya' if solo else 'Perlihatkan hubungan kedua tokoh'))))
        for b in p['beats']:
            t = round((offset+b['estimated_frames'][0]-1)/24, 3)
            if b.get('do') == 'silence':
                silences.append(dict(t=t, seconds=b['seconds']))
            if b.get('do') == 'music':
                sections.append(dict(name=f"{genre}_{len(sections)+1}", start_s=t,
                                     end_s=round((offset+p['estimated_frames'][1])/24, 3),
                                     music_state=b['mood'] or 'stop', instrumentation='Sparse keys and a soft sustained layer' if en else 'Tuts jarang dan lapisan nada panjang yang lembut'))
            beats.append(dict(t=t, event=(b.get('say', '')+': '+b.get('text', '')).strip(': ') if 'say' in b else b.get('do', 'title')))
        if offset:
            transitions.append(dict(t=round(offset/24, 3), kind=scene['transition_in']['kind'], audio=scene['transition_in'].get('audio')))
    for a, b in zip(sections, sections[1:]):
        a['end_s'] = min(a['end_s'], b['start_s'])
    spoken = [b['event'] for b in beats if ': ' in b['event']]
    opening, ending = spoken[0], spoken[-1]
    turn = spoken[min(len(spoken)-1, len(spoken)*2//3)]
    candidates = ['A small observation opens a difficult exchange', 'Start with the answer, then return to its cause', 'Follow one shared task until its meaning changes']
    if not en:
        candidates = ['Pengamatan kecil membuka gagasan' if solo else 'Pengamatan kecil membuka percakapan sulit', 'Mulai dari jawaban lalu kembali ke penyebabnya', 'Ikuti satu kegiatan sampai maknanya berubah']
    t = dict(structures=dict(candidates=candidates, chosen=candidates[0], why='The response can change visibly without adding locations or exposition.' if en else 'Perubahan jawaban bisa terlihat tanpa menambah tempat atau penjelasan panjang.'),
        logline=(f"{chars[0]['id']} opens with “{opening.split(': ',1)[-1]}”; the exchange reaches “{ending.split(': ',1)[-1]}”." if en else f"{chars[0]['id']} membuka percakapan dengan “{opening.split(': ',1)[-1]}”; akhirnya muncul jawaban “{ending.split(': ',1)[-1]}”."),
        arc=dict(setup=opening, turn=turn, ending=ending), hook='Open on the first speaker and a concrete observation within three seconds.' if en else 'Buka pada pembicara dan pengamatan konkret dalam tiga detik pertama.',
        ending_echo=('Return to the opening framing after the close response; hold the space for two seconds.' if en else 'Kembali ke framing pembuka setelah jawaban dekat; tahan ruang itu dua detik.'),
        signature_shot='A restrained close-up push at the response after the quiet pause.' if en else 'Push close-up tertahan pada jawaban sesudah jeda hening.', shot_list=shots,
        beat_sheet=beats, cue_map=dict(tempo=(scenes[0]['plan'].get('music') or {}).get('tempo', 80), sections=sections, cuts=[b['t'] for b in beats if b['event']=='camera'],
                                      silences=silences, transitions=transitions),
        sound_design=[dict(section=s['name'], ambience=('Quiet '+(opts.get('location') or 'location')+' bed; dip during the pause') if en else 'Latar lokasi pelan; turun saat jeda',
                           foley='Contact-timed steps and chair movement when present' if en else 'Langkah dan gerak kursi mengikuti kontak bila ada', music=s['music_state']+('; lower under speech' if en else '; turunkan saat dialog')) for s in sections],
        subtitle_design='Classic lower captions, phrase breaks, aim for 1.8 s holds and no more than 17 characters/s. Review actual speech timing.' if en else 'Subtitle klasik di bawah, pisahkan per frasa; target tahan 1.8 detik dan maksimal 17 karakter/detik. Periksa timing suara hasil build.')
    validate_treatment(t)
    return script, t
