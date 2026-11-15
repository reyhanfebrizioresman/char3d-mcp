"""Timeline graphics shared by still previews and the video composition pass."""
import json
import math
import os

import blf
import bpy
import imbuf
import numpy as np

from . import command, subtitles

CONFIG_PROP = "char3d_graphics"
KINDS = ("crossfade", "fade_black", "fade_white", "dip_black", "fade_in", "fade_out")
STYLES = ("center", "lower_third", "corner")


def get_config(sc):
    return json.loads(sc.get(CONFIG_PROP, "[]"))


def _positive(value, label, zero=False):
    value = float(value)
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"{label} must be finite and {'nonnegative' if zero else 'positive'}")
    return value


def _color(value):
    if len(value) != 3 or any(not math.isfinite(float(c)) or not 0 <= float(c) <= 1 for c in value):
        raise ValueError("colors must contain three RGB values in 0..1")
    return [float(c) for c in value]


def _store(sc, item):
    items = get_config(sc)
    if not item.get("name"):
        prefix = item["type"]
        n = 1
        while any(g["name"] == f"{prefix}{n}" for g in items):
            n += 1
        item["name"] = f"{prefix}{n}"
    if item["name"] == "all":
        raise ValueError("'all' is reserved for remove_graphics")
    items = [g for g in items if g["name"] != item["name"]] + [item]
    # Resolve before saving: a failed replacement leaves the old config intact.
    resolve_transitions(sc, items)
    sc[CONFIG_PROP] = json.dumps(items)
    return item


def resolve_transitions(sc, items=None):
    """Validate against today's shot markers; inclusive scene-frame intervals and keys."""
    marks = sorted((m for m in sc.timeline_markers if m.camera), key=lambda m: m.frame)
    fps = sc.render.fps / (sc.render.fps_base or 1)
    out = []
    for g in get_config(sc) if items is None else items:
        if g["type"] != "transition":
            continue
        kind = g["kind"]
        n = max(3 if kind in ("fade_black", "fade_white", "dip_black") else 2,
                round(g["duration_s"] * fps))
        cut = g.get("at_frame")
        if kind in ("fade_in", "fade_out"):
            boundary = sc.frame_start if kind == "fade_in" else sc.frame_end
            if g.get("shot") or (cut is not None and cut != boundary):
                raise ValueError(f"{kind} must be at the scene {'start' if kind == 'fade_in' else 'end'}")
            a, b = (boundary, boundary + n - 1) if kind == "fade_in" else (boundary - n + 1, boundary)
            keys = [[a, 1], [b, 0]] if kind == "fade_in" else [[a, 0], [b, 1]]
        else:
            matches = ([i for i, m in enumerate(marks) if g["shot"] in (m.name, m.camera.name)]
                       if g.get("shot") else [i for i, m in enumerate(marks) if m.frame == cut])
            if len(matches) != 1 or matches[0] == 0:
                raise ValueError("transition needs the start frame or name of an incoming shot with a preceding shot")
            i = matches[0]
            incoming = marks[i]
            cut = incoming.frame
            a = cut if kind == "crossfade" else cut - n // 2
            b = a + n - 1
            limit = marks[i + 1].frame - 1 if i + 1 < len(marks) else sc.frame_end
            if a < marks[i - 1].frame or b > limit:
                raise ValueError("transition duration exceeds the adjacent shots")
            keys = [[a, 1], [b, 0]] if kind == "crossfade" else [[a, 0], [cut, 1], [b, 0]]
        if a < sc.frame_start or b > sc.frame_end:
            raise ValueError("transition duration exceeds the scene range")
        if any(a <= t["end"] and b >= t["start"] for t in out):
            raise ValueError("transition intervals must not overlap")
        t = dict(g, start=a, end=b, keys=keys)
        if kind == "crossfade":
            t["camera"] = marks[matches[0] - 1].camera.name
        out.append(t)
    return out


