"""Deterministic emotional coverage planner. No Blender, audio I/O or random state.

Adapters supply evaluated word times, sentence events and measured voice energy.
All automatic cuts use integer frames outside the union of spoken word interiors.
"""
import math
from .emotion import classify, sentences, normalize, NEGATIONS

SIZES = ('extreme_wide', 'wide', 'full', 'medium_full', 'medium',
         'medium_close', 'close_up', 'extreme_close_up')
ALIASES = {'emosi': 'directed', 'emotional': 'directed'}
MOODS = {
    'marah': 'anger', 'angry': 'anger', 'furious': 'anger', 'shout': 'anger',
    'sedih': 'sad', 'cry': 'sad', 'takut': 'fear', 'nervous': 'fear',
    'surprised': 'surprise', 'shock': 'surprise', 'kaget': 'surprise',
    'happy': 'joy', 'smile': 'joy', 'big_smile': 'joy', 'laugh': 'joy', 'senang': 'joy',
    'tender': 'tender', 'haru': 'tender', 'lembut': 'tender', 'love': 'tender',
    'thinking': 'thinking', 'neutral': 'neutral', 'base': 'neutral',
    'excited': 'joy', 'startle': 'surprise', 'sigh': 'sad', 'tired': 'sad',
    'shy': 'fear', 'bored': 'neutral', 'confident': 'thinking',
}
LEVEL = dict(neutral=.20, thinking=.32, tender=.40, sad=.54, joy=.57,
             fear=.76, anger=.82, surprise=.84)
SLOW = {'tender', 'sad'}


def mode(value):
    value = ALIASES.get(str(value).lower(), str(value).lower())
    if value not in ('directed', 'mixed', 'singles', 'two_shot', 'none'):
        raise ValueError('camera must be directed (emosi/emotional), mixed, singles, two_shot or none')
    return value


def mood(value):
    return MOODS.get(str(value).lower(), str(value).lower()) if value else 'neutral'


def camera_overrides(beats, end):
    """Explicit cues own picture coverage until the next cue, including auto."""
    cues = [b for b in beats or [] if b.get('do') == 'camera' and b.get('frames')]
    return [(b['frames'][0], cues[i+1]['frames'][0]-1 if i+1 < len(cues) else end)
            for i,b in enumerate(cues) if b.get('shot') not in ('auto','otomatis')]


def safe_cut(target, low, high, words):
    """Nearest gap on the video frame grid. None means hold.

    Text/voiced-interval timing can have adjoining fractional word boundaries.
    Quantize those boundaries to the nearest frame (<= half a frame error),
    rather than inventing silence or moving the original speech timestamps.
    """
    low, high = math.ceil(low), math.floor(high)
    if high < low:
        return None
    target = max(low, min(high, round(target)))
    # Searching outwards gives a stable earlier-frame tie break, including overlaps.
    for distance in range(max(target-low, high-target)+1):
        for frame in sorted({target-distance, target+distance}):
            if low <= frame <= high and not any(round(a) < frame < round(b) for _, a, b in words):
                return frame
    return None


