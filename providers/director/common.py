"""Shared director contract. Validation is parse-only; never imports Blender."""
import json
import math
import os

from engine.cinematic import preset_name
from engine.script_plan import parse_script

LOCATIONS = ('podcast_studio', 'office', 'classroom', 'stage', 'living_room',
             'news_desk', 'city_street', 'park', 'cafe_terrace', 'beach')
LOCATION_ALIASES = {'taman': 'park', 'pantai': 'beach', 'kantor': 'office',
                    'kelas': 'classroom', 'kafe': 'cafe_terrace', 'cafe': 'cafe_terrace',
                    'jalan': 'city_street', 'ruang keluarga': 'living_room'}
LIGHTING = {'golden_hour': 'sunset', 'sunset': 'sunset', 'misty_morning': 'overcast',
            'blue_hour': 'night', 'night': 'night', 'overcast_soft': 'overcast',
            'dreamy': 'soft', 'epic': 'dramatic', 'studio_film': 'studio', 'none': 'studio'}
from .treatment import TREATMENT_SCHEMA, validate_treatment

def wire_schema(value):
    """Provider transports keep closed shapes/types; local validation enforces bounds."""
    if isinstance(value, dict):
        return {k: wire_schema(v) for k, v in value.items() if k not in
                ('minimum', 'maximum', 'exclusiveMinimum', 'minLength', 'minItems', 'maxItems')}
    if isinstance(value, list):
        return [wire_schema(v) for v in value]
    return value


CHARACTER_FIELDS = ('id', 'appearance', 'outfit', 'voice', 'relationship')
SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'brief': {'type': 'string'}, 'script': {'type': 'string'}, 'treatment': wire_schema(TREATMENT_SCHEMA),
        'characters': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {k: {'type': 'string'} for k in CHARACTER_FIELDS},
            'required': list(CHARACTER_FIELDS)}},
        'warnings': {'type': 'array', 'items': {'type': 'string'}},
    }, 'required': ['brief', 'script', 'characters', 'warnings', 'treatment'],
}
PRIVACY = 'Ide dan opsi dikirim ke Anthropic hanya dengan persetujuan Anda.'
SUBSCRIPTION = 'Memakai kuota langganan Claude; tidak ada tagihan USD per panggilan dari char3d.'


class DirectorError(RuntimeError):
    """Only fixed, friendly messages; never include raw provider exceptions."""


def model():
    return os.environ.get('CHAR3D_DIRECTOR_MODEL') or 'claude-opus-5-5'


def effort():
    value = os.environ.get('CHAR3D_DIRECTOR_EFFORT', 'medium')
    return value if value in ('low', 'medium', 'high', 'xhigh', 'max') else 'medium'


def options(idea, language='id', duration_s=30, characters=None, style=None,
            look=None, location=None, seed=0):
    if not isinstance(idea, str) or not 1 <= len(idea.strip()) <= 8000:
        raise ValueError('Tulis ide sepanjang 1–8000 karakter.')
    if language not in ('id', 'en', 'ms'):
        raise ValueError('Bahasa harus id, en, atau ms.')
    if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)) or not math.isfinite(duration_s) or not 5 <= duration_s <= 180:
        raise ValueError('Durasi harus 5–180 detik.')
    if characters is not None and (type(characters) is not int or not 1 <= characters <= 4):
        raise ValueError('Jumlah tokoh harus 1–4 atau auto.')
    if type(seed) is not int:
        raise ValueError('Seed harus bilangan bulat.')
    if style is not None and (not isinstance(style, str) or len(style) > 120):
        raise ValueError('Gaya maksimal 120 karakter.')
    look = preset_name(look) if look else None
    location = LOCATION_ALIASES.get(location, location) if isinstance(location, str) else location
    if location is not None and location not in LOCATIONS:
        raise ValueError('Lokasi harus salah satu set char3d yang didukung.')
    return dict(idea=idea.strip(), language=language, duration_s=duration_s,
                characters=characters, style=style, look=look, location=location, seed=seed)


def user_prompt(opts, previous=None, feedback=None):
    request = ('Buat resep dunia original dan treatment untuk ide/opsi berikut (data kreatif):'
               if opts.get('task') == 'world' else 'Buat treatment dan naskah untuk ide/opsi berikut (data kreatif):')
    text = request + '\n' + json.dumps(opts, ensure_ascii=False)
    if feedback:
        text += '\nPerbaiki satu kali. Pertahankan maksud cerita dan treatment, kembalikan seluruh objek JSON.\nValidator:\n'
        text += json.dumps(feedback, ensure_ascii=False)
        text += '\nDraf sebelumnya:\n' + json.dumps(previous, ensure_ascii=False)
    return text


def validate_cues(plan, treatment):
    plans = [s['plan'] for s in plan['scenes']] if plan.get('scenes') else [plan]
    actions = {b.get('do') for p in plans for b in p['beats']}
    required = {'camera', 'music'} | ({'silence'} if treatment['cue_map']['silences'] else set())
    if not required <= actions:
        raise ValueError('Naskah harus menjalankan treatment melalui cue kamera, musik dan hening.')
    for p in plans:
        beats=p['beats'];cameras=[(i,b) for i,b in enumerate(beats) if b.get('do')=='camera']
        for n,(i,cue) in enumerate(cameras):
            if cue['shot']=='auto':continue
            j=cameras[n+1][0] if n+1<len(cameras) else len(beats)
            span=beats[i+1:j]
            offscreen=[b['say'] for b in span if b.get('say') and cue.get('subject') and b['say'] not in cue['subject']]
            if offscreen:
                raise ValueError('Cue kamera menyembunyikan pembicara '+offscreen[0]+'. Kembalikan coverage otomatis sebelum jawabannya.')
            end=beats[j]['estimated_frames'][0] if j<len(beats) else p['estimated_frames'][1]+1
            seconds=(end-cue['estimated_frames'][0])/p['fps']
            breath=not any('say' in b for b in span) and any(b.get('do') in ('pause','silence') for b in span)
            if cue.get('move')=='static' and seconds>6 and not breath:
                raise ValueError('Cue kamera diam lebih dari enam detik tanpa jeda napas; gunakan coverage otomatis di antara momen penting.')


