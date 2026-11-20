"""Execute editorial decisions after body, speech and normal dialog coverage exist."""
import json
import math
import bpy
from mathutils import Vector
from . import dispatch


def cameras(plan, characters, shots, prefix, warnings):
    sc = bpy.context.scene
    cast = [c['rig'] for c in characters.values()]
    baseline = sorted([(m.frame, m.camera) for m in sc.timeline_markers if m.camera], key=lambda x: x[0])
    cues = [b for b in plan['beats'] if b.get('do') == 'camera']
    # Dialog coverage cuts four frames before speech. Share that cut boundary
    # instead of leaving a four-frame sliver before an editorial override/auto.
    starts = [next((f for f,_ in reversed(baseline) if 0 <= b['frames'][0]-f <= 4),b['frames'][0]) for b in cues]
    from .gaze import head_frame
    for i, beat in enumerate(cues):
        lo = starts[i]
        hi = starts[i+1]-1 if i+1 < len(cues) else sc.frame_end
        if hi < lo:
            continue
        cover = next((cam for f, cam in reversed(baseline) if f <= lo), sc.camera)
        if beat['shot'] == 'auto':
            if cover:
                for marker in [m for m in sc.timeline_markers if m.frame == lo]:
                    sc.timeline_markers.remove(marker)
                marker = sc.timeline_markers.new(prefix+f'Auto{i}', frame=lo)
                marker.camera = cover
            continue
        for marker in [m for m in sc.timeline_markers if lo <= m.frame <= hi]:
            sc.timeline_markers.remove(marker)
        sc.frame_set(lo)
        angle = beat.get('angle', 20)
        if len(cast) >= 2:
            a, b = [head_frame(bpy.data.objects[r])[0] for r in cast[:2]]
            axis = b-a
            ref = (cover.matrix_world.translation-a) if cover else Vector((0, -1, 0))
            proposed = Vector((math.sin(math.radians(angle)), -math.cos(math.radians(angle)), 0))
            if axis.cross(ref).z*axis.cross(proposed).z < 0:
                angle = (angle+180) % 360-180
                angle = angle+180 if angle < 0 else angle-180
        args = dict(subject=[characters[n]['rig'] for n in beat.get('subject', characters)],
                    shot=beat['shot'], move=beat['move'], angle=angle,
                    intensity=beat.get('intensity', .25), elevation=beat.get('elevation', 5),
                    start_frame=lo, end_frame=max(lo+1, hi), name=prefix+f'Cue{i:02d}',
                    action_line=cast[:2] if len(cast)>1 else None, require_composition=True,
                    face_coverage=beat['move'] in ('static','push_in','dolly_in','dolly_out','handheld'))
        if beat['shot'] == 'over_shoulder':
            if len(args['subject']) == 1:
                args['foreground'] = next((n for n in cast if n != args['subject'][0]), None)
        report = dispatch('camera_shot', args)
        # A requested orbit/reveal can cross the dialog line during its travel.
        # Retain the side, then visibly report the reduced move rather than crossing it.
        if len(cast) > 1:
            sides = []
            for f in (lo, (lo+hi)//2, hi):
                sc.frame_set(f)
                a, b = [head_frame(bpy.data.objects[r])[0] for r in cast[:2]]
                sides.append((b-a).cross(bpy.data.objects[report['camera']].matrix_world.translation-a).z)
            if min(sides)*max(sides) < 0:
                args.update(move='static')
                report = dispatch('camera_shot', args)
                warnings.append('Camera cue reduced to static to keep the dialog action-line side.')
        bpy.data.objects[report['camera']]['c3d_deliberate_cut'] = bool(beat.get('deliberate',False))
        report['director_cue'] = True
        report['reason'] = dict(role='explicit', emotion='authored', intensity=beat.get('intensity', .25),
                                detail='explicit camera cue overrides automatic coverage')
        bpy.data.objects[report['camera']]['c3d_shot_reason'] = json.dumps(report['reason'])
        beat['result'] = report
        shots.append(report)
    # Return the effective cut intervals, not coverage cameras hidden by an override.
    reports = {s['camera']: s for s in shots}
    current = dispatch('list_shots', {})['shots']
    shots[:] = [dict(reports.get(s['camera'], {}), **s) for s in current if s['camera']]


def audio(plan, result):
    sc = bpy.context.scene
    from .audio import _sound_strips, _key_volume
    silences = [dict(start=b['frames'][0], end=b['frames'][1]+1, db=-30)
                for b in plan['beats'] if b.get('do') == 'silence']
    sc['char3d_director_silences'] = json.dumps(silences)
    cfg = plan.get('music')
    cues = [dict(frame=b['frames'][0], mood=b['mood'], name='director')
            for b in plan['beats'] if b.get('do') == 'music']
    if cfg:
        result['music'] = dispatch('auto_music', dict(mood=cfg['mood'], tempo=cfg['tempo'],
            key=cfg['key'], seed=plan['seed'], sections=cues or None))
    else:
        result['music'] = dispatch('auto_music', {'clear': True})
    for strip in _sound_strips(sc):
        if strip.get('char3d_sfx_kind') == 'ambience':
            _key_volume(strip)
    result['director_cues'] = dict(silences=silences, music=cues)
