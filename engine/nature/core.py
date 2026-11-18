"""Blender-free geometry recipes. Meters, Z up; no IO, globals or global RNG.

Generators return an Asset containing Mesh parts with semantic collision flags.
The Blender adapter is intentionally separate. Recipes are ordinary dataclasses;
dataclasses.asdict() makes them suitable for a future restricted scene composer.
"""
from dataclasses import dataclass, field
import math
import random


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be finite in {low}..{high}')
    return float(value)


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def rng(seed):
    return random.Random(integer(seed, 'seed', 0, 2147483647))


def area_size(area):
    if not isinstance(area, (tuple, list)) or len(area) != 2:
        raise ValueError('area must be [width, length] in meters')
    return tuple(number(v, 'area', .1, 400) for v in area)


def color(rgb):
    if not isinstance(rgb, (tuple, list)) or len(rgb) != 3:
        raise ValueError('color must be RGB')
    return tuple(number(v, 'RGB', 0, 1) for v in rgb)


def points3(points, minimum=2):
    if not isinstance(points, (tuple, list)) or not minimum <= len(points) <= 1000:
        raise ValueError(f'points must contain {minimum}..1000 XYZ points')
    out = []
    for p in points:
        if not isinstance(p, (tuple, list)) or len(p) != 3:
            raise ValueError('each point must contain XYZ')
        out.append(tuple(number(v, 'coordinate', -1000, 1000) for v in p))
    if any(math.dist(a, b) < 1e-5 for a, b in zip(out, out[1:])):
        raise ValueError('consecutive points must differ')
    return out


@dataclass
class Material:
    name: str
    color: tuple
    roughness: float = .8
    metallic: float = 0.
    emission: float = 0.
    surface: str = ''


@dataclass
class Mesh:
    name: str
    vertices: list = field(default_factory=list)
    faces: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    indices: list = field(default_factory=list)
    solid: bool = False
    occludes: bool = True
    walkable: bool = False
    smooth: bool = False
    motion: dict = field(default_factory=dict)
    seat: dict = field(default_factory=dict)
    pivots: list = field(default_factory=list)

    def face(self, vertices, mat=0):
        start = len(self.vertices)
        self.vertices.extend(tuple(p) for p in vertices)
        self.faces.append(tuple(range(start, len(self.vertices))))
        self.indices.append(mat)

    def tube(self, a, b, radius, tip=None, sides=7, mat=0):
        d = sub(b, a)
        length = math.sqrt(dot(d, d))
        if length < 1e-8:
            return
        z = mul(d, 1 / length)
        x = norm(cross(z, (0, 1, 0) if abs(z[1]) < .9 else (1, 0, 0)))
        y = cross(z, x)
        start = len(self.vertices)
        for p, r in ((a, radius), (b, radius if tip is None else tip)):
            for i in range(sides):
                theta = i * math.tau / sides
                self.vertices.append(add(p, add(mul(x, r * math.cos(theta)), mul(y, r * math.sin(theta)))))
        self.faces.extend((start + i, start + (i + 1) % sides,
                           start + sides + (i + 1) % sides, start + sides + i) for i in range(sides))
        self.faces.extend((tuple(start + i for i in reversed(range(sides))),
                           tuple(start + sides + i for i in range(sides))))
        self.indices.extend([mat] * (sides + 2))

    def leaf(self, p, length, width, angle, tilt, mat=0, maple=False):
        # A folded, opaque blade: no alpha overdraw and a readable curved silhouette.
        forward = (math.cos(angle)*math.cos(tilt), math.sin(angle)*math.cos(tilt), math.sin(tilt))
        side = (-math.sin(angle), math.cos(angle), 0)
        outline = [(0, 0), (.38, .75), (.65, 1), (1, 0), (.65, -1), (.38, -.75)]
        if maple:
            outline = [(0,0),(.2,.65),(.45,.45),(.55,1),(.65,.5),(1,0),(.65,-.5),(.55,-1),(.45,-.45),(.2,-.65)]
        center = add(p, add(mul(forward, length*.48), (0, 0, width*.16)))
        for i, (u, v) in enumerate(outline):
            q, r = outline[(i+1) % len(outline)]
            self.face((center, add(p, add(mul(forward, q*length), mul(side, r*width))),
                       add(p, add(mul(forward, u*length), mul(side, v*width)))), mat)

    def blob(self, p, scale, random, mat=0, rings=5, sides=11):
        # Irregular rings give rocks and cloud lobes authored contour detail.
        start = len(self.vertices)
        for j in range(rings+1):
            theta = .001 + (math.pi-.002)*j/rings
            for i in range(sides):
                a = i*math.tau/sides
                r = random.uniform(.87, 1.12)
                self.vertices.append(add(p, (scale[0]*math.sin(theta)*math.cos(a)*r,
                    scale[1]*math.sin(theta)*math.sin(a)*r, scale[2]*math.cos(theta)*r)))
        for j in range(rings):
            for i in range(sides):
                a, b = start+j*sides+i, start+j*sides+(i+1)%sides
                self.faces.append((a,a+sides,b+sides,b))
                self.indices.append(mat)


@dataclass
class Asset:
    kind: str
    parts: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def placed(self, location=(0,0,0), scale=1., rotation=0.):
        """Return a transformed copy without modifying the source recipe."""
        import copy
        out = copy.deepcopy(self)
        angle = math.radians(rotation)
        c, s = math.cos(angle), math.sin(angle)
        for part in out.parts:
            part.vertices = [(location[0]+scale*(x*c-y*s), location[1]+scale*(x*s+y*c),
                              location[2]+scale*z) for x,y,z in part.vertices]
            part.pivots = [(location[0]+scale*(x*c-y*s), location[1]+scale*(x*s+y*c),
                            location[2]+scale*z) for x,y,z in part.pivots]
            # The adapter creates motion before placing parts; placed() is chiefly
            # useful for static composition. Motion uses transformed rest positions.
        return out


def add(a,b): return tuple(x+y for x,y in zip(a,b))
def sub(a,b): return tuple(x-y for x,y in zip(a,b))
def mul(a,s): return tuple(x*s for x in a)
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def norm(a): return mul(a, 1/max(math.sqrt(dot(a,a)),1e-12))


def scatter(area, density, seed, limit=18000, exclude=()):
    """Jittered stratification with a stable prefix as density increases.

    exclude contains local XY circles (x,y,r). No camera-dependent geometry/LOD.
    """
    width, length = area_size(area)
    density = number(density, 'density', 0, 200)
    count = min(limit, round(width*length*density))
    random = rng(seed)
    # Irrational rotations avoid rows, tile repetition, and density-dependent seeds.
    shift = random.random(), random.random()
    out = []
    for i in range(count):
        x = (((i*.754877666 + shift[0]) % 1)-.5)*width
        y = (((i*.569840296 + shift[1]) % 1)-.5)*length
        if not any((x-a)**2+(y-b)**2 < r*r for a,b,r in exclude):
            out.append((x,y,random.random(),random.random()))
    return out


def lod_weight(point,bounds):
    """Static camera-union density/detail falloff; no scene or frame dependency."""
    if bounds is None: return 1.
    x,y=point[:2]
    distance=max(bounds[0]-x,x-bounds[2],bounds[1]-y,y-bounds[3],0)
    return 1-.65*min(1.,distance/8)