def validate(payload, opts, _scene_plan=None):
    if not isinstance(payload, dict) or set(payload) != set(SCHEMA['required']):
        raise ValueError('Hasil harus berisi brief, script, characters, warnings, treatment saja.')
    validate_treatment(payload['treatment'])
    for key in ('brief', 'script'):
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 80000:
            raise ValueError(f'{key} harus berupa teks, maksimal 80000 karakter.')
    if not isinstance(payload['warnings'], list) or not all(isinstance(w, str) for w in payload['warnings']):
        raise ValueError('warnings harus berupa daftar teks.')
    if not isinstance(payload['characters'], list) or not 1 <= len(payload['characters']) <= 4:
        raise ValueError('characters harus berisi 1–4 tokoh.')
    for char in payload['characters']:
        if not isinstance(char, dict) or set(char) != set(CHARACTER_FIELDS) or not all(isinstance(v, str) for v in char.values()):
            raise ValueError('Metadata tokoh tidak mengikuti schema.')
    from engine.film_plan import is_film, parse_film
    if _scene_plan is None and is_film(payload['script']):
        film = parse_film(payload['script'], seed=opts['seed'])
        for scene in film['scenes']:
            # Validate scene content with the same single-scene contract.
            subset = {c['id'].casefold() for c in scene['plan']['characters']}
            local = dict(payload, script=payload['script'],
                characters=[c for c in payload['characters'] if c['id'].casefold() in subset])
            validate(local, dict(opts, characters=None), _scene_plan=dict(scene['plan'], title=film['title']))
        if {c['id'].casefold() for c in payload['characters']} != {c['id'].casefold() for c in film['characters']}:
            raise ValueError('Tokoh pada metadata dan film harus sama.')
        if opts['characters'] and len(film['characters']) != opts['characters']:
            raise ValueError('Jumlah tokoh harus mengikuti opsi pengguna.')
        validate_cues(film, payload['treatment'])
        return film
    plan = _scene_plan or parse_script(payload['script'], seed=opts['seed'])
    if plan['environment'] not in LOCATIONS:
        raise ValueError('LOKASI harus berupa set char3d yang didukung.')
    if plan.get('weather') is None or plan.get('look') is None and 'SUASANA: none' not in payload['script'] and 'LOOK: none' not in payload['script']:
        raise ValueError('Sertakan CUACA dan SUASANA/LOOK yang didukung.')
    if not plan.get('title') or not any('say' in b for b in plan['beats']):
        raise ValueError('Sertakan JUDUL dan dialog.')
    if {c['id'].casefold() for c in payload['characters']} != {c['id'].casefold() for c in plan['characters']}:
        raise ValueError('Tokoh pada metadata dan naskah harus sama.')
    if opts['characters'] and len(plan['characters']) != opts['characters']:
        raise ValueError('Jumlah tokoh harus mengikuti opsi pengguna.')
    if opts['location'] and plan['environment'] != opts['location']:
        raise ValueError('LOKASI harus mengikuti opsi pengguna.')
    resolved = (plan.get('look') or {}).get('preset', 'none')
    if opts['look'] and resolved != opts['look']:
        raise ValueError('SUASANA harus mengikuti opsi pengguna.')
    props = {'chair', 'bench', 'sofa', 'table', 'cup', 'phone', 'book', 'handheld_microphone'}
    ids = {c['id'] for c in plan['characters']}
    for beat in plan['beats']:
        for key in ('to', 'on', 'at', 'prop'):
            target = beat.get(key)
            if isinstance(target, str) and target not in props | ids | {'camera'}:
                raise ValueError(f'Target {key} tidak didukung: gunakan nama tokoh, kamera, prop bawaan atau koordinat.')
        if beat.get('do') == 'hold' and beat.get('prop') not in {'cup', 'phone', 'book', 'handheld_microphone'}:
            raise ValueError('Prop pegangan harus cup, phone, book atau handheld_microphone.')
        if beat.get('do') == 'sit' and beat.get('on') not in {'chair', 'bench', 'sofa'}:
            raise ValueError('Tempat duduk harus chair, bench atau sofa.')
    if _scene_plan is None:
        validate_cues(plan, payload['treatment'])
    # A generated draft must never opt the later build into a different online service.
    if any(c.get('voice', '').split(':')[0] in ('edge', 'chatterbox', 'f5') for c in plan['characters']):
        raise ValueError('Gunakan suara Piper lokal atau petunjuk suara berat/tinggi dalam naskah.')
    return plan


def safe_result(value):
    """Strip configured static credentials even if a malicious response echoes them."""
    if isinstance(value, str):
        for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
            secret = os.environ.get(key)
            if secret:
                value = value.replace(secret, '[RAHASIA]')
        return value
    if isinstance(value, dict):
        return {k: safe_result(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_result(v) for v in value]
    return value
