"""Baked additive morph layer. Original face/body/arm curves remain byte-for-byte.

Owned keys duplicate authored relative deltas; they never replace ARKit/viseme
curves. Reruns replace only owned keys in range. Native keys survive save/export
and separate-process rendering without handlers or drivers.
"""
import json
import math

import bpy
from mathutils import Vector

from . import command
from .face import _basemesh, _ensure_face, _face_meshes, VISEMES, MOUTH_UNITS
from ..face_life import score, intensity as life_intensity

PREFIX = '__c3d_life_'


def _emotions(base):
    return json.loads(base.get('char3d_emotions', '[]'))


def _rhythm(base, rig, start, end, fps):
    from .semantic import load_words
    from .talk import _speech_env, _smooth, _phrases
    words = load_words(base, start, end)
    if words:
        return words, 'words'
    # Acoustic-only lip sync has no transcript. Use voiced phrase spans from its
    # own audio/visemes without inventing stored words or subtitle text.
    envelope, _ = _speech_env(rig or base, base, start, end)
    spans = _phrases(_smooth(envelope), fps)
    return [('speech', start+a, start+b) for a, b in spans if b > a], 'envelope' if spans else 'none'


def _layer_key(obj, name):
    keys = obj.data.shape_keys.key_blocks
    owned = keys.get(PREFIX+name)
    if owned:
        return owned
    original = keys.get(name)
    if original is None:
        return None
    owned = obj.shape_key_add(name=PREFIX+name, from_mix=False)
    owned.value = 0.
    # An imported key can be relative to another key, not Basis. Copy its delta
    # against that same relative key instead of accidentally including that pose.
    owned.relative_key = original.relative_key
    owned.vertex_group = original.vertex_group
    for source, target in zip(original.data, owned.data):
        target.co = source.co
    owned.slider_min, owned.slider_max = -2., 2.
    return owned


def _breath_key(obj, rig):
    from .anim import semantic_map
    smap = semantic_map(rig)
    if not {'head', 'hips'} <= smap.keys() or not any(m.type == 'ARMATURE' for m in obj.modifiers):
        return None
    height = rig.data.bones[smap['head']].tail_local.z-rig.data.bones[smap['hips']].head_local.z
    floor = rig.data.bones[smap['hips']].head_local.z-height
    height *= 2
    if height <= .1:
        return None
    matrix = rig.matrix_world.inverted() @ obj.matrix_world
    inverse = matrix.inverted().to_3x3()
    keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else {}
    if PREFIX+'breath' in keys:
        keys[PREFIX+'breath'].slider_max = 2.
        return keys[PREFIX+'breath']
    points = keys[0].data if keys else obj.data.vertices
    offsets = []
    for p in points:
        co = matrix @ p.co
        z = (co.z-floor)/height
        weight = max(0., 1-abs(z-.71)/.16)**2 * max(0., 1-abs(co.x)/(.32*height))
        offsets.append(inverse @ Vector((co.x*.003*weight, -.0012*height*weight, .0014*height*weight)))
    if not any(v.length > 1e-6 for v in offsets):
        return None
    if not keys:
        obj.shape_key_add(name='Basis', from_mix=False)
    key = obj.shape_key_add(name=PREFIX+'breath', from_mix=False)
    key.value = 0.
    key.slider_max = 2.
    for p, target, delta in zip(points, key.data, offsets):
        target.co = p.co+delta
    return key


def _clear(meshes, start, end):
    from .talk import _data_curves
    for obj in meshes:
        sk = obj.data.shape_keys
        if not sk:
            continue
        for fc in _data_curves(sk):
            if fc.data_path.startswith('key_blocks["'+PREFIX):
                for i in range(len(fc.keyframe_points)-1, -1, -1):
                    point = fc.keyframe_points[i]
                    if start <= point.co.x <= end:
                        fc.keyframe_points.remove(point, fast=True)
                fc.update()
        for key in sk.key_blocks:
            if key.name.startswith(PREFIX):
                key.value = 0
                key.keyframe_insert('value', frame=start)
                key.keyframe_insert('value', frame=end)