def emotion_curve(lines, words=None, emotions=None, energy=None, beats=None):
    words, emotions, energy = words or {}, emotions or {}, energy or {}
    events = []
    for index, line in enumerate(lines):
        who, a, b = line['speaker'], line['start'], line['end']
        own = [w for w in words.get(who, []) if w[1] < b+1 and w[2] >= a]
        saved = [e for e in emotions.get(who, [])
                 if (e.get('sentence_frames') or e['frames'])[0] <= b
                 and (e.get('sentence_frames') or e['frames'])[1] >= a]
        if not saved:
            saved = [dict(sentence=' '.join(w[0] for w in group),
                          sentence_frames=[group[0][1], group[-1][2]],
                          emotion=classify(group)[0], strength=classify(group)[1],
                          question=classify(group)[2], source='text') for group in sentences(own)]
        if not saved:
            tokens = [(w, a, b) for w in (line.get('text') or '').split()]
            e, strength, question = classify(tokens)
            saved = [dict(sentence=line.get('text') or '', sentence_frames=[a, b],
                          emotion=e, strength=strength, question=question, source='text')]
        for event in saved:
            start, end = event.get('sentence_frames') or event['frames']
            start, end = max(a, start), min(b, end)
            explicit = line.get('emotion') or line.get('body_emotion')
            emotion = mood(explicit or event.get('emotion'))
            text = event.get('sentence') or line.get('text') or ''
            tokens = {normalize(w) for w in text.split()}
            if (not explicit and emotion in ('joy','neutral')
                    and tokens & {'rindu','hangat','lembut','missed','gently','tenderly'}
                    and not tokens & (NEGATIONS['id'] | NEGATIONS['en'])):
                emotion = 'tender'
            loudness = float(energy.get(who, {}).get(index, 0))
            raw = LEVEL.get(emotion, .35) + .10*float(event.get('strength', 0))
            raw += (.08 if '!' in text else 0) + (.035 if '?' in text else 0) + .08*loudness
            # Use the emotional word, or a sentence-ending question/punchline.
            candidates = [w for w in own if start <= w[2] <= end+.01]
            triggers = [w for w in candidates if mood(classify([w])[0]) == emotion and emotion != 'neutral']
            trigger = (triggers[0] if triggers else candidates[-1] if candidates else ('', start, end))
            events.append(dict(line=index, speaker=who, frames=[round(start, 3), round(end, 3)],
                frame=round((start+end)/2), emotion=emotion, raw_intensity=round(min(1., raw), 4),
                source='line' if explicit else event.get('source', 'text'),
                question=bool(event.get('question') or '?' in text),
                trigger_word=trigger[0], trigger_frame=float(trigger[2]), energy=round(loudness, 4)))
    for beat in beats or []:
        emotion = mood(beat.get('body_emotion') or beat.get('emotion') or beat.get('name'))
        who = beat.get('who')
        if beat.get('do') != 'gesture' or emotion not in LEVEL or not beat.get('frames'):
            continue
        candidates = [i for i,line in enumerate(lines) if line['speaker']==who]
        if not candidates:
            continue
        a,b = beat['frames']
        index = min(candidates, key=lambda i: abs(lines[i]['start']-b))
        events.append(dict(line=index, speaker=who, frames=[a,b], frame=round((a+b)/2),
            emotion=emotion, raw_intensity=LEVEL[emotion], source='body', question=False,
            trigger_word=beat.get('name',''), trigger_frame=b, energy=0.))
    events.sort(key=lambda e: (e['frame'], e['line']))
    for i, event in enumerate(events):
        previous = events[max(0, i-1)]['raw_intensity']
        following = events[min(len(events)-1, i+1)]['raw_intensity']
        event['intensity'] = round(.80*event['raw_intensity']+.10*previous+.10*following, 4)
        delta = event['raw_intensity']-previous
        event['phase'] = 'rise' if delta > .08 else 'release' if delta < -.08 else 'hold'
    if events:
        peak = max(range(len(events)), key=lambda i: (events[i]['intensity'], i))
        events[peak]['phase'] = 'peak'
    return events


