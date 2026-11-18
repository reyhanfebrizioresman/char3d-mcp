"""Small saved analytic animation recipes, without simulations or external assets."""
import math
from .core import Asset, Material, Mesh, area_size, integer, number, points3, rng


def falling_petals(area=(12,12),count=80,height=5.,seed=0,kind='petals'):
    """Looping petals or autumn leaves in centered XY, with saved whole-leaf pivots."""
    w,l=area_size(area);n=integer(count,'count',0,500);h=number(height,'height',.5,30)
    if kind not in ('petals','leaves'): raise ValueError('kind must be petals or leaves')
    random=rng(seed)
    mesh=Mesh(kind,materials=[Material(kind,(.88,.42,.48) if kind=='petals' else (.55,.23,.045))],
        occludes=False,motion=dict(kind='fall',height=h,seed=seed,amplitude=.22))
    for i in range(n):
        p=(random.uniform(-w/2,w/2),random.uniform(-l/2,l/2),random.uniform(.1,h))
        start=len(mesh.vertices)
        mesh.leaf(p,.045 if kind=='petals' else .10,.018,random.random()*math.tau,random.uniform(-1,1))
        mesh.pivots.extend([p]*(len(mesh.vertices)-start))
    return Asset('falling_'+kind,[mesh],dict(seed=seed,count=n))


def birds_flock(count=9,path=((-12,18,10),(12,25,13)),seed=0):
    """Small flock following a closed XYZ flight loop, with individual wing phases."""
    n=integer(count,'count',0,60);ps=points3(path);random=rng(seed)
    # The full path is consumed by the adapter's saved location keys. Each bird
    # has its own wing phase, while the flock takes the same continuous route.
    out=Asset('birds_flock',metadata=dict(seed=seed))
    for i in range(n):
        mesh=Mesh(f'bird_{i}',materials=[Material('bird',(.065,.085,.08))],occludes=False,
            motion=dict(kind='bird',path=ps,phase=random.random()*math.tau,seed=seed+i))
        dx,dy,dz=random.uniform(-2,2),random.uniform(-2,2),random.uniform(-.7,.7)
        mesh.vertices=[(dx-.04,dy-.17,dz),(dx+.04,dy-.17,dz),(dx,dy+.15,dz),
                       (dx-.28,dy+.03,dz+.03),(dx+.28,dy+.03,dz+.03)]
        mesh.faces=[(0,1,2),(0,2,3),(1,4,2)];mesh.indices=[0]*3
        out.parts.append(mesh)
    return out


def butterflies(area=(8,8),count=12,height=1.,seed=0):
    """Low drifting butterflies in centered XY; saved wingbeat and flight drivers."""
    w,l=area_size(area);n=integer(count,'count',0,80);h=number(height,'height',.1,5)
    random=rng(seed);out=Asset('butterflies',metadata=dict(seed=seed))
    for i in range(n):
        p=(random.uniform(-w/2,w/2),random.uniform(-l/2,l/2),h*random.uniform(.4,1))
        mesh=Mesh(f'butterfly_{i}',materials=[Material('butterfly',(.72,.36,.045))],occludes=False,
            motion=dict(kind='butterfly',phase=random.random()*math.tau,seed=seed+i))
        mesh.face(((0,0,0),(-.04,.035,.02),(-.065,-.03,.01)))
        mesh.face(((0,0,0),(.065,-.03,.01),(.04,.035,.02)))
        out.parts.append(Asset('butterfly',[mesh]).placed(p).parts[0])
    return out