@command('face_life')
def face_life(character, frame_start=None, frame_end=None, intensity=1., seed=3,
              listen_to=None, cuts=None, turns=None, clear=False, eyes=True, brows=True, blink=True):
    """Replace a seeded additive life layer; 0/clear removes it only in this range.

    Run after expressions, lip sync, blinks, gaze and cameras. listen_to accepts
    a rig name or list. Blinks react to saved emotions, cuts and head turns.
    Eyeball scale is preserved; pupil morphs are used only when authored on the asset. Rerun after editing speech/expressions/lighting.
    """
    from .talk import _rig_of, _data_curves
    k = life_intensity(intensity)
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    sc = bpy.context.scene
    current = sc.frame_current, sc.frame_subframe
    start = int(sc.frame_start if frame_start is None else frame_start)
    end = int(sc.frame_end if frame_end is None else frame_end)
    fps = sc.render.fps/sc.render.fps_base
    # Validate before adding keys or clearing an existing performance.
    if end < start or end-start > 24000:
        raise ValueError('invalid frame range (maximum 24000 frames)')
    base = _basemesh(character)
    _ensure_face(base)
    try:
        rig = _rig_of(character)
    except ValueError:
        rig = None
    character_name = rig.name if rig else base.name
    meshes = [m for m in rig.children_recursive if m.type == 'MESH'] if rig else [base]
    if clear or k == 0:
        _clear(meshes, start, end)
        base['char3d_face_life'] = json.dumps(dict(frames=[start, end], intensity=0., seed=seed))
        sc.frame_set(current[0], subframe=current[1])
        return dict(character=character_name, frames=[start, end], intensity=0., cleared=True)
    listeners = []
    for name in ([listen_to] if isinstance(listen_to, str) else listen_to or []):
        other = _basemesh(name)
        try:
            other_rig = _rig_of(name)
        except ValueError:
            other_rig = None
        listeners.append((_rhythm(other, other_rig, start, end, fps)[0], _emotions(other)))
    cuts = cuts if cuts is not None else [m.frame for m in sc.timeline_markers if m.camera]
    if turns is None and rig:
        from .anim import semantic_map
        from .script_scene import _bones_only
        head = semantic_map(rig).get('head')
        turns = []
        saved = sc.frame_current, sc.frame_subframe
        previous, last_turn = None, start-1000
        try:
            with _bones_only():
                for frame in range(start, end+1, max(1, round(fps/8))):
                    sc.frame_set(frame)
                    q = rig.pose.bones[head].matrix.to_quaternion() if head else None
                    angle = previous.rotation_difference(q).angle if q and previous else 0
                    if min(angle, math.tau-angle) > math.radians(10) and frame-last_turn > fps:
                        turns.append(frame)
                        last_turn = frame
                    previous = q
        finally:
            sc.frame_set(saved[0], subframe=saved[1])
    sk = base.data.shape_keys
    paths = {f'key_blocks["eyeBlink{side}"].value' for side in ('Left', 'Right')}
    blink_curves = [fc for fc in _data_curves(sk) if fc.data_path in paths]
    samples = [max((fc.evaluate(f) for fc in blink_curves), default=0.) for f in range(start, end+1)]
    authored, run = [], []
    for i, value in enumerate(samples+[0.]):
        if value > .35:
            run.append(i)
        elif run:
            # Long held winks/closed-eye expressions are not blink events.
            if len(run) < fps*.6:
                authored.append(start+max(run, key=lambda j: samples[j]))
            run = []
    words, rhythm = _rhythm(base, rig, start, end, fps)
    plan = score(start, end, fps, words, _emotions(base), listeners,
                 cuts, turns or [], seed, k, authored, blink and eyes)
    _clear(meshes, start, end)
    channels = {name for _, values in plan['frames'] for name in values}
    channels = {n for n in channels if (eyes or not n.startswith('eye'))
                and (brows or not n.startswith('brow'))}
    # Optional authored pupil morphs: a small, static light adaptation. Never
    # scale an eyeball (which would alter its cornea and sockets).
    look = json.loads(sc.get('char3d_cinematic_look', '{}')).get('preset')
    pupil = 'pupilDilate' if look in ('night', 'blue_hour') else 'pupilSmall'
    if eyes and pupil in base.data.shape_keys.key_blocks:
        channels.add(pupil)
        for _, values in plan['frames']:
            values[pupil] = .10*k
    face_meshes = _face_meshes(base)
    owned = {}
    for obj in face_meshes:
        owned[obj] = {n: key for n in sorted(channels) if n != 'breath' and (key := _layer_key(obj, n)) is not None}
    breathing = []
    for obj in meshes:
        key = _breath_key(obj, rig) if rig else None
        if key:
            owned.setdefault(obj, {})['breath'] = key
            breathing.append(obj.name)
    # Read base action values directly: no animation keys added here can feed back
    # into a later frame's baseline. Also honor nonzero unanimated authored values.
    baselines = {}
    for obj, mapping in owned.items():
        sk = obj.data.shape_keys
        curves = {fc.data_path: fc for fc in _data_curves(sk)}
        baselines[obj] = {n: (curves.get(sk.key_blocks[n].path_from_id('value')), sk.key_blocks[n].value)
                          for n in channels | set(VISEMES) | set(MOUTH_UNITS) if n in sk.key_blocks}
    # Imported face rigs can use NLA or drivers. Sample those evaluated values
    # before adding any offsets; ordinary actions retain the inexpensive path.
    evaluated = {}
    layered = [obj for obj in owned if (ad := obj.data.shape_keys.animation_data) and (
        ad.drivers or any(not track.mute for track in ad.nla_tracks) or
        ad.action_influence != 1 or (ad.action and len(ad.action.layers) > 1))]
    if layered:
        from .script_scene import _bones_only
        try:
            with _bones_only():
                for frame in range(start, end+1):
                    sc.frame_set(frame)
                    evaluated[frame] = {obj: {n: obj.data.shape_keys.key_blocks[n].value
                                              for n in baselines[obj]} for obj in layered}
        finally:
            sc.frame_set(current[0], subframe=current[1])
    for frame, values in plan['frames']:
        fade = min(1., max(0., (frame-start)/max(1, .2*fps)), max(0., (end-frame)/max(1, .2*fps)))
        for obj, mapping in owned.items():
            sample = evaluated.get(frame, {}).get(obj)
            if sample is None:
                sample = {n: fc.evaluate(frame) if fc else value
                          for n, (fc, value) in baselines[obj].items()}
            def original(name):
                return sample.get(name, 0.)
            closure = max(original('p_b_m_21'), original('mouthClose'))
            articulation = sum(original(v) for v in VISEMES if v != 'sil_00') > .02 or original('jawOpen') > .03
            for name, key in mapping.items():
                delta = values.get(name, 0.)*fade
                if name == 'breath':
                    key.value = delta
                else:
                    value = original(name)
                    if name.startswith(('mouth', 'jaw', 'nose')):
                        delta *= max(0., 1-closure*5)
                        if articulation:
                            delta = 0.
                    if name.startswith('eyeBlink'):
                        side = 'Left' if name.endswith('Left') else 'Right'
                        delta = max(0., delta-value) + original('eyeLookDown'+side)*.08*k*fade
                    if name.startswith('eyeWide'):
                        side = 'Left' if name.endswith('Left') else 'Right'
                        delta += original('eyeLookUp'+side)*.06*k*fade
                        blink = max(original('eyeBlink'+side), values.get('eyeBlink'+side, 0.)*fade)
                        delta -= (value+delta)*min(1., blink)
                    key.value = max(-max(0., value), min(max(0., 1-value), delta))
                key.keyframe_insert('value', frame=frame)
    # Linear samples have no Bezier overshoot on the blink or closed-lip boundaries.
    for obj, mapping in owned.items():
        sk = obj.data.shape_keys
        paths = {key.path_from_id('value') for key in mapping.values()}
        for key in mapping.values():
            for frame in (start-1, end+1):
                # Outside-range samples belong to a preceding/following bake.
                curves = _data_curves(sk)
                fc = next((c for c in curves if c.data_path == key.path_from_id('value')), None)
                if fc and any(abs(p.co.x-frame) < .01 for p in fc.keyframe_points):
                    continue
                key.value = 0
                key.keyframe_insert('value', frame=frame)
        for fc in _data_curves(sk):
            if fc.data_path in paths:
                for point in fc.keyframe_points:
                    if start <= point.co.x <= end:
                        point.interpolation = 'LINEAR'
    config = dict(frames=[start, end], intensity=k, seed=seed,
                  rhythm=rhythm,
                  blinks=plan['blinks'], authored_blinks=authored, reactions=plan['reactions'],
                  gaze_holds=plan['holds'] if eyes else [])
    base['char3d_face_life'] = json.dumps(config)
    sc.frame_set(current[0], subframe=current[1])
    return dict(character=character_name, **config, accents=plan['accents'], breathing=breathing,
                layer=PREFIX, pupil=pupil if pupil in channels else 'unsupported; eyeball scale preserved')