@command("add_transition")
def add_transition(at_frame=None, shot=None, kind="crossfade", duration_s=0.5, name=None):
    """Add/replace a transition; shot names the incoming shot. Fades use scene boundaries."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if at_frame is not None and shot is not None:
        raise ValueError("pass at_frame OR shot, not both")
    return _store(bpy.context.scene, dict(type="transition", name=name, kind=kind,
                  at_frame=int(at_frame) if at_frame is not None else None, shot=shot,
                  duration_s=_positive(duration_s, "duration_s")))


@command("add_title")
def add_title(text, subtitle=None, start_s=0.0, duration_s=3.0, style="center", name=None,
              size=1.0, color=(1, 1, 1), background_color=(0.025, 0.035, 0.055),
              background_opacity=0.7, animation=None, animation_s=0.3, font=None):
    """Add/replace a title or name/role bar. Times are seconds from the scene start."""
    if not str(text).strip():
        raise ValueError("text must not be empty")
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    animation = animation or ("fade" if style == "center" else "slide")
    if animation not in ("fade", "slide", "none"):
        raise ValueError("animation must be fade, slide or none")
    opacity = float(background_opacity)
    if not math.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError("background_opacity must be in 0..1")
    cfg = dict(type="title", name=name, text=str(text).strip(), subtitle=str(subtitle or "").strip(),
               start_s=_positive(start_s, "start_s", zero=True),
               duration_s=_positive(duration_s, "duration_s"), style=style,
               size=_positive(size, "size"), color=_color(color),
               background_color=_color(background_color), background_opacity=opacity,
               animation=animation, animation_s=_positive(animation_s, "animation_s", zero=True), font=font)
    subtitles._font_path(cfg)
    return _store(bpy.context.scene, cfg)


@command("list_graphics")
def list_graphics():
    """List saved titles/transitions (names can be reused to replace them)."""
    return {"graphics": get_config(bpy.context.scene)}


@command("remove_graphics")
def remove_graphics(name=None, all=False):
    """Remove one named graphic, or all graphics with all=True / name='all'."""
    sc = bpy.context.scene
    items = get_config(sc)
    if not all and name is None:
        raise ValueError("pass name or all=True")
    kept = [] if all or name == "all" else [g for g in items if g["name"] != name]
    sc[CONFIG_PROP] = json.dumps(kept)
    return {"removed": [g["name"] for g in items if g not in kept], "graphics": kept}


def title_timing(sc, g):
    fps = sc.render.fps / (sc.render.fps_base or 1)
    a = sc.frame_start + round(g["start_s"] * fps)
    b = a + max(2, round(g["duration_s"] * fps)) - 1
    ramp = min(round(g["animation_s"] * fps), (b - a) // 2)
    return a, b, ramp if g["animation"] != "none" else 0


def title_keys(sc, g, width):
    a, b, ramp = title_timing(sc, g)
    dx = -width * 0.08 if g["animation"] == "slide" else 0
    return ([[a, 0, dx], [a + ramp, 1, 0], [b - ramp, 1, 0], [b, 0, dx]]
            if ramp else [[a, 1, 0], [b, 1, 0]])


def draw_title(path, width, height, g):
    """Draw text with blf and a rectangular translucent backing with numpy pixels."""
    font = subtitles._font_id(subtitles._font_path(g)[0])
    ref = min(width, height)
    size = max(10, int(ref * (0.075 if g["style"] == "center" else 0.06) * g["size"]))
    lines = []
    for text, factor in ((g["text"], 1), (g["subtitle"], 0.65)):
        if not text:
            continue
        words = text.split()
        sz, space, widths, rows = subtitles._layout(font, words, max(8, int(size * factor)),
                                                  width * 0.8, 2, min_size=1)
        for row in rows:
            lines.append((" ".join(words[i] for i in row), sz,
                          sum(widths[i] for i in row) + space * (len(row) - 1)))
    pad = ref * 0.035
    block_h = sum(sz * 1.3 for _, sz, _ in lines)
    block_w = max(w for _, _, w in lines)
    left = (width - block_w) / 2 if g["style"] == "center" else width * 0.06 + pad
    bottom = ((height - block_h) / 2 if g["style"] == "center" else
              height * 0.12 + pad if g["style"] == "lower_third" else height * 0.92 - block_h - pad)
    ib = imbuf.new((int(width), int(height)))
    y = bottom + block_h
    with blf.bind_imbuf(font, ib, display_name="sRGB"):
        blf.color(font, *g["color"], 1)
        for text, sz, w in lines:
            y -= sz * 1.3
            blf.size(font, sz)
            x = (width - w) / 2 if g["style"] == "center" else left
            blf.position(font, x, y + sz * 0.18, 0)
            blf.draw_buffer(font, text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    imbuf.write(ib, filepath=path)
    img = bpy.data.images.load(path, check_existing=False)
    try:
        pixels = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
        text_pixels = pixels.reshape(height, width, 4)
        bg = np.zeros_like(text_pixels)
        x0, x1 = max(0, int(left - pad)), min(width, math.ceil(left + block_w + pad))
        y0, y1 = max(0, int(bottom - pad)), min(height, math.ceil(bottom + block_h + pad))
        bg[y0:y1, x0:x1, :3] = g["background_color"]
        bg[y0:y1, x0:x1, 3] = g["background_opacity"]
        blend_rgba(bg, text_pixels)
        img.pixels.foreach_set(bg.ravel())
        img.filepath_raw, img.file_format = path, "PNG"
        img.save()
    finally:
        bpy.data.images.remove(img)


def blend_rgba(base, over):
    """Straight-alpha over, including translucent backgrounds."""
    a, b = over[..., 3:4], base[..., 3:4]
    alpha = a + b * (1 - a)
    base[..., :3] = (over[..., :3] * a + base[..., :3] * b * (1 - a)) / np.maximum(alpha, 1e-8)
    base[..., 3:4] = alpha


def build(sc, width, height, start, end, out_dir):
    overlays = []
    for i, g in enumerate(get_config(sc)):
        if g["type"] != "title":
            continue
        a, b, _ = title_timing(sc, g)
        if b < start or a > end:
            continue
        path = os.path.join(out_dir, f"title_{i:04d}.png")
        draw_title(path, width, height, g)
        overlays.append(dict(path=path, start=max(a, start) - start + 1, end=min(b, end) - start + 1,
                             keys=[[f - start + 1, alpha, dx] for f, alpha, dx in title_keys(sc, g, width)]))
    transitions = []
    for t in resolve_transitions(sc):
        if t["end"] >= start and t["start"] <= end:
            transitions.append(dict(t, start=max(t["start"], start) - start + 1,
                                    end=min(t["end"], end) - start + 1,
                                    keys=[[f - start + 1, alpha] for f, alpha in t["keys"]]))
    return overlays, transitions


def overlay_png(base_path, sc, frame):
    """Show titles in scene-camera stills. Shot transitions are checked in draft video."""
    titles = [g for g in get_config(sc) if g["type"] == "title" and
              title_timing(sc, g)[0] <= frame <= title_timing(sc, g)[1]]
    if not titles:
        return False
    img = bpy.data.images.load(base_path, check_existing=False)
    tmp = base_path + ".title.png"
    try:
        w, h = img.size
        pixels = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
        base = pixels.reshape(h, w, 4)
        for g in titles:
            draw_title(tmp, w, h, g)
            title = bpy.data.images.load(tmp, check_existing=False)
            try:
                over = np.empty_like(pixels)
                title.pixels.foreach_get(over)
                over = over.reshape(h, w, 4)
                keys = title_keys(sc, g, w)
                alpha = np.interp(frame, [k[0] for k in keys], [k[1] for k in keys])
                dx = round(np.interp(frame, [k[0] for k in keys], [k[2] for k in keys]))
                over[..., 3] *= alpha
                if dx:
                    over = np.roll(over, dx, axis=1)
                    if dx < 0:
                        over[:, dx:] = 0
                    else:
                        over[:, :dx] = 0
                blend_rgba(base, over)
            finally:
                bpy.data.images.remove(title)
        img.pixels.foreach_set(base.ravel())
        img.filepath_raw, img.file_format = base_path, "PNG"
        img.save()
    finally:
        bpy.data.images.remove(img)
        if os.path.exists(tmp):
            os.remove(tmp)
    return True
