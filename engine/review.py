"""Pure review rules. Heuristics return measurements and editable tool suggestions."""
import math
import re
import numpy as np

CATEGORIES = ('sound', 'rhythm', 'camera', 'performance', 'continuity', 'readability')
WEIGHTS = (.28, .19, .19, .16, .08, .10)


def issue(rule, category, severity, message, evidence=None, fix=None, auto=False, **where):
    suffix = ':'.join(str(where[k]) for k in ('scene', 'shot', 'character', 'frame', 'time') if where.get(k) is not None)
    return dict(id=rule+(':'+suffix if suffix else ''), category=category, severity=severity,
                message=message, evidence=evidence or {}, fix=fix or [], auto_fixable=bool(auto), **where)


def call(tool, **args):
    return dict(tool=tool, args=args)


def articulation_present(curves, start, end, fps=24):
    """Check changing mouth channels, also for audio-only lip sync without words."""
    points=sorted({start-1,start,(start+end)/2,end,*np.arange(start,end+1,max(1,fps/12)).tolist()})
    for curve in curves:
        values=[float(curve.evaluate(f)) for f in points]
        if max(values)-min(values)>.015 and max(abs(v) for v in values)>.025:return True
    return False


def safe_fixes(issues):
    """One batch, restricted to reversible tool operations; merge shared mix fixes."""
    import copy
    allowed={'auto_blink','duck_music','auto_sfx','add_subtitles','camera_shot','add_title'}
    selected={}
    for finding in issues:
        if not finding['auto_fixable']:continue
        for source in finding['fix']:
            if source['tool'] not in allowed:continue
            action=copy.deepcopy(source);args=action['args'];tool=action['tool']
            key=(tool,args.get('character') or args.get('name') or args.get('music_strip') or '')
            if key not in selected:
                selected[key]=dict(issue=finding['id'],**action)
                continue
            previous=selected[key]['args']
            if tool=='duck_music':
                previous['amount_db']=min(previous.get('amount_db',-12),args.get('amount_db',-12))
            elif tool=='auto_sfx':
                previous['kinds']=sorted(set(previous.get('kinds',[])) | set(args.get('kinds',[])))
                if previous.get('characters') is not None and args.get('characters') is not None:
                    previous['characters']=sorted(set(previous['characters']) | set(args['characters']))
                else:previous.pop('characters',None)
    return list(selected.values())


def score(issues):
    scores = {c: max(0, 100-sum({'error': 22, 'warn': 8, 'info': 0}[i['severity']]
              for i in issues if i['category'] == c)) for c in CATEGORIES}
    return round(sum(scores[c]*w for c, w in zip(CATEGORIES, WEIGHTS))), scores


def rhythm(shots, fps, words=(), duration=0):
    out, lengths = [], []
    for shot in shots:
        a, b = shot['frames']; seconds = (b-a+1)/fps; lengths.append(seconds)
        where = dict(shot=shot['name'], frame=a)
        if seconds < .8 and not shot.get('deliberate'):
            out.append(issue('short_shot', 'rhythm', 'warn', 'The cut gives this shot less than 0.8 seconds.',
                             dict(seconds=round(seconds, 3), minimum_s=.8), **where))
        if seconds > 8 and shot.get('move', 'static') == 'static':
            out.append(issue('long_static', 'rhythm', 'warn', 'Consider a motivated change or a visible action during this hold.', dict(seconds=seconds), **where))
        if a > 1:
            hit = next((w for w in words if w[1]+.08*fps < a < w[2]-.08*fps), None)
            if hit:
                out.append(issue('word_cut', 'rhythm', 'warn', 'The picture cut falls inside a spoken word.', dict(word=hit[0], word_frames=list(hit[1:])), **where))
    if len(lengths) >= 4:
        cv = float(np.std(lengths)/max(.001, np.mean(lengths)))
        if cv < .12:
            out.append(issue('even_pace', 'rhythm', 'warn', 'Shot durations stay almost equal; consider varying the pace.', dict(duration_cv=round(cv, 4))))
    if duration > 30 and lengths and max(lengths) < 5:
        out.append(issue('no_breath', 'rhythm', 'warn', 'Allow one longer reaction or quiet hold.', dict(longest_shot_s=max(lengths))))
    return out


SIZES = ('extreme_wide', 'wide', 'full', 'medium_full', 'medium', 'medium_close', 'close_up', 'extreme_close_up')


