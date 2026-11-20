"""Shoulder-relative OTS layout and evaluated eye landmarks."""
import math
import bpy
from mathutils import Euler, Vector
from .anim import semantic_map
from .gaze import head_frame


def eye_point(rig):
    """Evaluated eyeball plane when authored; anatomical fallback otherwise.

    MPFB's head bone extends above the eyes. Its midpoint is not an eye landmark.
    Reading the native eye mesh avoids moving any character or material data.
    """
    eyes = [o for o in rig.children_recursive if o.type == 'MESH'
            and (o.get('c3d_material_part','').lower() in ('high-poly','low-poly','eyes','eye')
                 or o.name.rsplit('.',1)[-1].lower() in ('eyes','eyeballs'))]
    if not eyes:
        from .cinematic import _eye
        return _eye(rig)
    dg = bpy.context.evaluated_depsgraph_get()
    centers = []
    for obj in eyes:
        ev = obj.evaluated_get(dg)
        centers.append(ev.matrix_world @ (sum((Vector(c) for c in ev.bound_box),Vector())/8))
    return sum(centers,Vector())/len(centers) + head_frame(rig)[1]@Vector((0,-.012,0))


def shoulder_site(rig, normal):
    mapping = semantic_map(rig)
    sites = {side: rig.matrix_world @ rig.pose.bones[mapping['upper_arm.'+side]].head
             for side in ('L','R') if 'upper_arm.'+side in mapping}
    if not sites:
        raise ValueError('over_shoulder requires humanoid shoulder joints')
    side = max(sites, key=lambda s: sites[s].dot(normal))
    return sites[side], side


def eye_rotation(position, eye, lens, sensor, x=.5, y=1/3):
    base = (eye-position).to_track_quat('-Z','Y')
    pitch = -math.atan((.5-y)*sensor[1]/lens)
    yaw = math.atan((x-.5)*sensor[0]/lens)
    return (base @ Euler((pitch,yaw,0)).to_quaternion()).to_euler()


def layout(subject, partner, normal, eye, height, sensor, back=.75, side=.30, lift=0., framing=.38, lens=None):
    shoulder, shoulder_side = shoulder_site(partner, normal)
    head, orient = head_frame(partner)
    axis = Vector((head.x-eye.x,head.y-eye.y,0))
    if axis.length<.25:
        raise ValueError('over_shoulder partners must be at least 25 cm apart')
    axis.normalize()
    position = shoulder+axis*(height*back)+normal*(height*side)
    position.z = shoulder.z+height*lift
    distance = (eye-position).length
    mm = float(lens or max(50.,min(85.,distance*sensor[1]/(height*framing))))
    rotation = eye_rotation(position,eye,mm,sensor)
    aim = position+rotation.to_matrix()@Vector((0,0,-distance))
    rear = math.degrees((orient@Vector((0,-1,0))).angle(position-head))
    return position,aim,rotation,mm,dict(shoulder=shoulder_side,head_angle=rear)
