"""Scene adapter for the pure emotional editor and its owned reaction morphs."""
import json
import math
import bpy
import numpy as np

from ..emocam import plan_coverage

REACTION = '__c3d_reaction_'


def _energy(lines):
    """RMS of audible voice samples inside each line, normalized across this cast.

    Respect source trims, mute and volume automation; music/Foley never vote.
    No decoding occurs in the pure planner, and each source is read only once.
    """
    from .audio import _sound_strips, load_audio, _volume_curve
    sc = bpy.context.scene
    fps = sc.render.fps/sc.render.fps_base
    cache, levels = {}, []
    for line in lines:
        total, count = 0., 0
        for strip in _sound_strips(sc):
            if strip.mute or not strip.sound or strip.get('char3d_audio_kind','voice') != 'voice':
                continue
            if strip.get('char3d_speaker') not in (None, line['speaker']):
                continue
            lo = max(line['start'], strip.frame_final_start)
            hi = min(line['end']+1, strip.frame_final_end)
            if hi <= lo:
                continue
            path = bpy.path.abspath(strip.sound.filepath)
            if path not in cache:
                cache[path] = load_audio(path)
            data, rate = cache[path]
            offset = float(getattr(strip, 'sound_offset', 0))
            a = max(0, round(((lo-strip.frame_start)/fps+offset)*rate))
            b = min(len(data), round(((hi-strip.frame_start)/fps+offset)*rate))
            if b <= a:
                continue
            samples = np.asarray(data[a:b], dtype=float)
            curve = _volume_curve(strip)
            grid = np.arange(math.floor(lo), math.ceil(hi)+1)
            gain = [curve.evaluate(f) if curve else strip.volume for f in grid]
            weight = np.interp(lo+np.arange(b-a)/rate*fps, grid, gain)
            if samples.ndim > 1:
                weight = weight[:, None]
            total += float(np.sum((samples*weight)**2))
            count += samples.size
        levels.append(math.sqrt(total/max(1,count)))
    ceiling = max(levels, default=0)
    out = {}
    for i, (line, value) in enumerate(zip(lines, levels)):
        out.setdefault(line['speaker'], {})[i] = value/ceiling if ceiling else 0.
    return out


def plan(turns, names, start, end, beats=None, previous_size=None):
    from .face import _basemesh
    from .semantic import load_words
    words, emotions = {}, {}
    for name in names:
        base = _basemesh(name)
        words[name] = load_words(base, start, end)
        emotions[name] = json.loads(base.get('char3d_emotions','[]'))
    sc = bpy.context.scene
    return plan_coverage(turns, names, start, end, sc.render.fps/sc.render.fps_base,
                         words, emotions, _energy(turns), beats, previous_size)


def reactions(events, names, start, end):
    """Replace only owned additive brow/cheek/corner keys; no jaw, gaze or blink.

    Match face_life's relative-delta semantics in a separate key namespace.
    Original animation curves are never rewritten, including on shared Actions.
    """
    from .face import _basemesh, _ensure_face, _face_meshes, EXPRESSIONS, EMOTION_UNITS
    from .talk import _data_curves
    sc = bpy.context.scene
    saved = sc.frame_current, sc.frame_subframe
    fps = sc.render.fps/sc.render.fps_base
    warnings = []
    try:
        for name in names:
            base = _basemesh(name)
            try:
                _ensure_face(base)
            except (ValueError, RuntimeError):
                if any(e['character']==name for e in events):
                    warnings.append(f'{name}: listener reaction has no facial targets')
                continue
            own = [e for e in events if e['character']==name]
            for obj in _face_meshes(base):
                sk = obj.data.shape_keys
                for fc in _data_curves(sk):
                    if fc.data_path.startswith('key_blocks["'+REACTION):
                        for point in list(fc.keyframe_points)[::-1]:
                            if start-1 <= point.co.x <= end+1:
                                fc.keyframe_points.remove(point, fast=True)
                        fc.update()
                for key in sk.key_blocks:
                    if key.name.startswith(REACTION):
                        key.value = 0.
                        key.keyframe_insert('value', frame=start-1)
                        key.keyframe_insert('value', frame=end+1)
                channels = {n for event in own for n in EXPRESSIONS[event['expression']]
                            if n in EMOTION_UNITS and n in sk.key_blocks}
                for unit in channels:
                    original = sk.key_blocks[unit]
                    key = sk.key_blocks.get(REACTION+unit)
                    if key is None:
                        key = obj.shape_key_add(name=REACTION+unit, from_mix=False)
                        key.relative_key, key.vertex_group = original.relative_key, original.vertex_group
                        for source, target in zip(original.data, key.data):
                            target.co = source.co
                    key.value = 0
                    key.keyframe_insert('value', frame=start-1)
                    curve = next((fc for fc in _data_curves(sk) if fc.data_path==original.path_from_id('value')), None)
                    for event in own:
                        strength = EXPRESSIONS[event['expression']].get(unit, 0)*event['strength']
                        # Cap against the underlying expression, preserving its curves.
                        for frame, amount in ((event['onset']-1,0), (event['peak'],strength),
                                              (max(event['peak'],event['end']-round(.2*fps)),strength),
                                              (event['end']+1,0)):
                            if start <= frame <= end+1:
                                value = curve.evaluate(frame) if curve else original.value
                                key.value = max(0.,min(1-max(0.,value),amount))
                                key.keyframe_insert('value',frame=frame)
                    key.value=0
                    key.keyframe_insert('value',frame=end+1)
                paths = {k.path_from_id('value') for k in sk.key_blocks if k.name.startswith(REACTION)}
                for fc in _data_curves(sk):
                    if fc.data_path in paths:
                        for point in fc.keyframe_points:
                            point.interpolation='LINEAR'
            base['char3d_camera_reactions'] = json.dumps(own)
    finally:
        sc.frame_set(saved[0],subframe=saved[1])
    return warnings


def bake(planned, names, turns, prefix, angle_limits=None):
    from .camera import camera_shot
    shots, warnings = [], list(planned['warnings'])
    for index, item in enumerate(planned['shots']):
        a,b = item['frames']
        who, partner = item['subject'], item['partner']
        role = item['reason']['role']
        # OTS is an actual geometric composition, not a label on a clean single.
        ots = role == 'OTS' and partner is not None
        report = camera_shot(subject=[who] if who else names,
            shot='over_shoulder' if ots else item['size'], foreground=partner if ots else None,
            move=item['move'], start_frame=a, end_frame=b, angle=0, elevation=3.,
            intensity=item['intensity'], handheld=item['handheld'], name=f'{prefix}{index+1:02d}',
            action_line=[who,partner] if who and partner else names[:2],
            angle_limits=angle_limits or [-89.,89.], require_composition=True,
            face_coverage=len(names)>1, coverage_turns=turns)
        cam = bpy.data.objects[report['camera']]
        cam['c3d_shot_reason'] = json.dumps(item['reason'])
        if role == 'reaction' and partner:
            cam['c3d_focus_from'] = partner
        report.update(subject=who or 'two_shot', reason=item['reason'], role=role,
                      foreground=partner if ots else None)
        shots.append(report)
        if report['occlusion'].get('warning'):
            warnings.append(f"{cam.name}: {report['occlusion']['warning']}")
    return shots, warnings
