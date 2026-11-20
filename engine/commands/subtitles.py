"""Subtitles / captions burned into rendered video.

Words come from the word times that lip_sync / lip_sync_audio store on face meshes
(``char3d_words``), or from explicit lines. They are grouped into caption chunks, each chunk
(and, with word highlighting, each spoken word inside it) is drawn with Blender's own font
engine (blf) into a transparent full-frame PNG, and render_video lays those PNGs over the
rendered movie in a second Video Sequencer pass (engine/compose_subtitles.py). No ffmpeg or
extra Python packages needed. render_frames(camera="scene") shows the captions too.
"""
import json
import math
import os
import re

import blf
import bpy
import imbuf

from . import command
from .semantic import PROP as WORDS_PROP

CONFIG_PROP = "char3d_subtitles"

STYLES = {
    # size: font px as a fraction of min(width, height); lines: max lines per caption
    "tiktok": dict(size=0.085, max_words=3, max_chars=18, lines=1, highlight=True, pop=True,
                   outline=0.11, position="lower_third", uppercase=False),
    "karaoke": dict(size=0.062, max_words=7, max_chars=34, lines=2, highlight=True, pop=False,
                    outline=0.09, position="bottom", uppercase=False),
    "classic": dict(size=0.055, max_words=14, max_chars=42, lines=2, highlight=False, pop=False,
                    outline=0.08, position="bottom", uppercase=False),
}
# vertical centre of the caption block as a fraction of the frame height (from the bottom)
POSITIONS = {"bottom": 0.12, "lower_third": 0.27, "center": 0.5, "top": 0.86}
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
    "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)
SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*$")
CLAUSE_END = re.compile(r"[,;:]+[\"')\]]*$")


# ---- configuration
def get_config(sc):
    try:
        cfg = json.loads(sc.get(CONFIG_PROP, ""))
    except (TypeError, ValueError):
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("enabled", True) else None


def _resolved_style(cfg):
    st = dict(STYLES[cfg.get("style", "tiktok")])
    for k in ("max_words", "position", "uppercase", "highlight", "min_hold", "hold", "max_cps"):
        if cfg.get(k) is not None:
            st[k] = cfg[k]
    st["size"] *= float(cfg.get("size", 1.0))
    return st


def _font_path(cfg):
    if cfg.get("font"):
        p = os.path.expanduser(cfg["font"])
        if not os.path.exists(p):
            raise FileNotFoundError(f"font not found: {p}")
        return p, False
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p, False
    bundled = bpy.utils.system_resource("DATAFILES", path="fonts")
    p = os.path.join(bundled, "Inter.woff2")
    return (p, True) if os.path.exists(p) else (None, True)   # True: thicken by double draw


def _font_id(path):
    if path is None:
        return 0
    # BLF deduplicates loads by path. Let it own the cache: font IDs cached in Python
    # become invalid when read_factory_settings / open_mainfile resets Blender's fonts.
    fid = blf.load(path)
    return fid if fid != -1 else 0


# ---- words
def scene_words(sc, cfg=None):
    """[(text, f0, f1)] for the subtitles: explicit lines or every stored lip-sync word."""
    cfg = cfg if cfg is not None else (get_config(sc) or {})
    if cfg.get("words"):
        return [(str(w[0]), float(w[1]), float(w[2])) for w in cfg["words"]]
    if cfg.get("lines"):
        return _line_words(cfg["lines"], sc)
    words = []
    for ob in sc.objects:
        if WORDS_PROP in ob:
            try:
                words += [(str(w[0]), float(w[1]), float(w[2])) for w in json.loads(ob[WORDS_PROP])]
            except (TypeError, ValueError, IndexError):
                continue
    words = [w for w in words if w[0].strip()]
    return sorted(words, key=lambda w: w[1])


def _line_words(lines, sc):
    """Explicit lines [{"text", "start", "end"} seconds | "start_frame"/"end_frame"]: words are
    spread over each line weighted by their length (marked as a forced break at the end)."""
    fps = sc.render.fps / (sc.render.fps_base or 1)
    out = []
    for ln in lines:
        text = str(ln.get("text", "")).strip()
        if not text:
            continue
        if "start_frame" in ln:
            a, b = float(ln["start_frame"]), float(ln.get("end_frame", ln["start_frame"] + 2 * fps))
        else:
            a = sc.frame_start + float(ln.get("start", 0)) * fps
            b = sc.frame_start + float(ln.get("end", float(ln.get("start", 0)) + 2)) * fps
        toks = text.split()
        total = sum(len(t) + 1 for t in toks)
        t = a
        for i, tok in enumerate(toks):
            d = (b - a) * (len(tok) + 1) / total
            out.append((tok + ("\n" if i == len(toks) - 1 else ""), t, t + d * 0.92))
            t += d
    return out


