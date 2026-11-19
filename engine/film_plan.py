"""Film grammar and frame arithmetic. Pure Python; no files, audio or Blender."""
import copy
import hashlib
import json
import re

SCENE = re.compile(r'^(?:ADEGAN|SCENE)\s*(?:\d+\s*)?:\s*(.*)$', re.I)
HEADER = re.compile(r'^(JUDUL|TITLE|LOKASI|LOCATION|SUASANA|LOOK|MOOD|CUACA|WEATHER|LIGHTING|PENCAHAYAAN|KARTU|CARD|GAYA|STYLE)\s*:\s*(.*)$', re.I)
FIELDS = {'gaya': 'style', 'style': 'style', 'judul': 'title', 'title': 'title', 'lokasi': 'environment', 'location': 'environment',
          'suasana': 'look', 'look': 'look', 'mood': 'look', 'cuaca': 'weather', 'weather': 'weather',
          'lighting': 'lighting', 'pencahayaan': 'lighting', 'kartu': 'card', 'card': 'card'}
CHANGE = re.compile(r'(.+?)\s+(?:berganti\s+(?:baju|pakaian)|changes?\s+into)\s+(.+)', re.I)


def is_film(script):
    return isinstance(script, dict) and 'scenes' in script or isinstance(script, str) and any(SCENE.match(s.strip()) for s in script.splitlines())


def transition(value=None):
    from .script_plan import _number
    if value is None:
        return {'kind': 'cut', 'duration_s': 0.0}
    if isinstance(value, str):
        m = re.fullmatch(r'([\w-]+)(?:\s+(\d+(?:\.\d+)?)(?:\s*(?:detik|seconds?|s))?)?', value.strip(), re.I)
        if not m:
            raise ValueError(f'Invalid transition: {value}')
        value = {'kind': m[1], 'duration_s': float(m[2]) if m[2] else .5}
    if not isinstance(value, dict):
        raise ValueError('transition_in must be a kind or dict')
    kind = str(value.get('kind', 'cut')).lower()
    kind = {'dissolve': 'crossfade', 'dip_black': 'fade_black'}.get(kind, kind)
    if kind not in ('cut', 'crossfade', 'fade_black', 'fade_white'):
        raise ValueError('transition must be cut/dissolve/crossfade/fade_black/dip_black/fade_white')
    seconds = _number(value.get('duration_s', .5), 'transition duration_s', .05, 10) if kind != 'cut' else 0.0
    return {'kind': kind, 'duration_s': seconds}


