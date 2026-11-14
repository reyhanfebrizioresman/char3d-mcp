"""Humanoid joint landmarks: the shared language between character builders and riggers.

All coordinates are world space, meters, Z up, character faces -Y, so its LEFT side is +X.
Only ".L" landmarks are generated; ".R" are mirrored (x -> -x).
"""
import math

CENTER = ["hips", "waist", "chest", "upper_chest", "neck_base", "neck", "chin",
          "head_center", "head_top"]
SIDE = ["clavicle", "shoulder", "elbow", "wrist", "hand_tip",
        "hip", "knee", "ankle", "ball", "toe_tip", "heel"]

GENDER = {  # shoulder joint half-width, hip joint half-width (fractions of height)
    "male": (0.118, 0.082),
    "female": (0.100, 0.092),
    "neutral": (0.110, 0.087),
}

STYLES = {"realistic": 7.5, "heroic": 8.0, "stylized": 6.0, "cartoon": 4.5, "chibi": 3.0}


def mirror(lm):
    """Add .R landmarks mirrored from .L (keeps existing .R entries)."""
    out = dict(lm)
    for k, v in lm.items():
        if k.endswith(".L"):
            out.setdefault(k[:-2] + ".R", (-v[0], v[1], v[2]))
    return out


def human_landmarks(height=1.75, heads=7.5, gender="neutral", arm_angle=35.0, build=1.0):
    """Proportional joint positions for a standing character (A-pose by default).

    heads: total height in head units (7.5 realistic, 6 stylized, 3 chibi).
    arm_angle: degrees below horizontal (0 = T-pose, ~35-45 = A-pose).
    """
    if gender not in GENDER:
        raise ValueError(f"gender must be one of {sorted(GENDER)}")
    H = float(height)
    h = H / float(heads)
    C = H - h  # chin height; the body below the head is laid out in fractions of C
    sw, hw = GENDER[gender]
    sx = sw * H * (0.9 + 0.1 * build)
    hx = hw * H * (0.9 + 0.1 * build)

    L = {
        "hips": (0, 0.005 * H, 0.60 * C),
        "waist": (0, 0.0, 0.70 * C),
        "chest": (0, -0.004 * H, 0.80 * C),
        "upper_chest": (0, 0.0, 0.89 * C),
        "neck_base": (0, 0.006 * H, 0.955 * C),
        "neck": (0, 0.004 * H, 0.98 * C),
        "chin": (0, 0.0, C),
        "head_center": (0, 0.0, C + 0.5 * h),
        "head_top": (0, 0.0, H),
    }
    zs = 0.93 * C
    L["clavicle.L"] = (0.045 * H, -0.004 * H, zs + 0.012 * H)
    L["shoulder.L"] = (sx, 0.0, zs)
    a = math.radians(arm_angle)
    d = (math.cos(a), 0.0, -math.sin(a))
    ua, fa, hd = 0.215 * C, 0.17 * C, 0.125 * C

    def step(p, length, dy=0.0):
        return (p[0] + d[0] * length, p[1] + dy, p[2] + d[2] * length)

    L["elbow.L"] = step(L["shoulder.L"], ua, 0.012 * H)        # slight bend backwards
    L["wrist.L"] = step(L["elbow.L"], fa, -0.008 * H)
    L["hand_tip.L"] = step(L["wrist.L"], hd)

    L["hip.L"] = (hx, 0.0, 0.57 * C)
    L["knee.L"] = (hx * 0.95, -0.012 * H, 0.31 * C)                # slight bend forwards
    L["ankle.L"] = (hx * 0.92, 0.01 * H, 0.055 * C)
    L["ball.L"] = (hx * 0.92, -0.075 * H, 0.014 * H)
    L["toe_tip.L"] = (hx * 0.92, -0.112 * H, 0.009 * H)
    L["heel.L"] = (hx * 0.92, 0.035 * H, 0.004 * H)
    return mirror(L)


def as_tuples(lm):
    return {k: tuple(float(c) for c in v) for k, v in lm.items()}
