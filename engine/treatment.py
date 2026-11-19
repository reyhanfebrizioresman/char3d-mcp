"""Shared structured directing contract and Markdown rendering. No Blender or IO."""
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


def markdown(t, language='en'):
    from .director_cues import display_size, display_move
    lines = ['## Treatment', '', '**Logline:** '+t['logline'], '', '**Structure choices:**']
    lines += ['- '+v for v in t['structures']['candidates']]
    lines += ['', '**Chosen:** '+t['structures']['chosen']+'. '+t['structures']['why'], '']
    lines += [f'**{k.title()}:** {v}' for k, v in t['arc'].items()]
    lines += ['', '**Opening three seconds:** '+t['hook'], '**Opening returned:** '+t['ending_echo'],
              '**Peak shot:** '+t['signature_shot'], '', '| Beat | Size / move / angle | Seconds | Purpose |',
              '| --- | --- | --- | --- |']
    lines += [f"| {s['beat']} | {display_size(s['size'])} / {display_move(s['move'],language)} / {s['angle']:g}° | {s['seconds']:g} | {s['reason']} |" for s in t['shot_list']]
    lines += ['', '### Beat timing', ''] + [f"- {b['t']:g}s: {b['event']}" for b in t['beat_sheet']]
    lines += ['', f"### Sound and cut grid · {t['cue_map']['tempo']:g} BPM", '',
              '| Section | Time | Music | Instruments |', '| --- | --- | --- | --- |']
    lines += [f"| {s['name']} | {s['start_s']:g}–{s['end_s']:g}s | {s['music_state']} | {s['instrumentation']} |" for s in t['cue_map']['sections']]
    lines += ['', 'Cuts (seconds): '+', '.join(str(x) for x in t['cue_map']['cuts'])]
    lines += [(f"- Silence: {s['t']:g}s for {s['seconds']:g}s; keep movement sounds." if language=='en' else
               f"- Hening: {s['t']:g} detik selama {s['seconds']:g} detik; pertahankan bunyi gerak.") for s in t['cue_map']['silences']]
    lines += [f"- Transition at {s['t']:g}s: {s['kind']}, audio {s['audio'] or 'picture-aligned'}." for s in t['cue_map']['transitions']]
    lines += ['', '| Section | Ambience | Foley | Music |', '| --- | --- | --- | --- |']
    lines += [f"| {s['section']} | {s['ambience']} | {s['foley']} | {s['music']} |" for s in t['sound_design']]
    result = '\n'.join(lines+['', '**Captions:** '+t['subtitle_design']])
    if language != 'en':
        for a,b in {'Structure choices':'Pilihan struktur','Chosen':'Pilihan','Setup':'Awal','Turn':'Perubahan','Ending':'Akhir',
                    'Opening three seconds':'Tiga detik pembuka','Opening returned':'Gema pembuka','Peak shot':'Shot puncak',
                    'Beat timing':'Urutan tindakan','Sound and cut grid':'Peta musik dan potongan','Section':'Bagian',
                    'Time':'Waktu','Music':'Musik','Instruments':'Instrumen','Size / move / angle':'Ukuran / gerak / sudut',
                    'Seconds':'Detik','Purpose':'Alasan','Cuts (seconds)':'Potongan (detik)','Captions':'Subtitle',
                    'Ambience':'Latar suara','Silence:':'Hening:','keep movement sounds.':'pertahankan bunyi gerak.'}.items():
            result = result.replace(a,b)
    return result