def _text(script):
    from .script_plan import _descriptors, _direction
    raw = {'characters': [], 'scenes': []}
    chars, pending, preamble, warnings = {}, None, [], []
    current = None
    for n, line in enumerate(script.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        match = SCENE.match(line)
        if match:
            current = {'name': match[1] or f'Adegan {len(raw["scenes"])+1}', 'beats': list(preamble),
                       'transition_in': pending}
            preamble.clear()
            raw['scenes'].append(current)
            pending = None
            continue
        header = HEADER.match(line)
        if header:
            key = FIELDS[header[1].lower()]
            (raw if key == 'title' or current is None else current)[key] = header[2]
            continue
        beats = current['beats'] if current is not None else preamble
        if line.startswith('[') and line.endswith(']'):
            text = line[1:-1].strip()
            t = re.fullmatch(r'(?:TRANSISI|TRANSITION)\s*:\s*(.+)', text, re.I)
            change = CHANGE.fullmatch(text)
            if t:
                pending = transition(t[1])
            elif change:
                beats.append({'do': 'outfit', 'who': change[1], 'outfit': change[2]})
            else:
                beat = _direction(text, warnings)
                if beat:
                    beats.append(beat)
            continue
        match = re.fullmatch(r'([^:()]+?)(?:\s*\(([^)]*)\))?\s*(?::\s*(.*))?', line)
        if not match or not (match[2] or match[3]):
            warnings.append(f'Line {n}: unrecognized text: {line}')
            continue
        ident, desc, text = match.groups()
        ident = ident.strip()
        if ident.casefold() not in chars:
            chars[ident.casefold()] = {'id': ident}
            raw['characters'].append(chars[ident.casefold()])
            if desc:
                _descriptors(desc, chars[ident.casefold()], warnings)
        elif desc:
            warnings.append(f'{ident}: repeated declaration ignored; use an explicit outfit change')
        if text:
            beats.append({'say': chars[ident.casefold()]['id'], 'text': text})
    if pending:
        raise ValueError('Transition must be followed by a scene header')
    return raw, warnings


def layout(scenes, fps=24, estimated=False):
    """Inclusive scene ranges. Dissolves overlap; dips keep a cut and fade around it.

    Cards insert solid frames before the scene. Incoming transitions lead into the card.
    Reject overlapping transitions rather than silently shortening user durations.
    """
    cursor, previous, windows = 1, None, []
    for i, scene in enumerate(scenes):
        count = (scene.get('estimated_frames') if estimated else scene.get('frames')) or scene['plan']['estimated_frames']
        count = count[1] - count[0] + 1
        card_frames = round(scene['card']['duration_s'] * fps) if scene.get('card') else 0
        t = scene['transition_in']
        minimum = 3 if t['kind'] in ('fade_black', 'fade_white') else 2
        n = max(minimum, round(t['duration_s'] * fps)) if t['kind'] != 'cut' and i else 0
        overlap = n if t['kind'] == 'crossfade' else 0
        start = cursor - overlap
        end = start + card_frames + count - 1
        if n:
            if previous is None or n > min(previous['segment_frames'], card_frames + count):
                raise ValueError('Transition duration exceeds adjacent scene/card duration')
            a = start if overlap else start - n // 2
            b = a + n - 1
            if any(a <= d and b >= c for c, d in windows):
                raise ValueError('Film transitions must not overlap')
            windows.append((a, b))
        scene.update(segment_start=start, segment_frames=card_frames + count,
                     card_frames=card_frames, film_frames=[start + card_frames, end],
                     audio_offset_frames=start + card_frames - 1,
                     subtitle_offset_frames=start + card_frames - 1,
                     transition_frames=n, overlap_frames=overlap)
        previous, cursor = scene, end + 1
    return [1, cursor - 1]


def parse_film(script, name=None, environment=None, seed=0, fps=24, look=None, lighting='studio', style=None):
    from .script_plan import parse_script, _descriptors, _number
    warnings = []
    if not is_film(script):
        p = parse_script(script, name=name, environment=environment, seed=seed, fps=fps, look=look, style=style)
        raw = {'title': p['title'], 'characters': p['characters'], 'scenes': [{'name': p['name'], **p}]}
    elif isinstance(script, str):
        raw, warnings = _text(script)
    else:
        raw = copy.deepcopy(script)
    if not isinstance(raw.get('scenes'), list) or not 1 <= len(raw['scenes']) <= 64:
        raise ValueError('Film needs 1–64 scenes')
    # Normalize defaults ONCE in global declaration order, before selecting scene casts.
    base = parse_script({'characters': raw.get('characters', []), 'beats': [{'do': 'pause', 'seconds': 1}]}, seed=seed, fps=fps)
    chars = {c['id']: c for c in base['characters']}
    ids = {c.casefold(): c for c in chars}
    warnings.extend(base['warnings'])
    scenes = []
    for i, source in enumerate(raw['scenes']):
        if not isinstance(source, dict) or not isinstance(source.get('beats', []), list):
            raise ValueError('Each scene needs a beats list')
        beats, used = [], set()
        for beat in source.get('beats', []):
            if not isinstance(beat, dict):
                raise ValueError('Each beat must be a dict')
            if beat.get('do') in ('outfit', 'change_outfit'):
                if beats:
                    raise ValueError('Put outfit changes before scene dialogue/actions; costume changes apply at scene boundaries')
                ident = ids.get(str(beat.get('who', '')).casefold())
                if ident is None:
                    raise ValueError('Outfit change needs a declared character')
                change = {'id': ident}
                _descriptors(str(beat.get('outfit', '')), change, warnings)
                if not change.get('outfit') and 'clothes' not in change and 'assets' not in change:
                    raise ValueError('Outfit change needs a supported outfit or catalog clothes')
                for key in ('clothes', 'outfit', 'assets'):
                    chars[ident].pop(key, None)
                chars[ident].update({k: v for k, v in change.items() if k in ('clothes', 'outfit', 'assets')})
                used.add(ident)
                continue
            beats.append(copy.deepcopy(beat))
            for key in ('say', 'who', 'with', 'at', 'to'):
                if isinstance(beat.get(key), str):
                    value = ids.get(beat[key].casefold())
                    if value:
                        used.add(value)
                    elif beat[key].casefold() in ('they', 'mereka'):
                        used.update(chars)
        for ident in source.get('cast', []):
            if str(ident).casefold() not in ids:
                raise ValueError(f'Unknown cast member: {ident}')
            used.add(ids[ident.casefold()])
        if not used:
            used.update(chars)  # silent establishing scene
        scene_chars = [copy.deepcopy(c) for ident, c in chars.items() if ident in used]
        scene_raw = {k: copy.deepcopy(source.get(k, raw.get(k))) for k in ('environment', 'look', 'weather', 'style')
                     if source.get(k, raw.get(k)) is not None}
        p = parse_script({**scene_raw, 'characters': scene_chars, 'beats': beats},
                         name=source.get('name') or f'Adegan {i+1}', environment=environment,
                         seed=seed, fps=fps, look=look, style=style)
        card = source.get('card')
        if card is not None:
            card = {'text': card, 'duration_s': 2} if isinstance(card, str) else copy.deepcopy(card)
            if not isinstance(card, dict) or not isinstance(card.get('text'), str) or not card['text'].strip():
                raise ValueError('card needs nonempty text')
            card['duration_s'] = _number(card.get('duration_s', 2), 'card duration_s', .1, 60)
        scene = {**{k: p.get(k) for k in ('name', 'environment', 'look', 'weather', 'estimated_frames')},
                 'index': i+1, 'lighting': source.get('lighting', raw.get('lighting', lighting)),
                 'card': card, 'transition_in': transition(source.get('transition_in')) if i else transition(),
                 'cast': [c['id'] for c in scene_chars], 'plan': p,
                 'character_seeds': {c['id']: seed + j*101 for j, c in enumerate(base['characters']) if c['id'] in used}}
        scene['source_hash'] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()
        scenes.append(scene)
        warnings.extend(p['warnings'])
    frames = layout(scenes, fps, estimated=True)
    result = dict(version=1, kind='film', name=name or raw.get('title') or 'Film', title=raw.get('title'),
                characters=base['characters'], scenes=scenes, seed=seed, fps=fps, estimated_frames=frames,
                duration_s=round(frames[1]/fps, 3), warnings=list(dict.fromkeys(warnings)))
    return json.loads(json.dumps(result))


def content_hash(path, settings):
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(',', ':')).encode())
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def offset_captions(chunks, offset):
    return [dict(c, start=c['start']+offset, end=c['end']+offset,
                 **({'words': [(text, a+offset, b+offset) for text, a, b in c['words']]}
                    if 'words' in c else {})) for c in chunks]
