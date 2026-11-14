"""Finger posing for any humanoid rig with finger bones.

Curl axes are derived from the hand's rest geometry, not from bone-roll conventions, so the
same hand shape works on MPFB game_engine, Rigify and Mixamo-style skeletons:
  * the palm normal comes from the knuckle line (index -> pinky) and the finger direction,
  * its sign from two independent cues: knuckles bulge toward the back of the hand and the
    thumb sits on the palm side.
A curl rotates each finger bone toward the palm; spread rotates base joints sideways.
Rotations are applied in bone space on top of whatever pose/animation the bone already has.
"""
import math

import bpy
from mathutils import Matrix, Quaternion

from . import command

FINGERS = ("thumb", "index", "middle", "ring", "pinky")

# name patterns per rig family: (finger, joint 1..3, side "L"/"R") -> bone name
PATTERNS = (
    lambda f, n, s: f"{f}_{n:02d}_{s.lower()}",                                   # MPFB game_engine
    lambda f, n, s: f"{'thumb' if f == 'thumb' else 'f_' + f}.{n:02d}.{s}",        # Rigify controls
    lambda f, n, s: f"mixamorig:{'Left' if s == 'L' else 'Right'}Hand{f.capitalize()}{n}",  # Mixamo
    lambda f, n, s: f"{'Left' if s == 'L' else 'Right'}Hand{f.capitalize()}{n}",  # Mixamo (no prefix)
    lambda f, n, s: f"{f}_{n:02d}_{s.lower()}".replace("_0", "_"),                # thumb_1_l style
)

# hand shapes: per finger (curl joint1, joint2, joint3) degrees, plus spread degrees
SHAPES = {
    "relaxed": {"thumb": (5, 10, 10), "index": (10, 15, 10), "middle": (14, 18, 12),
                "ring": (18, 22, 14), "pinky": (22, 25, 16), "spread": 0},
    "open": {"thumb": (-8, 0, 0), "index": (0, 3, 2), "middle": (0, 3, 2), "ring": (0, 3, 2),
             "pinky": (0, 3, 2), "spread": 7},
    "palm": {"thumb": (-5, 2, 2), "index": (4, 8, 5), "middle": (5, 9, 6), "ring": (6, 10, 6),
             "pinky": (8, 11, 7), "spread": 8},
    "beat": {"thumb": (12, 18, 12), "index": (22, 32, 20), "middle": (30, 38, 24),
             "ring": (36, 42, 26), "pinky": (42, 46, 28), "spread": -2},
    "point": {"thumb": (25, 35, 30), "index": (0, 0, 0), "middle": (75, 95, 60),
              "ring": (80, 95, 60), "pinky": (85, 95, 60), "spread": 0},
    "fist": {"thumb": (28, 40, 30), "index": (75, 95, 65), "middle": (80, 95, 65),
             "ring": (82, 95, 65), "pinky": (85, 95, 65), "spread": 0},
    "thumbs_up": {"thumb": (-15, -5, 0), "index": (80, 95, 65), "middle": (82, 95, 65),
                  "ring": (84, 95, 65), "pinky": (86, 95, 65), "spread": 0},
    "peace": {"thumb": (28, 40, 30), "index": (0, 0, 0), "middle": (0, 0, 0), "ring": (80, 95, 60),
              "pinky": (85, 95, 60), "spread": 12},
    "three": {"thumb": (28, 40, 30), "index": (0, 0, 0), "middle": (0, 0, 0), "ring": (0, 2, 0),
              "pinky": (85, 95, 60), "spread": 10},
    "four": {"thumb": (30, 42, 32), "index": (0, 0, 0), "middle": (0, 0, 0), "ring": (0, 2, 0),
             "pinky": (0, 3, 0), "spread": 10},
    "ok": {"thumb": (25, 30, 20), "index": (45, 55, 35), "middle": (0, 3, 2), "ring": (0, 3, 2),
           "pinky": (0, 3, 2), "spread": 6},
}
SPREAD_SIDE = {"index": -1.0, "middle": -0.2, "ring": 0.6, "pinky": 1.2}


def find_fingers(rig):
    """{side: {finger: [bone1, bone2, bone3]}} using the first matching naming scheme."""
    names = set(rig.pose.bones.keys())
    for pat in PATTERNS:
        found = {}
        for s in ("L", "R"):
            hand = {}
            for f in FINGERS:
                chain = [pat(f, n, s) for n in (1, 2, 3)]
                if all(c in names for c in chain):
                    hand[f] = chain
            if len(hand) >= 4:
                found[s] = hand
        if found:
            return found
    return {}


def _palm_frame(rig, chains):
    """(palm normal, knuckle line index->pinky) in armature rest space."""
    B = rig.data.bones

    def head(f, n):
        return B[chains[f][n]].head_local

    def tail(f, n):
        return B[chains[f][n]].tail_local

    ref = "middle" if "middle" in chains else next(f for f in chains if f != "thumb")
    side_a = "index" if "index" in chains else ref
    side_b = "pinky" if "pinky" in chains else ("ring" if "ring" in chains else ref)
    across = (head(side_b, 0) - head(side_a, 0)).normalized()
    fdir = (tail(ref, 2) - head(ref, 0)).normalized()
    n = fdir.cross(across).normalized()
    mid = (head(ref, 0) + tail(ref, 2)) / 2
    convex = ((head(ref, 1) + head(ref, 2)) / 2 - mid).dot(n)
    thumb = 0.0
    if "thumb" in chains:
        thumb = (tail("thumb", 2) - (head(side_a, 0) + head(side_b, 0)) / 2).dot(n)
    return (n if (thumb - 10.0 * convex) > 0 else -n), across


