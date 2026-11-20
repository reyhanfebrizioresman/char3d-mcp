"""Deterministic collision maths; no Blender, IO, random state or physics cache.

Distances are meters, normals point out of the collider. Ellipsoid distances use
the closest surface point (including interior points on a principal plane).
"""
import math
import numpy as np


def unit(v, fallback=(1., 0., 0.)):
    v = np.asarray(v, dtype=float)
    length = float(np.linalg.norm(v))
    return v / length if length > 1e-10 else np.asarray(fallback, dtype=float)


def closest_segment(p, a, b):
    p, a, b = (np.asarray(v, dtype=float) for v in (p, a, b))
    d = b-a
    t = np.clip(np.sum((p-a)*d, axis=-1)/max(float(d@d), 1e-20), 0., 1.)
    return a + np.asarray(t)[..., None]*d


def segment_pair(a, b, c, d):
    """Exact finite segment pair, including parallel/point degeneracies."""
    a, b, c, d = (np.asarray(v, dtype=float) for v in (a, b, c, d))
    u, v, w = b-a, d-c, a-c
    aa, bb, cc, dd, ee = u@u, u@v, v@v, u@w, v@w
    if aa < 1e-20:
        return a, closest_segment(a, c, d)
    if cc < 1e-20:
        return closest_segment(c, a, b), c
    det = aa*cc-bb*bb
    s = np.clip((bb*ee-cc*dd)/det, 0., 1.) if det > 1e-20 else 0.
    t = (bb*s+ee)/cc
    if t < 0:
        t, s = 0., np.clip(-dd/aa, 0., 1.)
    elif t > 1:
        t, s = 1., np.clip((bb-dd)/aa, 0., 1.)
    return a+s*u, c+t*v


def capsule_distance(a, b, radius, c, d, other_radius):
    p, q = segment_pair(a, b, c, d)
    delta = p-q
    return float(np.linalg.norm(delta)-radius-other_radius), unit(delta)


def ellipsoid_distance(points, center, radii, axes=None):
    """Closest-point signed distances/normals, vectorized over query points.

    Solve the Lagrange multiplier by bisection. Interior principal-plane cases
    also test the stationary solution at the shortest axis pole.
    """
    points = np.atleast_2d(points).astype(float)
    axes = np.eye(3) if axes is None else np.asarray(axes)
    p = (points-np.asarray(center)) @ axes
    r = np.maximum(np.asarray(radii), 1e-8)
    rr = r*r
    inside = np.sum((p/r)**2, axis=1) < 1.
    lo = np.where(inside, -float(rr.min())+1e-14, 0.)
    hi = np.maximum(np.linalg.norm(p*r, axis=1), 1e-12)
    for _ in range(32):
        mid = (lo+hi)*.5
        value = np.sum((r*p/(rr+mid[:, None]))**2, axis=1)
        lo = np.where(value > 1., mid, lo)
        hi = np.where(value > 1., hi, mid)
    q = rr*p/(rr+hi[:, None])
    # If p has zero component on the shortest axis, the root may lie exactly
    # at that pole. This includes the center, where radial formulas fail.
    k = int(np.argmin(rr))
    shortest = np.abs(rr-rr[k]) < 1e-12
    special = inside & np.all(np.abs(p[:, shortest]) < 1e-8, axis=1)
    if special.any():
        rest = [j for j in range(3) if j != k]
        denom = rr[rest]-rr[k]
        candidate = np.zeros_like(p)
        candidate[:, rest] = np.divide(rr[rest]*p[:, rest], denom,
                                      out=np.zeros((len(p), 2)), where=denom > 1e-12)
        remaining = 1.-np.sum((candidate/r)**2, axis=1)
        candidate[:, k] = r[k]*np.sqrt(np.maximum(remaining, 0.))
        use = special & (remaining >= 0.)
        q[use] = candidate[use]
    delta = p-q
    distance = np.linalg.norm(delta, axis=1)*np.where(inside, -1., 1.)
    normal = q/rr
    normal /= np.maximum(np.linalg.norm(normal, axis=1)[:, None], 1e-12)
    return distance, normal @ axes.T


def surface_distance(point, nearest, normal, inside=False):
    """Convert BVH nearest-surface output to a signed metric and outward normal.

    `inside` must come from a closed-volume parity test, never an open mesh's
    face normal. Thus an open tabletop blocks both sides without infinite solids.
    """
    delta = np.asarray(point)-np.asarray(nearest)
    distance = float(np.linalg.norm(delta))
    outward = -unit(delta, normal) if inside else unit(delta, normal)
    return (-distance if inside else distance), outward


