"""Deterministic normalized overlay rectangles (top-left origin), without Blender."""


def overlap(a, b, margin=0):
    return (min(a[2],b[2])+margin>max(a[0],b[0]) and
            min(a[3],b[3])+margin>max(a[1],b[1]))


def candidates(rect, movable=True):
    yield list(rect)
    if not movable:
        return
    height = rect[3]-rect[1]
    for center in (.94,.88,.80,.72,.60,.50,.40,.28,.20,.12,.06):
        top = min(max(.025,center-height/2),.975-height)
        yield [rect[0],top,rect[2],top+height]


def arrange(caption, titles, faces=(), caption_auto=True, title_auto=None):
    """Keep requested positions where possible; otherwise stack into free space.

    Never shrink text, hide it, alter timing, or place a rectangle beyond safe edges.
    A failed fit remains measurable rather than silently dropping an overlay.
    """
    title_auto = title_auto if title_auto is not None else [True]*len(titles)
    def outside(r):
        return not (.02<=r[0]<r[2]<=.98 and .02<=r[1]<r[3]<=.98)
    best = None
    for cap in candidates(caption,caption_auto) if caption else [None]:
        placed, cost = [], 0.
        if cap:
            cost += 1000*(outside(cap)+sum(overlap(cap,f,.012) for f in faces))
            cost += 3*abs(cap[1]-caption[1])
        for raw, movable in zip(titles,title_auto):
            obstacles = list(faces)+placed+([cap] if cap else [])
            options = list(candidates(raw,movable))
            chosen = min(options,key=lambda r:(1000*(outside(r)+sum(overlap(r,b,.015) for b in obstacles))+abs(r[1]-raw[1])))
            cost += 1000*(outside(chosen)+sum(overlap(chosen,b,.015) for b in obstacles))+abs(chosen[1]-raw[1])
            placed.append(chosen)
        if best is None or cost<best[0]:
            best = cost,cap,placed
    return dict(caption=best[1],titles=best[2],clear=best[0]<1000)