def _axes(rig, chains):
    """Per bone: (curl axis, spread axis) in that bone's own rest space."""
    B = rig.data.bones

    def head(f, n):
        return B[chains[f][n]].head_local

    ref = "middle" if "middle" in chains else next(f for f in chains if f != "thumb")
    palm, across = _palm_frame(rig, chains)
    to_middle = None
    if "thumb" in chains:
        to_middle = (head(ref, 0) - head("thumb", 0)).normalized()
    out = {}
    for f, chain in chains.items():
        for j, name in enumerate(chain):
            b = B[name]
            d = (b.tail_local - b.head_local).normalized()
            target = palm
            if f == "thumb" and to_middle is not None:
                target = (palm * 0.55 + to_middle * 0.45).normalized()   # thumb folds across
            curl = d.cross(target)
            side = across * SPREAD_SIDE.get(f, 0.0)
            spread = d.cross(side) if side.length > 1e-6 else None
            inv = b.matrix_local.to_3x3().inverted()
            out[name] = ((inv @ curl).normalized() if curl.length > 1e-6 else None,
                         (inv @ spread).normalized() if spread is not None and spread.length > 1e-6 else None,
                         SPREAD_SIDE.get(f, 0.0) if j == 0 else 0.0)
    return out


class HandRig:
    """Precomputed finger chains and axes for one rig."""

    def __init__(self, rig):
        self.rig = rig
        self.fingers = find_fingers(rig)
        self.axes = {s: _axes(rig, ch) for s, ch in self.fingers.items()}

    def palm_local(self, side, hand_bone):
        """Palm normal of one hand in the given hand bone's rest space (None if unknown)."""
        if side not in self.fingers or hand_bone not in self.rig.data.bones:
            return None
        palm, _across = _palm_frame(self.rig, self.fingers[side])
        return (self.rig.data.bones[hand_bone].matrix_local.to_3x3().inverted() @ palm).normalized()

    @property
    def bones(self):
        return [b for s in self.fingers.values() for ch in s.values() for b in ch]

    def rotations(self, side, shape, weight=1.0):
        """{bone: bone-space Quaternion} for a shape name or a blended shape dict."""
        sh = SHAPES[shape] if isinstance(shape, str) else shape
        out = {}
        for f, chain in self.fingers.get(side, {}).items():
            curls = sh.get(f, (0, 0, 0))
            for j, name in enumerate(chain):
                curl_ax, spread_ax, spread_k = self.axes[side][name]
                q = Quaternion()
                if curl_ax is not None:
                    q = Quaternion(curl_ax, math.radians(curls[j] * weight)) @ q
                if spread_ax is not None and spread_k:
                    q = Quaternion(spread_ax, math.radians(abs(spread_k) * sh.get("spread", 0) * weight)) @ q
                out[name] = q
        return out

    def apply(self, side, shape, weight, base):
        """Set matrix_basis = base pose x shape rotation for every finger bone of a hand."""
        for name, q in self.rotations(side, shape, weight).items():
            pb = self.rig.pose.bones[name]
            pb.matrix_basis = base[name] @ q.to_matrix().to_4x4()


def blend_shapes(a, b, t):
    sa = SHAPES[a] if isinstance(a, str) else a
    sb = SHAPES[b] if isinstance(b, str) else b
    out = {f: tuple(x + (y - x) * t for x, y in zip(sa.get(f, (0, 0, 0)), sb.get(f, (0, 0, 0))))
           for f in FINGERS}
    out["spread"] = sa.get("spread", 0) + (sb.get("spread", 0) - sa.get("spread", 0)) * t
    return out


@command("set_hand_pose")
def set_hand_pose(character, shape="relaxed", side="both", strength=1.0, frame=None,
                  keyframe=False):
    """Pose the fingers of one or both hands with a named shape."""
    from .anim import _key_rot
    from .talk import _rig_of
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {sorted(SHAPES)}")
    rig = _rig_of(character)
    hands = HandRig(rig)
    if not hands.fingers:
        raise ValueError(f"{rig.name} has no recognised finger bones (mannequins have none)")
    sc = bpy.context.scene
    f = int(frame) if frame is not None else sc.frame_current
    sc.frame_set(f)
    sides = ("L", "R") if side == "both" else ({"left": "L", "right": "R", "L": "L", "R": "R"}[side],)
    prev = {}
    done = []
    for s in sides:
        if s not in hands.fingers:
            continue
        base = {b: Matrix.Identity(4) for ch in hands.fingers[s].values() for b in ch}
        for b in base:   # shapes are absolute from the rest pose (keep location)
            base[b] = Matrix.Translation(rig.pose.bones[b].location)
        hands.apply(s, shape, float(strength), base)
        for ch in hands.fingers[s].values():
            for b in ch:
                done.append(b)
                if keyframe:
                    _key_rot(rig.pose.bones[b], f, prev)
    bpy.context.view_layer.update()
    return {"character": rig.name, "shape": shape, "sides": list(sides), "frame": f,
            "keyed": bool(keyframe), "bones": len(done)}


@command("list_hand_shapes")
def list_hand_shapes():
    return {"shapes": sorted(SHAPES)}