def two_bone(shoulder, target, upper, lower, pole):
    """Analytic joint and clamped endpoint matching seating._chain's reach."""
    shoulder, target = np.asarray(shoulder), np.asarray(target)
    axis = unit(target-shoulder, (0., 0., -1.))
    length = float(np.linalg.norm(target-shoulder))
    length = max(abs(upper-lower)+1e-4, min(length, (upper+lower)*.9995))
    pole = np.asarray(pole, dtype=float)
    perp = pole-axis*float(pole@axis)
    if np.linalg.norm(perp) < 1e-8:
        fallback = np.array((1.,0.,0.)) if abs(axis[0])<.8 else np.array((0.,1.,0.))
        perp = fallback-axis*float(fallback@axis)
    cosine = np.clip((upper*upper+length*length-lower*lower)/(2*upper*length), -1., 1.)
    joint = shoulder+upper*(axis*cosine+unit(perp)*math.sqrt(max(0., 1.-cosine*cosine)))
    return joint, shoulder+axis*length


def smooth_corrections(values, fps, locked=None):
    """Anticipatory quintic shoulders over .2 s, with zero slope at the edges.

    A largest-magnitude envelope anticipates a collision rather than averaging
    the required push below the surface. Locked contact frames remain exactly 0.
    Direction changes are lightly filtered, then projected onto each required
    correction half-space. No causal lag into a collider.
    """
    raw = np.asarray(values, dtype=float)
    if not len(raw):
        return raw.copy()
    width = max(1, round(.2*fps))
    out = raw.copy()
    magnitudes = np.linalg.norm(out, axis=1)
    for offset in range(-width, width+1):
        if not offset:
            continue
        t = 1.-abs(offset)/(width+1)
        weight = t*t*t*(t*(6*t-15)+10)
        for i in range(max(0, -offset), min(len(raw), len(raw)-offset)):
            candidate = raw[i+offset]*weight
            length = float(np.linalg.norm(candidate))
            if length > magnitudes[i]:
                out[i], magnitudes[i] = candidate, length
    norms = np.linalg.norm(raw,axis=1)
    normals = raw/np.maximum(norms[:,None],1e-12)
    for _ in range(6):
        padded=np.pad(out,((1,1),(0,0)),mode='edge')
        out=(padded[:-2]+2*padded[1:-1]+padded[2:])*.25
        deficit=np.maximum(0.,norms-np.sum(out*normals,axis=1))
        out+=normals*deficit[:,None]
        if locked is not None:
            out[np.asarray(locked,dtype=bool)]=0.
    if locked is not None:
        locked=np.asarray(locked,dtype=bool)
        # A protected contact is a hard endpoint with a smooth shoulder. Nearby
        # unsatisfied collisions must be reported, not hidden by a one-frame snap.
        distance=np.full(len(raw),len(raw),dtype=float)
        last=-len(raw)
        for i in range(len(raw)):
            if locked[i]:last=i
            distance[i]=i-last
        last=2*len(raw)
        for i in range(len(raw)-1,-1,-1):
            if locked[i]:last=i
            distance[i]=min(distance[i],last-i)
        t=np.minimum(1.,distance/(width+1))
        out*= (t*t*t*(t*(6*t-15)+10))[:,None]
        out[locked] = 0.
    return out


def bounded_correction(delta, maximum, locked=False):
    if not np.all(np.isfinite(delta)):
        return np.zeros(3), 'non-finite correction'
    if np.linalg.norm(delta) > maximum+1e-8:
        return np.zeros(3), 'correction exceeds displacement limit'
    if locked and np.linalg.norm(delta) > 1e-8:
        return np.zeros(3), 'intended contact target is protected'
    return np.asarray(delta), None


def split_bezier(points, x):
    """Split a monotone-time cubic exactly at a frame, preserving both halves."""
    p0,p1,p2,p3=(np.asarray(p,dtype=float) for p in points)
    lo,hi=0.,1.
    for _ in range(48):
        t=(lo+hi)*.5
        a,b,c=p0+(p1-p0)*t,p1+(p2-p1)*t,p2+(p3-p2)*t
        d,e=a+(b-a)*t,b+(c-b)*t
        point=d+(e-d)*t
        if point[0]<x:lo=t
        else:hi=t
    return a,c,d,e,point