def chunk_words(words, fps, style):
    """Group words into caption chunks: [{"words": [(text, f0, f1)], "start", "end"}]."""
    max_words = int(style["max_words"])
    max_chars = int(style["max_chars"]) * int(style["lines"])
    chunks, cur = [], []

    def flush():
        if cur:
            chunks.append({"words": list(cur)})
            cur.clear()

    for w in words:
        if cur:
            prev = cur[-1][0]
            text_len = len(" ".join(x[0].strip() for x in cur + [w]))
            if (w[1] - cur[-1][2] > 0.6 * fps or prev.endswith("\n") or len(cur) >= max_words
                    or text_len > max_chars or SENTENCE_END.search(prev.strip())
                    or (CLAUSE_END.search(prev.strip()) and len(cur) >= max(2, max_words // 2))):
                flush()
        cur.append(w)
    flush()
    lead, hold = 1, round(style.get('hold', .3) * fps)
    min_len = round((0.45 if style["max_words"] <= 3 else 0.8) * fps)
    for i, c in enumerate(chunks):
        c["start"] = max(0, round(c["words"][0][1]) - lead)
        c["end"] = max(round(c["words"][-1][2]) + hold, c["start"] + min_len,
                       c["start"] + round(style.get('min_hold', 0)*fps),
                       c["start"] + round(len(' '.join(w[0] for w in c['words']))/style.get('max_cps', 100000)*fps))
    for i in range(len(chunks) - 1):
        nxt = chunks[i + 1]["start"]
        if chunks[i]["end"] > nxt or nxt - chunks[i]["end"] < round(0.25 * fps):
            chunks[i]["end"] = nxt
        chunks[i]["end"] = max(chunks[i]["end"], chunks[i]["start"] + 1)
    for c in chunks:
        c["words"] = [(x[0].replace("\n", "").strip(), x[1], x[2]) for x in c["words"]]
    return chunks


def caption_states(chunks, highlight):
    """[(frame_start, frame_end_exclusive, chunk_index, highlighted word index or None)]."""
    out = []
    for ci, c in enumerate(chunks):
        if not highlight:
            out.append((c["start"], c["end"], ci, None))
            continue
        ws = c["words"]
        for wi, w in enumerate(ws):
            a = c["start"] if wi == 0 else max(c["start"], round(w[1]))
            b = c["end"] if wi == len(ws) - 1 else max(a + 1, round(ws[wi + 1][1]))
            b = min(b, c["end"])
            if b > a:
                out.append((a, b, ci, wi))
    return out


# ---- drawing
def _layout(font, words, size, max_w, lines, min_size=10):
    """Wrap words into lines that fit max_w; shrink the font when they don't."""
    while True:
        blf.size(font, size)
        space = blf.dimensions(font, "a a")[0] - 2 * blf.dimensions(font, "a")[0]
        widths = [blf.dimensions(font, w)[0] for w in words]
        rows, cur, cur_w = [], [], 0.0
        for i, w in enumerate(widths):
            add = w if not cur else cur_w + space + w
            if cur and add > max_w:
                rows.append(cur)
                cur, cur_w = [i], w
            else:
                cur.append(i)
                cur_w = add
        if cur:
            rows.append(cur)
        fits = len(rows) <= lines and all(
            sum(widths[i] for i in r) + space * (len(r) - 1) <= max_w for r in rows)
        if fits or size <= min_size:
            return size, space, widths, rows
        size = max(min_size, int(size * 0.92))


def caption_layout(width, height, words, cfg, style):
    """Measured glyph/outline rectangle, shared by drawing and collision review."""
    font_path, thin = _font_path(cfg)
    font = _font_id(font_path)
    texts = [w.upper() if style.get("uppercase") else w for w in words]
    ref = min(width, height)
    size, space, widths, rows = _layout(font, texts, max(10, int(style["size"] * ref)),
                                        width * 0.86, int(style["lines"]))
    line_h = size * 1.22
    cy = height * style.get('center_y',POSITIONS.get(style["position"], 0.12))
    top = cy + (len(rows) * line_h) / 2 - size * 0.85      # baseline of the first row
    r_out = max(1.0, size * style["outline"])
    placed = []
    for li, row in enumerate(rows):
        row_w = sum(widths[i] for i in row) + space * (len(row) - 1)
        x = (width - row_w) / 2
        y = top - li * line_h
        for i in row:
            placed.append((i, x, y))
            x += widths[i] + space
    x0 = min(x for i,x,y in placed)-r_out
    x1 = max(x+widths[i] for i,x,y in placed)+r_out
    y0 = min(y for i,x,y in placed)-.30*size-r_out
    y1 = max(y for i,x,y in placed)+1.05*size+r_out
    return dict(font=font,thin=thin,texts=texts,size=size,r_out=r_out,placed=placed,cy=cy,
                box=[x0/width,1-y1/height,x1/width,1-y0/height])


def draw_caption(path, width, height, words, active, cfg, style):
    """Write one caption state as a transparent RGBA PNG of the full frame."""
    layout = caption_layout(width,height,words,cfg,style)
    font,thin,texts,size,r_out,placed,cy = [layout[k] for k in ('font','thin','texts','size','r_out','placed','cy')]
    color = tuple(cfg.get("color", (1.0, 1.0, 1.0)))[:3]
    hcolor = tuple(cfg.get("highlight_color", (1.0, 0.84, 0.1)))[:3]
    ib = imbuf.new((int(width), int(height)))
    steps = 16
    with blf.bind_imbuf(font, ib, display_name="sRGB"):
        blf.size(font, size)
        for i, x, y in placed:                       # soft drop shadow
            blf.color(font, 0, 0, 0, 0.35)
            blf.position(font, x + r_out * 0.35, y - r_out * 0.9, 0)
            blf.draw_buffer(font, texts[i])
        for i, x, y in placed:                       # outline
            blf.color(font, 0, 0, 0, 1)
            for k in range(steps):
                a = 2 * math.pi * k / steps
                blf.position(font, x + math.cos(a) * r_out, y + math.sin(a) * r_out, 0)
                blf.draw_buffer(font, texts[i])
        for i, x, y in placed:                       # fill
            c = hcolor if i == active else color
            blf.color(font, c[0], c[1], c[2], 1)
            for dx in ((0, 0.6) if thin else (0,)):
                blf.position(font, x + dx * size / 40, y, 0)
                blf.draw_buffer(font, texts[i])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    imbuf.write(ib, filepath=path)
    return {"origin": [0.5, cy / height],"box":layout['box']}


def build(sc, width, height, frame_start, frame_end, out_dir):
    """Caption overlays for frames [frame_start, frame_end]: list of dicts with path, start,
    end (frame numbers relative to frame_start, 1-based, end inclusive), pop, origin."""
    cfg = get_config(sc)
    if not cfg:
        return [], []
    style = _resolved_style(cfg)
    fps = sc.render.fps / (sc.render.fps_base or 1)
    chunks = chunk_words(scene_words(sc, cfg), fps, style)
    out = []
    from .screen_layout import boundaries,layout_at
    splits = boundaries(sc,frame_start,frame_end)
    for n, (a, b, ci, wi) in enumerate(caption_states(chunks, style["highlight"])):
        a2, b2 = max(a, frame_start), min(b - 1, frame_end)
        if b2 < a2:
            continue
        cuts = sorted({a2,b2+1,*[f for f in splits if a2<f<=b2]})
        for index,(left,right) in enumerate(zip(cuts,cuts[1:])):
            path = os.path.join(out_dir, f"cap_{n:04d}_{index:03d}.png")
            resolved = layout_at(sc,(left+right-1)//2,width,height)
            st = resolved['caption_style'] or style
            info = draw_caption(path,width,height,[w[0] for w in chunks[ci]['words']],wi,cfg,st)
            first = left==a and (wi in (None,0))
            out.append(dict(path=path,start=left-frame_start+1,end=right-frame_start,
                            pop=bool(style['pop'] and first),origin=info['origin']))
    return out, chunks


def state_at(sc, frame):
    """(chunk words, active index, cfg, style) shown at a frame, or None."""
    cfg = get_config(sc)
    if not cfg:
        return None
    style = _resolved_style(cfg)
    fps = sc.render.fps / (sc.render.fps_base or 1)
    chunks = chunk_words(scene_words(sc, cfg), fps, style)
    for a, b, ci, wi in caption_states(chunks, style["highlight"]):
        if a <= frame < b:
            return [w[0] for w in chunks[ci]["words"]], wi, cfg, style
    return None


def overlay_png(base_path, sc, frame):
    """Draw the caption shown at `frame` onto an existing PNG (render_frames previews)."""
    st = state_at(sc, frame)
    if st is None:
        return False
    import numpy as np
    img = bpy.data.images.load(base_path, check_existing=False)
    try:
        w, h = img.size
        tmp = base_path[:-4] + "_cap.png"
        from .screen_layout import layout_at
        style = layout_at(sc,frame,w,h)['caption_style'] or st[3]
        draw_caption(tmp, w, h, st[0], st[1], st[2], style)
        cap = bpy.data.images.load(tmp, check_existing=False)
        try:
            base = np.empty(w * h * 4, dtype=np.float32)
            over = np.empty(w * h * 4, dtype=np.float32)
            img.pixels.foreach_get(base)
            cap.pixels.foreach_get(over)
            base, over = base.reshape(-1, 4), over.reshape(-1, 4)
            a = over[:, 3:4]
            base[:, :3] = base[:, :3] * (1 - a) + over[:, :3] * a
            base[:, 3:4] = np.maximum(base[:, 3:4], a)
            img.pixels.foreach_set(base.ravel())
            img.filepath_raw = base_path
            img.file_format = "PNG"
            img.save()
        finally:
            bpy.data.images.remove(cap)
            try:
                os.remove(tmp)
            except OSError:
                pass
    finally:
        bpy.data.images.remove(img)
    return True


def _srt_time(sec):
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(path, chunks, fps, frame_start, frame_end):
    """Caption chunks as an .srt file (times relative to frame_start)."""
    n = 0
    lines = []
    for c in chunks:
        a, b = max(c["start"], frame_start), min(c["end"], frame_end + 1)
        if b <= a:
            continue
        n += 1
        lines += [str(n), f"{_srt_time((a - frame_start) / fps)} --> {_srt_time((b - frame_start) / fps)}",
                  " ".join(w[0] for w in c["words"]), ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return n


# ---- commands
@command("add_subtitles")
def add_subtitles(style="tiktok", lines=None, words=None, start_frame=None, position=None,
                  size=1.0, color=None, highlight_color=None, highlight=None, uppercase=None,
                  max_words=None, font=None, min_hold=None, hold=None, max_cps=None, avoid_overlap=True):
    """Turn on captions for render_video / render_frames(camera="scene")."""
    if style not in STYLES:
        raise ValueError(f"style must be one of {list(STYLES)}")
    if position is not None and position not in POSITIONS:
        raise ValueError(f"position must be one of {list(POSITIONS)}")
    for label, value, low, high in (('min_hold',min_hold,0,60),('hold',hold,0,10),('max_cps',max_cps,1,100)):
        if value is not None and (not math.isfinite(value) or not low<=value<=high):
            raise ValueError(label+' outside range')
    if max_words is not None and (type(max_words) is not int or not 1<=max_words<=100):
        raise ValueError('max_words must be 1..100')
    sc = bpy.context.scene
    fps = sc.render.fps / (sc.render.fps_base or 1)
    if words:            # transcript words in seconds (e.g. from transcribe_audio)
        s0 = float(start_frame if start_frame is not None else sc.frame_start)
        lines = None
        cfg_words = [[str(w["word"]), round(s0 + float(w["start"]) * fps, 2),
                      round(s0 + float(w["end"]) * fps, 2)] for w in words]
    else:
        cfg_words = None
    cfg = {"enabled": True, "style": style, "position": position, "size": float(size),
           "avoid_overlap": bool(avoid_overlap),
           "highlight": highlight, "uppercase": uppercase, "max_words": max_words,
           "font": font, "lines": lines, "min_hold": min_hold, "hold": hold, "max_cps": max_cps}
    if color is not None:
        cfg["color"] = [float(c) for c in color][:3]
    if highlight_color is not None:
        cfg["highlight_color"] = [float(c) for c in highlight_color][:3]
    if font:
        _font_path(cfg)
    if cfg_words:
        cfg["lines"] = None
        cfg["words"] = cfg_words
    sc[CONFIG_PROP] = json.dumps(cfg)
    st = _resolved_style(cfg)
    ws = [tuple(w) for w in cfg_words] if cfg_words else scene_words(sc, cfg)
    if not ws:
        del sc[CONFIG_PROP]
        raise RuntimeError("no words to caption: run lip_sync / lip_sync_audio first, or pass "
                           "lines=[{'text', 'start', 'end'}] or an audio file")
    chunks = chunk_words(ws, fps, st)
    return {"style": style, "position": st["position"], "words": len(ws),
            "captions": len(chunks), "font": os.path.basename(_font_path(cfg)[0] or "blender default"),
            "preview": [{"frames": [c["start"], c["end"]],
                         "text": " ".join(w[0] for w in c["words"])} for c in chunks[:8]]}


@command("remove_subtitles")
def remove_subtitles():
    sc = bpy.context.scene
    had = CONFIG_PROP in sc
    if had:
        del sc[CONFIG_PROP]
    return {"removed": had}
