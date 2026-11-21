"""Pure shot-size helpers shared by camera code and offline tests (no bpy)."""
from .toon import PRESETS

CLOSE_CAPS = {"extreme_close_up": 0.36, "close_up": 0.5}


def head_framing(styles, size, frac_h, aim_frac, medium_frac=0.6):
    """Close sizes are framed in head units: a cartoon/chibi head is a much larger
    share of its stature, so body fractions would crop the chin of a close-up.
    Returns (visible height fraction, aim height fraction) of the subject bounds."""
    styles = set(styles)
    if size not in ("medium_close", "close_up", "extreme_close_up") or len(styles) != 1:
        return frac_h, aim_frac
    style = next(iter(styles))
    if style not in PRESETS:
        return frac_h, aim_frac
    k = PRESETS["realistic"]["heads"] / PRESETS[style]["heads"]
    if size == "medium_close":
        # Chest-up stays body-led; only part of the head enlargement applies.
        k = 1.0 + (k - 1.0) * 0.5
    # Keep the size ladder ordered: each close size stays tighter than the next wider one.
    frac = min(frac_h * k, CLOSE_CAPS.get(size, 0.92 * medium_frac))
    k = frac / frac_h
    return frac, 1.0 - (1.0 - aim_frac) * k
