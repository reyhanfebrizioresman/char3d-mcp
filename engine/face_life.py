"""Deterministic, Blender-free face performance score. Values are additive deltas.

No articulation channels are generated while speaking. Smooth phrase pulses and
held eye offsets avoid frame-wise random noise; seed never changes global RNG.
"""
import math
import random


def intensity(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 2:
        raise ValueError('life/intensity must be finite in 0..2')
    return value


def pulse(frame, peak, attack, release):
    t = (frame-peak)/max(1, attack if frame <= peak else release)
    return .5+.5*math.cos(math.pi*t) if abs(t) <= 1 else 0.


def emotion_at(events, frame):
    event = next((e for e in reversed(events) if e['frames'][0] <= frame <=
                  (e.get('relax_frame') or e['frames'][1])), {})
    emotion = event.get('emotion', 'base')
    emotion = {'big_smile': 'joy', 'smile': 'joy', 'angry': 'anger',
               'furious': 'anger', 'surprised': 'surprise'}.get(emotion, emotion)
    return emotion, event.get('strength', .3)


def score(start, end, fps, words=(), emotions=(), listeners=(), cuts=(), turns=(), seed=3, amount=1.,
          existing_blinks=(), blink=True):
    """Return per-frame face deltas and reviewable blink/reaction/gaze events.

    listeners: [(word-times, emotion-events), ...]. Word times use scene frames.
    cuts and turns supply extra blink opportunities; refractory time avoids flurries.
    """
    amount = intensity(amount)
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    if not math.isfinite(fps) or fps <= 0 or end < start or end-start > 24000:
        raise ValueError('invalid fps or frame range (maximum 24000 frames)')
    rng = random.Random(seed)
    accents = []
    for i, (word, a, b) in enumerate(words):
        if i == 0 or a-words[i-1][2] > .22*fps or len(word) >= 6 or word.endswith(('!', '?')):
            accents.append(((a+b)/2, rng.choice(('Left', 'Right')), rng.uniform(.65, 1.)))
    reactions = []
    for other_words, events in listeners:
        last = -1e9
        for word, a, b in other_words:
            center = round((a+b)/2+.18*fps)
            if center-last < fps*1.1 or any(x-.2*fps <= center <= y+.25*fps for _, x, y in words):
                continue
            if len(word) >= 5 or word.endswith(('!', '?')):
                emotion, strength = emotion_at(events, center)
                reactions.append(dict(frame=center, emotion=emotion, strength=strength,
                                      side=rng.choice(('Left', 'Right'))))
                last = center
    blinks, f = [], start+round(rng.uniform(.7, 1.9)*fps)
    while f < end-6:
        emotion, _ = emotion_at(emotions, f)
        interval = {'fear': 2.0, 'anger': 2.4, 'sad': 4.2, 'thinking': 2.6,
                    'surprise': 4.5}.get(emotion, 3.3)
        blinks.append(dict(frame=f, depth=.52 if rng.random() < .22 else 1.,
                           width=rng.choice((.20, .25, .30)), source='rhythm'))
        f += max(8, round(fps*interval*rng.uniform(.7, 1.25)))
    for f, source in [(f, 'cut') for f in cuts]+[(f, 'turn') for f in turns]:
        if start+2 <= f <= end-6 and all(abs(f-b['frame']) > .65*fps for b in blinks):
            blinks.append(dict(frame=int(f), depth=.9, width=.25, source=source))
    blinks.sort(key=lambda b: b['frame'])
    blinks = [b for b in blinks if blink and all(abs(b['frame']-f) > fps for f in existing_blinks)]
    holds, f = [], start
    while f <= end:
        away = bool(listeners) and rng.random() < .17
        yaw = rng.uniform(-.016, .016) + (rng.choice((-1, 1))*.13 if away else 0)
        pitch = rng.uniform(-.012, .012) + (-.08 if away else 0)
        stop = min(end, f+max(5, round(fps*rng.uniform(.75, 1.8))))
        holds.append(dict(frame=f, end=stop, yaw=yaw, pitch=pitch, away=away,
                          micro=round((f+stop)/2), micro_yaw=rng.uniform(-.008, .008)))
        f = stop+1
    frames = []
    phase = rng.uniform(0, math.tau)
    for f in range(start, end+1):
        values = {}
        emotion, strength = emotion_at(emotions, f)
        speaking = any(a-.15*fps <= f <= b+.22*fps for _, a, b in words)
        def add(name, value):
            values[name] = values.get(name, 0)+value*amount
        for peak, side, weight in accents:
            p = pulse(f, peak, .18*fps, .40*fps)*weight
            brow = 'browDown' if emotion in ('anger', 'sad') else 'browOuterUp'
            add(brow+side, .10*p)
            add('cheekSquint'+side, .055*p)
            # Mouth corners are a listening/pause layer. Speech owns the lips.
            if not speaking:
                add(('mouthFrown' if emotion in ('sad', 'fear', 'anger') else 'mouthSmile')+side, .055*p)
        for reaction in reactions:
            p = pulse(f, reaction['frame'], .25*fps, .65*fps)*(.6+.5*reaction['strength'])
            side, mood = reaction['side'], reaction['emotion']
            add('browInnerUp', .10*p)
            add('browOuterUp'+side, .07*p)
            if not speaking:
                add(('mouthFrown' if mood in ('sad', 'fear', 'anger') else 'mouthSmile')+side, .10*p)
                add('cheekSquint'+side, .05*p)
        hold = next(h for h in holds if h['frame'] <= f <= h['end'])
        # Two-frame landing, then a stable fixation; occasional tiny return movement.
        idx = holds.index(hold)
        prev = holds[max(0, idx-1)]
        u = min(1., (f-hold['frame'])/2)
        yaw = prev['yaw']*(1-u)+hold['yaw']*u
        pitch = prev['pitch']*(1-u)+hold['pitch']*u
        yaw += hold['micro_yaw']*pulse(f, hold['micro'], 2, 4)
        for name, value in (('eyeLookOutLeft', yaw), ('eyeLookInRight', yaw),
                            ('eyeLookInLeft', -yaw), ('eyeLookOutRight', -yaw),
                            ('eyeLookDownLeft', pitch), ('eyeLookDownRight', pitch),
                            ('eyeLookUpLeft', -pitch), ('eyeLookUpRight', -pitch)):
            add(name, value)
        # Slow asymmetric settling during a fixation, also on silent listeners.
        drift = .5+.5*math.sin((f-start)/fps*1.3+phase)
        add('browOuterUp'+('Left' if seed % 2 else 'Right'), .016*drift)
        add('cheekSquint'+('Right' if seed % 2 else 'Left'), .012*(1-drift))
        for side in ('Left', 'Right'):
            add('eyeBlink'+side, 0.)
            add('eyeSquint'+side, max(0, pitch)*.25)
            add('eyeWide'+side, max(0, -pitch)*.30)
        for blink in blinks:
            width = max(4, round(blink['width']*fps))
            for side, delay in (('Left', 0), ('Right', 1)):
                add('eyeBlink'+side, blink['depth']*pulse(f, blink['frame']+delay, 2, width-2))
        breath = (.5-.5*math.cos(math.tau*(f-start)/fps/3.8+phase))
        add('breath', breath*(.35 if speaking else 1.))
        if not speaking:
            add('noseSneerLeft', .012*breath)
            add('noseSneerRight', .009*breath)
            add('jawOpen', .009*breath)
        frames.append((f, values))
    return dict(frames=frames, blinks=blinks, reactions=reactions, holds=holds,
                accents=[round(a[0]) for a in accents])