def camera_checks(shots):
    out = []
    for previous, current in zip(shots, shots[1:]):
        same = set(previous.get('subject', [])) == set(current.get('subject', [])) and current.get('subject')
        a = previous.get('angle_end', previous.get('angle', 0)); b = current.get('angle', 0)
        delta = abs((a-b+180) % 360-180)
        near_size = abs(SIZES.index(previous.get('size', 'medium'))-SIZES.index(current.get('size', 'medium'))) <= 1
        if same and near_size and delta < 30:
            out.append(issue('jump_cut', 'camera', 'warn', 'Consecutive views of the same subject have little change in size or angle.',
                dict(angle_change_deg=round(delta, 2), previous=previous['name']), shot=current['name'], frame=current['frames'][0]))
        if previous.get('action_side', 0)*current.get('action_side', 0) < 0:
            out.append(issue('line_crossing', 'camera', 'error', 'Dialog coverage crosses the live action line.',
                dict(previous_side=previous['action_side'], side=current['action_side']), shot=current['name']))
    for s in shots:
        where = dict(shot=s['name'], frame=s['frames'][0])
        if s.get('missing_subjects'):
            out.append(issue('missing_subject','camera','error','Shot subjects no longer exist in the scene.',dict(subjects=s['missing_subjects']),**where))
        repair = s.get('repair', [])
        samples = s.get('samples', [])
        size = s.get('size', 'medium')
        minimum = dict(extreme_wide=.025, wide=.12, full=.48, medium_full=.18, medium=.22,
                       medium_close=.3, close_up=.45, extreme_close_up=.6)[size]
        scale = min((p.get('body_height', 1) if size in ('full', 'wide', 'extreme_wide') else p.get('head_chest_height', 1) for p in samples), default=1)
        if scale < minimum:
            out.append(issue('small_subject', 'camera', 'warn', 'The subject occupies too little of the frame for this shot size.',
                dict(projected_height=round(scale, 4), minimum=minimum, size=size), fix=repair, **where))
        edge = [p for p in samples if p.get('face_edge')]
        blocked = s.get('occlusion', 0)
        if edge or blocked > .05:
            out.append(issue('face_visibility', 'camera', 'warn', 'A face reaches the frame edge or is blocked.',
                dict(edge_samples=len(edge), face_occlusion=blocked), fix=repair, auto=bool(repair), **where))
        if s.get('face_angle',0)>75:
            out.append(issue('face_turned','camera','warn','A subject faces away from the camera; eyes may be hidden by the head or hair.',dict(face_angle_deg=s['face_angle']),shot=s['name']))
        eyes = [p['eye_y'] for p in samples if 'eye_y' in p]
        if size in ('close_up', 'medium_close', 'extreme_close_up') and any(not .20 <= y <= .48 for y in eyes):
            out.append(issue('eye_line', 'camera', 'warn', 'Close-shot eyes lie outside the upper-third band.', dict(eye_y=eyes, band=[.20,.48]), **where))
    if len(shots) >= 4 and len({s.get('size') for s in shots}) < 2:
        out.append(issue('camera_variety', 'camera', 'info', 'All shots use the same size.', dict(distinct_sizes=1, distinct_moves=len({s.get('move') for s in shots}))))
    if not any(s.get('move') not in ('static', None) for s in shots):
        out.append(issue('signature_shot', 'camera', 'info', 'No moving peak shot is recorded; consider a deliberate visual accent.'))
    return out


def subtitle_checks(chunks, fps, first=1, last=None, repair=None):
    out = []
    for c in chunks:
        a, b = max(first, c['start']), min(last+1, c['end']) if last is not None else c['end']
        if b <= a:
            continue
        words = c.get('words', [])
        text = c.get('text') or ' '.join(w[0] for w in words)
        span = (words[-1][2]-words[0][1])/fps if words else 0
        hold = (b-a)/fps
        cps = len(text)/max(hold, .001)
        expected = max(1.8, span+.6)
        evidence = dict(hold_s=round(hold, 3), spoken_s=round(span, 3), target_s=round(expected, 3), cps=round(cps, 2))
        if hold+.05 < expected:
            out.append(issue('subtitle_hold', 'readability', 'warn', 'Caption disappears before a comfortable reading hold.', evidence,
                             fix=repair, auto=bool(repair), frame=round(a)))
        if cps > 17:
            out.append(issue('subtitle_speed', 'readability', 'warn', 'Caption exceeds 17 characters per second.', evidence, fix=repair, auto=bool(repair), frame=round(a)))
    return out


def audio_metrics(samples):
    from .music.dsp import loudness, true_peak
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if not len(x):
        return dict(lufs=-100., true_peak_dbfs=-240., clipped_samples=0)
    peak = true_peak(x)
    return dict(lufs=round(loudness(x), 3), true_peak_dbfs=round(20*math.log10(max(peak, 1e-12)), 3),
                clipped_samples=int(np.count_nonzero(abs(x) >= 1)), duration_s=round(len(x)/48000, 4))


def sound_checks(metrics):
    out = []
    if metrics['clipped_samples'] or metrics['true_peak_dbfs'] > -.1:
        out.append(issue('clipping', 'sound', 'error', 'The mix reaches the digital peak ceiling.', metrics))
    if metrics['lufs'] > -12:
        out.append(issue('mix_hot', 'sound', 'warn', 'The integrated mix is louder than the review range.', dict(lufs=metrics['lufs'], target_lufs=[-24,-14])))
    if metrics['lufs'] < -30:
        out.append(issue('mix_quiet', 'sound', 'warn', 'The integrated mix is very quiet or silent.', dict(lufs=metrics['lufs'])))
    return out


def wer(reference, hypothesis):
    a, b = [re.findall(r'\w+', s.casefold()) for s in (reference, hypothesis)]
    row = list(range(len(b)+1))
    for i, word in enumerate(a, 1):
        nxt = [i]
        for j, heard in enumerate(b, 1):
            nxt.append(min(nxt[-1]+1, row[j]+1, row[j-1]+(word != heard)))
        row = nxt
    return row[-1]/max(1, len(a))


def report_text(report):
    lines = [f"# Film review · {report['score']}/100", '',
             'Scores are editing heuristics. Info findings do not reduce the score.', '',
             ' | '.join(f"{c}: {report['scores'][c]}" for c in CATEGORIES), '']
    for item in report['issues']:
        lines += [f"- **{item['severity']} · {item['category']} · {item['id']}**: {item['message']}",
                  '  Evidence: '+str(item['evidence'])]
        if item['fix']:
            lines += ['  Suggested calls: '+str(item['fix'])]
    if report.get('fixed'):
        lines += ['', 'One deterministic fix round: '+str(report['fixed'])]
    lines += ['', 'Limits: '+ '; '.join(report.get('limits', [])), '', 'Timings: '+str(report.get('timings', {}))]
    return '\n'.join(lines)+'\n'
