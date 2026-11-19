"""Bar-aligned mood changes using the existing offline composer and renderers."""
import math
import numpy as np
from .compose import compose
from .dsp import RATE, render


def resolve(cues, tempo, fps, first, end):
    bar = 240/tempo*fps
    result = []
    for cue in sorted(cues, key=lambda c: c['frame']):
        at = first+round(math.ceil(max(0, cue['frame']-first)/bar-1e-9)*bar)
        if at < end:
            item = dict(cue, frame=at, requested_frame=cue['frame'])
            if result and result[-1]['frame'] == at:
                result[-1] = item
            else:
                result.append(item)
    return result


def render_cues(score, cues, backend):
    fps, first = score['fps'], score['first']
    end = first+round(score['duration']*fps)
    changes = resolve(cues, score['tempo'], fps, first, end)
    if not changes or changes[0]['frame'] > first:
        changes.insert(0, dict(frame=first, mood=score['mood'], name='opening'))
    output = np.zeros((round(score['duration']*RATE), 2), np.float32)
    renderers = []
    for i, cue in enumerate(changes):
        lo = cue['frame']; hi = changes[i+1]['frame'] if i+1 < len(changes) else end
        if cue.get('mood') is None or hi <= lo:
            continue
        seconds = (hi-lo)/fps
        part = compose(max(.25, seconds), cue['mood'], score['tempo'], score['key'],
                       score['intensity'], score['seed']+i,
                       cuts=[a['frame'] for a in score.get('accents',[]) if lo<=a['frame']<hi],
                       emotions=[e for e in score.get('emotion_cues',[]) if lo<=e['frame']<hi],
                       fps=fps, first=lo)
        x = render(part, fade_in=.04, fade_out=.08, backend=backend)
        at = round((lo-first)/fps*RATE)
        count = min(round(seconds*RATE), len(output)-at)
        output[at:at+count] = x[:count]
        renderers.append(part['renderer'])
    score['renderer'] = renderers[0] if renderers else {'backend': 'synth'}
    score['cue_sections'] = changes
    return output
