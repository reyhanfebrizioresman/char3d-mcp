"""Bilingual editorial cue grammar; pure data, shared by scene and film parsing."""
import re

SIZES = ('extreme_wide', 'wide', 'full', 'medium_full', 'medium', 'medium_close',
         'close_up', 'extreme_close_up')
MOVES = ('static', 'push_in', 'dolly_in', 'dolly_out', 'pull_out', 'orbit_left',
         'orbit_right', 'arc', 'crane_up', 'crane_down', 'truck_left', 'truck_right',
         'pan_left', 'pan_right', 'tilt_up', 'tilt_down', 'zoom_in', 'crash_zoom',
         'dolly_zoom', 'handheld', 'tracking', 'tracking_side', 'drone_reveal')


def token(value):
    return re.sub(r'[\s-]+', '_', value.strip().lower())


def direction(text):
    m = re.fullmatch(r'(?:HENING|SILENCE)\s+(\d+(?:\.\d+)?)(?:\s+(?:detik|seconds?))?', text, re.I)
    if m:
        return {'do': 'silence', 'seconds': float(m[1])}
    m = re.fullmatch(r'(MUSIK|MUSIC|KAMERA|CAMERA)\s*:\s*(.+)', text, re.I)
    if not m:
        return None
    value = m[2].strip()
    if m[1].upper() in ('MUSIK', 'MUSIC'):
        from .music import mood_name
        try:
            mood = None if token(value) in ('berhenti', 'stop') else mood_name(value)
        except ValueError:
            return None
        return {'do': 'music', 'mood': mood}
    if token(value) in ('auto', 'otomatis'):
        return {'do': 'camera', 'shot': 'auto'}
    pieces = [s.strip() for s in value.split(',')]
    first = pieces.pop(0)
    match = re.fullmatch(r'(' + '|'.join(s.replace('_', r'[ -_]') for s in sorted(SIZES, key=len, reverse=True)) +
                         r')(?:\s+(two[ -]shot|dua tokoh))?(?:\s+(.+))?', first, re.I)
    if not match:
        return None
    beat = {'do': 'camera', 'shot': token(match[1]), 'move': 'static'}
    if match[3]:
        beat['subject'] = match[3].strip()
    if pieces:
        move = token(pieces[0])
        if len(pieces) != 1 or move not in MOVES:
            return None
        beat['move'] = move
    return beat


def normalize(beat, ids):
    from .script_plan import _number
    action = beat['do']
    if action == 'silence':
        beat['seconds'] = _number(beat.get('seconds', 1), 'silence seconds', .05, 60)
        return
    if action == 'music':
        from .music import mood_name
        value = beat.get('mood', 'auto')
        beat['mood'] = None if value in ('stop', 'berhenti') else mood_name(value)
        return
    if 'deliberate' in beat and type(beat['deliberate']) is not bool:
        raise ValueError('camera deliberate must be boolean')
    shot = token(beat.get('shot', 'medium'))
    if shot in ('otomatis', 'auto'):
        beat['shot'] = 'auto'
        return
    if shot not in SIZES or token(beat.get('move', 'static')) not in MOVES:
        raise ValueError('camera needs a supported shot size and move')
    beat.update(shot=shot, move=token(beat.get('move', 'static')))
    subjects = beat.get('subject')
    subjects = [subjects] if isinstance(subjects, str) else subjects
    if subjects is not None:
        if not isinstance(subjects, list) or not subjects:
            raise ValueError('camera subject must be a character name or list')
        if any(not isinstance(s, str) or s.casefold() not in ids for s in subjects):
            raise ValueError('camera subject must refer to declared characters')
        beat['subject'] = [ids[s.casefold()] for s in subjects]
    for key, default, low, high in (('angle', 20, -180, 180), ('intensity', .25, 0, 1), ('elevation', 5, -60, 80)):
        beat[key] = _number(beat.get(key, default), key, low, high)
