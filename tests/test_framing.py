"""Offline close-shot framing contract for stylized proportions."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.framing import head_framing
from engine.toon import PRESETS

SIZES = {"medium": (0.6, 0.72), "medium_close": (0.42, 0.8), "close_up": (0.24, 0.9),
         "extreme_close_up": (0.14, 0.905)}


def main():
    for size, (frac, aim) in SIZES.items():
        assert head_framing({"realistic"}, size, frac, aim) == (frac, aim)
        assert head_framing({"anime", "chibi"}, size, frac, aim) == (frac, aim)
    for style, preset in PRESETS.items():
        heads = preset["heads"]
        order = [head_framing({style}, s, *SIZES[s])[0] for s in ("extreme_close_up", "close_up", "medium_close", "medium")]
        assert order == sorted(order) and len(set(order)) == 4, (style, order)
        frac, aim = head_framing({style}, "close_up", *SIZES["close_up"])
        # The chin (one head below the scalp) and some neck stay inside the frame.
        top_to_chin = 1.0 / heads
        bottom = aim - frac / 2
        assert bottom < 1.0 - top_to_chin * 1.15, (style, frac, aim)
        assert aim + frac / 2 > 1.0, (style, frac, aim)
    print("FRAMING UNIT OK")


if __name__ == "__main__":
    main()