def plan_coverage(lines, characters, start, end, fps=24, words=None, emotions=None,
                  energy=None, beats=None, previous_size=None):
    """Plan inclusive, contiguous shots and additive listener reactions.

    Explicit editorial cues are applied by the adapter afterwards and always win.
    Planning never changes audio, word times, cast placement or speech animation.
    """
    lines = sorted(lines, key=lambda line: line['start'])
    words = words or {}
    all_words = sorted([w for group in words.values() for w in group], key=lambda w: w[1])
    curve = emotion_curve(lines, words, emotions, energy, beats)
    minimum = max(2, math.ceil(fps))
    warnings, shots, reactions = [], [], []
    events_by_line = {i: [e for e in curve if e['line'] == i] for i in range(len(lines))}

    def event_at(frame):
        return min(curve, key=lambda e: abs(e['frame']-frame)) if curve else dict(emotion='neutral', intensity=.2, phase='hold')

    def add(a, b, who, role, event, size=None, partner=None, detail=None):
        if b < a:
            return
        value, emotion = event['intensity'], event['emotion']
        size = size or ('close_up' if value >= .76 else 'medium_close' if value >= .48 else 'medium')
        if role == 'OTS':
            size = 'medium_close'
        move = 'static'
        if role in ('peak', 'reaction') or emotion == 'tender':
            move = 'push_in'
        if role == 'release':
            move = 'pull_out'
        shock = (role == 'peak' and emotion == 'surprise' and event.get('source') == 'cue'
                 and event.get('raw_intensity', 0) >= .93
                 and not any(s['move']=='crash_zoom' for s in shots))
        if shock:
            size, move = 'extreme_close_up', 'crash_zoom'
        # Same-subject cuts need two sizes of change. Do this before baking;
        # live face-relative cameras should never be rotated away just for variety.
        if shots and shots[-1]['subject'] == who:
            if shots[-1]['reason']['role'] == 'reaction' and role in ('speaker','OTS','peak'):
                # The listener often answers next. Hold the readable reaction
                # camera into their reply instead of widening into a dirty single.
                shots[-1]['frames'][1] = int(b)
                shots[-1]['reason']['detail'] = 'listener response held into their speaking turn'
                return
            prev = SIZES.index(shots[-1]['size'])
            if abs(SIZES.index(size)-prev) < 2:
                choices = [j for j in range(2, 7) if abs(j-prev) >= 2]
                size = SIZES[min(choices, key=lambda j: (abs(j-SIZES.index(size)), j))]
                if role == 'OTS':
                    role = 'speaker'
        reason = dict(role=role, emotion=emotion, intensity=value, phase=event.get('phase', 'hold'),
                      detail=detail or ('listener response over continuing speaker audio' if role == 'reaction' else 'emotional coverage'))
        shots.append(dict(frames=[int(a), int(b)], subject=who, size=size, move=move,
                          partner=partner, reason=reason,
                          handheld=.045 if emotion in ('anger','fear') and role == 'peak' else 0.,
                          intensity=.08 if shock else .12 if move == 'pull_out' else .28))

    singles = 0
    for index, line in enumerate(lines):
        lo = start if index == 0 else safe_cut(line['start']-4, max(start+minimum, shots[-1]['frames'][0]+minimum), line['start'], all_words)
        if lo is None:
            warnings.append(f"Line {index+1}: no safe word gap; previous shot held")
            continue
        hi = end if index == len(lines)-1 else safe_cut(lines[index+1]['start']-4, line['end']+1, lines[index+1]['start'], all_words)
        hi = (hi-1) if hi is not None and index < len(lines)-1 else end
        if hi-lo+1 < minimum:
            if shots:
                shots[-1]['frames'][1] = hi
            continue
        if shots:
            shots[-1]['frames'][1] = lo-1
        own = events_by_line[index]
        event = max(own, key=lambda e: e['intensity'], default=event_at(lo))
        who = line['speaker']
        partner = next((l['speaker'] for l in reversed(lines[:index]) if l['speaker'] != who),
                       next((n for n in characters if n != who), None))
        duration = (hi-lo+1)/fps
        # Opening and re-establishing group coverage is motivated by geography.
        opening = index == 0
        geography = any(b.get('do') in ('walk','sit','stand','enter','interact')
                        and shots and shots[-1]['frames'][0] < b.get('frames', [0])[0] <= line['start']
                        for b in beats or [])
        group = opening or singles >= 3 or geography
        cursor = lo
        if group and duration >= 3.4:
            boundary = safe_cut(lo+(2.1 if opening else 1.4)*fps, lo+minimum, hi-minimum+1, all_words)
            if boundary is not None:
                opening_size = 'full' if previous_size in ('close_up','extreme_close_up') else 'medium_full'
                add(lo, boundary-1, None, 'establish', event, size=opening_size,
                    detail='opening geography' if opening else 're-establish after singles or movement')
                cursor = boundary
                singles = 0
        elif group:
            add(lo, hi, None, 'establish', event, size='medium_full')
            singles = 0
            continue

        # Select one motivated listener insert per line, at a safe gap >=1s after
        # onset, with the reaction starting .3s after a real trigger word ends.
        reaction = None
        motivated = duration > 4 or event['question'] or event['intensity'] >= .60
        if event['emotion'] in SLOW:
            motivated = motivated and (index % 3 == 1 or event.get('phase') in ('peak','release'))
        if partner and motivated:
            candidates = sorted(own, key=lambda e: (-e['intensity'], e['frame']))
            for trigger in candidates:
                onset = round(trigger['trigger_frame']+.3*fps)
                # If the trigger ends too late, use an earlier emotional sentence.
                cut = safe_cut(onset, max(cursor+minimum, line['start']+minimum, onset-round(.2*fps)),
                               min(hi-minimum+1, onset+round(.3*fps)), all_words)
                if cut is not None and onset <= hi-.35*fps:
                    reaction = (cut, trigger, onset)
                    break
            # Long neutral lines use an internal word at the end of a phrase.
            if reaction is None and duration > 4:
                inner = [w for w in words.get(who, []) if max(cursor+minimum,line['start']+minimum) <= w[2] <= hi-1.4*fps]
                if inner:
                    trigger_word = min(inner, key=lambda w: abs(w[2]-(lo+hi)*.5))
                    onset = round(trigger_word[2]+.3*fps)
                    cut = safe_cut(onset, max(cursor+minimum,line['start']+minimum,onset-round(.2*fps)),
                                   min(hi-minimum+1,onset+round(.3*fps)), all_words)
                    if cut is not None:
                        trigger = dict(event, trigger_word=trigger_word[0], trigger_frame=trigger_word[2])
                        reaction = (cut, trigger, onset)

        intervals = []
        if reaction:
            cut, trigger, onset = reaction
            hold = (1.35 if event['emotion'] in ('anger','fear','surprise') else 2.15)*fps
            back = safe_cut(cut+hold, cut+minimum, hi-minimum+1, all_words)
            stop = back-1 if back is not None else hi
            intervals = [(cursor, cut-1, False), (cut, stop, True)]
            if back is not None:
                intervals.append((back, hi, False))
            expression = {'anger':'angry','fear':'fear','sad':'sad','surprise':'surprised',
                          'joy':'smile','tender':'smile'}.get(trigger['emotion'], 'thinking')
            peak = max(cut, onset)+round(.2*fps)
            reactions.append(dict(character=partner, speaker=who, expression=expression,
                strength=.55, onset=onset, peak=min(stop, peak), end=stop,
                trigger_word=trigger['trigger_word'], trigger_frame=trigger['trigger_frame'], cut=cut))
        else:
            intervals = [(cursor, hi, False)]
        for a, b, is_reaction in intervals:
            if is_reaction:
                add(a, b, partner, 'reaction', trigger, partner=who,
                    size='close_up' if trigger['intensity'] >= .76 else 'medium_close')
                singles += 1
                continue
            # Longer tender/sad holds and quicker arguments, with deterministic
            # duration variation. A >30s scene reserves one >=5s breath.
            target = (5.8 if event['emotion'] in SLOW else 2.65 if event['emotion'] in ('anger','fear') else 4.4)
            target *= (1., 1.17, .91)[index % 3]
            while b-a+1 > min(7.5, target+1.1)*fps:
                boundary = safe_cut(a+target*fps, a+minimum, b-minimum+1, all_words)
                if boundary is None:
                    break
                role = 'peak' if event.get('phase') == 'peak' else 'speaker'
                add(a, boundary-1, who, role, event, partner=partner)
                singles += 1
                a = boundary
            role = 'peak' if event.get('phase') == 'peak' else 'OTS' if partner and index % 2 == 0 else 'speaker'
            add(a, b, who, role, event, partner=partner)
            singles += 1
    if not shots:
        add(start, end, None, 'establish', event_at(start), size='medium_full')
    # Physical entrances, routes and seat changes need their geography on screen
    # while they happen. Expand into adjacent fragments shorter than the minimum.
    for beat in beats or []:
        if beat.get('do') not in ('walk','sit','stand','enter') or not beat.get('frames'):
            continue
        a,b = beat['frames']
        a,b = max(start,a), min(end,max(b,a+minimum-1))
        if b-a+1 < minimum:
            a = max(start,b-minimum+1)
        first = next((i for i,s in enumerate(shots) if s['frames'][1]>=a), None)
        last = next((i for i,s in reversed(list(enumerate(shots))) if s['frames'][0]<=b), None)
        if first is None or last is None:
            continue
        if a-shots[first]['frames'][0] < minimum:
            a = shots[first]['frames'][0]
        if shots[last]['frames'][1]-b < minimum:
            b = shots[last]['frames'][1]
        before = [dict(s, frames=[s['frames'][0],min(a-1,s['frames'][1])]) for s in shots if s['frames'][0]<a]
        after = [dict(s, frames=[max(b+1,s['frames'][0]),s['frames'][1]]) for s in shots if s['frames'][1]>b]
        shots = []
        add(a,b,None,'establish',event_at(a),size='full',detail='geography during '+beat['do'])
        if b-a+1>5*fps:
            shots[0]['move']='push_in'
        shots = before+shots+after
    # Echo the opening at the end, but only where both intervals remain readable.
    last = shots[-1]
    if len(shots) > 1 and last['frames'][1]-last['frames'][0]+1 >= 2.8*fps:
        cut = safe_cut(end-1.5*fps, last['frames'][0]+minimum, end-minimum+1, all_words)
        if cut is not None and (not lines or cut >= lines[-1]['start']+minimum):
            last['frames'][1] = cut-1
            add(cut, end, None, 'release', event_at(end), size='medium_full', detail='ending echoes opening')
    if len(shots) > 1 and shots[-1]['reason']['role'] not in ('reaction','release'):
        # A short final speaking fragment can itself become the closing group
        # view; no extra cut or sub-second sliver is needed.
        last = shots[-1]
        last.update(subject=None, size='medium_full', move='pull_out', intensity=.12)
        last['reason'] = dict(last['reason'], role='release', detail='ending echoes opening')
    if end-start+1 > 30*fps and not any(s['frames'][1]-s['frames'][0]+1 >= 5*fps for s in shots):
        # Merge a contiguous run into a moving group breath, preserving all cuts
        # before/after it and never altering a spoken word's timing.
        for i in range(1, len(shots)):
            j = i
            while j < len(shots) and shots[j]['frames'][1]-shots[i]['frames'][0]+1 < 5*fps:
                j += 1
            if j < len(shots):
                a, b = shots[i]['frames'][0], shots[j]['frames'][1]
                del shots[i:j+1]
                previous = shots
                shots = []
                add(a, b, None, 'establish', event_at(a), size='medium_full', detail='held breath')
                shots[0]['move'] = 'push_in'
                shots = previous[:i]+shots+previous[i:]
                break
    # A breath can adjoin an earlier establishing shot. Merge that continuous
    # group view instead of manufacturing a same-size jump cut.
    merged = []
    for item in shots:
        if merged and item['subject'] is None and merged[-1]['subject'] is None:
            merged[-1]['frames'][1] = item['frames'][1]
            merged[-1]['move'] = 'push_in'
        else:
            merged.append(item)
    shots = merged
    # Reactions hidden by the held breath are removed, not reported as visible.
    overrides = camera_overrides(beats, end)
    reactions = [r for r in reactions if not any(a <= r['peak'] <= b for a,b in overrides)
                 and any(s['reason']['role']=='reaction' and s['subject']==r['character']
                         and s['frames'][0] <= r['peak'] <= s['frames'][1] for s in shots)]
    return dict(shots=shots, emotion_curve=curve, reactions=reactions, warnings=warnings)
