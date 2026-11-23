"""Initial seated desk blocking and microphone placement with existing rigs/props."""
import bpy
from mathutils import Vector
from . import dispatch

DESK_SETS = {'podcast_studio','news_desk','office'}


def _rod(obj, a, b):
    inv = obj.parent.matrix_world.inverted() if obj.parent else None
    a,b = (inv@a,inv@b) if inv else (a,b)
    depth = max(v.co.z for v in obj.data.vertices)-min(v.co.z for v in obj.data.vertices)
    obj.location = (a+b)/2
    obj.rotation_euler = (b-a).to_track_quat('Z','Y').to_euler()
    obj.scale = (1,1,(b-a).length/max(depth,1e-6))


def stage(cast, beats=()):
    sc = bpy.context.scene
    root = next((o for o in sc.objects if o.get('c3d_environment_preset') in DESK_SETS),None)
    if not root or not cast:
        return {}
    if any(b.get('do') in ('sit','stand','walk','interact','enter') for b in beats):
        return dict(mode='authored',seats=[])
    if root.get('c3d_desk_seated'):
        return dict(mode='existing',seats=[])
    root['c3d_desk_seated'] = True
    unit = abs(root.matrix_world.to_scale().x)
    floor = root.matrix_world.translation.z
    # Normal chairs need a seated desk height, rather than the standing preset.
    for obj in root.children_recursive:
        if obj.type!='MESH':
            continue
        if obj.get('c3d_prop_kind')=='desk' or 'anchor_desk' in obj.name:
            inv = obj.matrix_world.inverted()
            for v in obj.data.vertices:
                point = obj.matrix_world@v.co
                point.z = floor+(point.z-floor)*.75
                v.co = inv@point
            obj.data.update()
        elif obj.get('c3d_prop_kind') in ('screen','laptop'):
            obj.location.z -= .255
    # Move existing chairs close enough to use the desk, maintaining their spacing.
    # Podcast chairs (1.72 m apart) pushed seated faces to the two-shot edges.
    inward = .72 if root.get('c3d_environment_preset')=='podcast_studio' else 1.
    chairs = [o for o in root.children_recursive if o.get('c3d_prop_kind')=='chair']
    anchors = {o.name: o.location.x for o in chairs if o.name==o.get('c3d_prop_group')}
    for obj in chairs:
        obj.location.y -= .72
        # Shift each chair as one rigid group; never squash its parts.
        obj.location.x += anchors.get(obj.get('c3d_prop_group'),0.)*(inward-1)
    bpy.context.view_layer.update()
    seats = [o for o in root.children_recursive if 'c3d_seat_centers' in o]
    used, rows = set(),[]
    saved = sc.frame_start,sc.frame_end
    try:
        sc.frame_start = 0
        sc.frame_end = max(2,sc.frame_end)
        for name in cast:
            rig = bpy.data.objects[name]
            choices = [o for o in seats if o.name not in used and abs(o.matrix_world.translation.x-rig.location.x)<.6*unit]
            seat = min(choices,key=lambda o:(o.matrix_world.translation-rig.location).length) if choices else None
            if seat is None:
                position = Vector((rig.location.x,root.matrix_world.translation.y-.1*unit,floor))
                chair = dispatch('add_prop',dict(kind='chair',location=list(position),scale=unit))
                seat = bpy.data.objects[bpy.data.objects[chair['root']]['c3d_seat_anchor']]
            used.add(seat.name)
            rig['c3d_desk_seat'] = True
            # Bake the settled pose before frame one, without adding a sit beat.
            dispatch('sit_on',dict(character=name,seat=seat.name,start_frame=0,transition_frames=1,hands='desk'))
            dispatch('set_hand_pose',dict(character=name,shape='open',frame=1,keyframe=True))  # relaxed curls fingertips into the desk
            from .talk import _fcurves
            if rig.animation_data and rig.animation_data.action:
                for fc in _fcurves(rig.animation_data.action):
                    for key in list(fc.keyframe_points):
                        if key.co.x<1:
                            fc.keyframe_points.remove(key,fast=True)
                    fc.update()
            rows.append(dict(character=name,seat=seat.name,seat_index=0))
    finally:
        sc.frame_start,sc.frame_end = saved
        sc.frame_set(1)
    from .face_geometry import FaceGeometry
    actors = [bpy.data.objects[n] for n in cast]
    microphones = {}
    for obj in root.children_recursive:
        if obj.get('c3d_prop_kind')=='microphone':
            microphones.setdefault(obj['c3d_prop_group'],[]).append(obj)
    mic_rows = []
    for parts in microphones.values():
        clamp = next(o for o in parts if 'mic_clamp' in o.name)
        rig = min(actors,key=lambda r:abs(r.location.x-clamp.matrix_world.translation.x))
        geometry = FaceGeometry(rig,1.75*unit).points()
        mouth = geometry['mouth'][len(geometry['mouth'])//2]
        base = clamp.matrix_world.translation.copy();base.z=floor+.78*unit
        outward = -1 if rig.location.x<root.matrix_world.translation.x else 1
        # Beside the chin line, clear of the face and of gestures in front of the chest.
        head = mouth+Vector((outward*.19*unit,-.28*unit,-.21*unit))
        axis = (mouth-head).normalized()
        joint = base+Vector((0,.10*unit,.09*unit))
        bottom = head-axis*(.21*unit)
        for obj in parts:
            if 'mic_arm_lower' in obj.name:_rod(obj,base,joint)
            elif 'mic_arm_upper' in obj.name:_rod(obj,joint,bottom)
            elif 'mic_body' in obj.name:_rod(obj,bottom,head-axis*(.04*unit))
            elif 'mic_grille' in obj.name:_rod(obj,head-axis*(.04*unit),head+axis*(.04*unit))
            elif 'mic_clamp' in obj.name:
                obj.location = obj.parent.matrix_world.inverted()@base
        mic_rows.append(dict(character=rig.name,mouth=list(mouth),head=list(head),axis=list(axis),clearance_m=mouth.z-head.z))
    bpy.context.view_layer.update()
    return dict(mode='seated',seats=rows,microphones=mic_rows)
