"""Anatomical head frames shared by performance and camera coverage."""
from mathutils import Matrix, Vector

from .anim import semantic_map


def head_frame(rig, bone="head"):
    """Live world head center and anatomical orientation, including pelvis motion.

    Bone local axes differ between basic, MPFB and imported skeletons. Apply the
    rest-to-pose deformation to the anatomical rest frame instead of assuming that
    object rotation (or a bone's local -Y) describes the character's face.
    """
    smap = semantic_map(rig)
    name = smap.get(bone) or smap["head"]
    rest, posed = rig.data.bones[name], rig.pose.bones[name]
    left = (rig.data.bones[smap["thigh.L"]].head_local -
            rig.data.bones[smap["thigh.R"]].head_local).normalized()
    up = rig.data.bones[smap["head"]].tail_local - rig.data.bones[smap["hips"]].head_local
    up = (up - left * up.dot(left)).normalized()
    back = left.cross(up).normalized() * -1
    anatomical = Matrix((left, back, up)).transposed().to_quaternion()
    deform = rig.matrix_world @ posed.matrix @ rest.matrix_local.inverted()
    center = rig.matrix_world @ ((posed.head + posed.tail) / 2)
    return center, deform.to_quaternion() @ anatomical


def face_angle(position, orientation, camera_position):
    direction = camera_position - position
    if direction.length < 1e-8:
        return 180.0
    import math
    return math.degrees((orientation @ Vector((0, -1, 0))).angle(direction))
