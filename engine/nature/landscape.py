"""Analytic hills, ridges, sedimentary rock, continuous paths and rippling water."""
import math
from .core import (Asset, Material, Mesh, add, area_size, color, integer, mul,
                   number, points3, rng, scatter)


def hills(area=(30,30), height=3., roughness=.5, seed=0):
    """Walkable 48×48 rolling height field, centered XY; roughness in 0..1."""
    w,l = area_size(area)
    h = number(height,'height',0,80)
    r = number(roughness,'roughness',0,1)
    random = rng(seed)
    phases = [random.random()*math.tau for _ in range(4)]
    mesh = Mesh('hills',materials=[Material('moss',(.16,.25,.08),surface='grass')],
                walkable=True,smooth=True)
    n = 48
    for j in range(n+1):
        y = (j/n-.5)*l
        for i in range(n+1):
            x = (i/n-.5)*w
            edge = math.sin(math.pi*i/n)*math.sin(math.pi*j/n)
            z = h*edge**2*(.5+.25*math.sin(x/w*7+phases[0])*math.cos(y/l*6+phases[1])+
                           r*.13*math.sin(x/w*23+phases[2])*math.cos(y/l*19+phases[3]))
            mesh.vertices.append((x,y,z))
            if i and j:
                k=j*(n+1)+i
                mesh.faces.append((k-n-2,k-n-1,k,k-1)); mesh.indices.append(0)
    return Asset('hills',[mesh],dict(seed=seed,area=(w,l),height=h))


def mountains_backdrop(layers=3, area=(130,65), height=24., seed=0):
    """One to six sloping ridge layers with distance palettes, extending along +Y."""
    layers = integer(layers,'layers',1,6)
    w,l = area_size(area)
    h = number(height,'height',1,150)
    random = rng(seed)
    out = Asset('mountains_backdrop',metadata=dict(seed=seed))
    for layer in range(layers):
        t = layer/max(1,layers-1)
        mat = Material('distant_ridge',(.095+t*.14,.18+t*.14,.19+t*.19))
        mesh = Mesh(f'ridge_{layer}',materials=[mat],occludes=False,smooth=True)
        phase = random.random()*math.tau
        for i in range(121):
            x=(i/120-.5)*w
            z=h*(.32+.09*layer+.25*math.sin(i*.12+phase)**2+
                 .16*math.sin(i*.29+phase)**2+.055*math.sin(i*.78+phase))
            y=layer*l/max(1,layers-1)+math.sin(i*.13+phase)*4
            # Sloping front and back, not camera-facing cardboard silhouettes.
            mesh.vertices.extend(((x,y-l*.18,-.5),(x,y,z),(x,y+l*.18,-.5)))
            if i:
                k=i*3
                mesh.faces.extend(((k-3,k,k+1,k-2),(k-2,k+1,k+2,k-1)))
                mesh.indices.extend((0,0))
        out.parts.append(mesh)
    return out


def rocks(count=6, area=(8,8), height=.7, seed=0):
    """Solid irregular boulders in centered XY; selected low rocks have level seats."""
    n = integer(count,'count',0,300)
    w,l=area_size(area)
    h=number(height,'height',.05,15)
    random=rng(seed)
    out=Asset('rocks',metadata=dict(seed=seed))
    for i in range(n):
        scale=(h*random.uniform(.6,1.5),h*random.uniform(.6,1),h*random.uniform(.4,.8))
        mesh=Mesh(f'rock_{i}',materials=[Material('slate',(.24,.27,.23)),
                  Material('rock_moss',(.17,.23,.075))],solid=True)
        p=(random.uniform(-w/2,w/2),random.uniform(-l/2,l/2),scale[2]*.65)
        mesh.blob(p,scale,random,rings=5,sides=11)
        for j,face in enumerate(mesh.faces):
            if sum(mesh.vertices[k][2] for k in face)/len(face)>p[2]+scale[2]*.4:
                mesh.indices[j]=1
        # A deliberately low, cut-front boulder supports the buttocks while
        # leaving the shins clear. One closed level cap avoids overlapping tops.
        # Keep the preceding RNG consumption, so other stones keep their seeds.
        if .55 <= h <= 1.2 and i == 0:
            top=min(.48,h*.8);n=11;rx=max(.43,min(.78,scale[0]*.85))
            mesh.vertices=[];mesh.faces=[];mesh.indices=[]
            for z,factor in ((0,.90),(top*.45,1.),(top,.86)):
                for j in range(n):
                    a=j*math.tau/n
                    mesh.vertices.append((p[0]+rx*math.cos(a)*factor,
                        p[1]+max(-.23,.34*math.sin(a)*factor),z))
            for ring in range(2):
                for j in range(n):
                    k=ring*n+j;q=ring*n+(j+1)%n
                    mesh.faces.append((k,q,q+n,k+n));mesh.indices.append(0)
            mesh.faces.extend((tuple(reversed(range(n))),tuple(range(2*n,3*n))))
            mesh.indices.extend((0,1))
            mesh.seat=dict(centers=[[p[0],p[1]-.04,top]],front=[0,-1,0],floor=0)
        out.parts.append(mesh)
    return out


def cliff(height=8., width=12., seed=0):
    """Faceted solid rock wall along X; put its base at the desired world height."""
    h=number(height,'height',.2,80)
    w=number(width,'width',.2,100)
    random=rng(seed)
    mesh=Mesh('cliff',materials=[Material('strata',(.27,.26,.20)),
        Material('strata_light',(.38,.36,.28)),Material('strata_moss',(.16,.23,.065))],solid=True)
    for j in range(12):
        z=j*h/12
        for i in range(24):
            x=(i/24-.5)*w
            depth=random.uniform(-.3,.3)+.25*math.sin(i*.7)
            mesh.face(((x,depth,z),(x+w/24,depth,z),(x+w/24,depth+.12,z+h/12),
                       (x,depth+.12,z+h/12)),2 if j==11 else j%2)
    return Asset('cliff',[mesh],dict(seed=seed))


def path(points=((0,-8,0),(0,8,0)), width=2., material='gravel', seed=0,crown=True):
    """Walkable ribbon with flush feathered edges and separate aggregate detail.

    crown=False gives a flat ribbon 6mm above the points (used by water ribbons).
    """
    ps=points3(points)
    w=number(width,'width',.1,20)
    if material not in ('gravel','earth','stone','wood'): raise ValueError('unknown path material')
    if not isinstance(crown,bool): raise ValueError('crown must be boolean')
    random=rng(seed)
    palette={'gravel':(.42,.37,.27),'earth':(.24,.15,.07),'stone':(.36,.37,.32),'wood':(.28,.14,.06)}
    mesh=Mesh('path',materials=[Material(material,palette[material],surface=material)],walkable=True)
    left,right=[],[]
    for i,p in enumerate(ps):
        a,b=ps[max(0,i-1)],ps[min(len(ps)-1,i+1)]
        dx,dy=b[0]-a[0],b[1]-a[1]
        length=math.hypot(dx,dy)
        if length<1e-6: raise ValueError('path points must differ in XY')
        # Bounded miter joins: no gaps or overlapping strips at corners.
        left.append((p[0]-dy/length*w/2,p[1]+dx/length*w/2,p[2]+.006))
        right.append((p[0]+dy/length*w/2,p[1]-dx/length*w/2,p[2]+.006))
        if i:
            if crown:
                def rails(k):
                    p=ps[k];a,b=left[k],right[k];lift=min(.006,w*.004)
                    return ((a[0],a[1],p[2]+.0002),((a[0]+p[0])/2,(a[1]+p[1])/2,p[2]+lift),
                            ((b[0]+p[0])/2,(b[1]+p[1])/2,p[2]+lift),(b[0],b[1],p[2]+.0002))
                a,b=rails(i-1),rails(i)
                for k in range(3): mesh.face((a[k],a[k+1],b[k+1],b[k]))
            else: mesh.face((left[i-1],right[i-1],right[i],left[i]))
    # Scattered aggregate is sub-centimeter relief, joined to one mesh.
    aggregate=Mesh('path_aggregate',materials=mesh.materials,occludes=False)
    for a,b in zip(ps,ps[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        for _ in range(min(1000,round(length*w*12))):
            t=random.random();side=random.uniform(-.45,.45)*w
            x=a[0]+dx*t-dy/length*side;y=a[1]+dy*t+dx/length*side
            z=a[2]+(b[2]-a[2])*t+.009;r=random.uniform(.008,.022)
            aggregate.face(((x-r,y-r,z),(x+r,y-r,z),(x,y+r,z+.004)))
    # Tiny relief is visual dressing, not a separate tread for whole-sole IK.
    return Asset('path',[mesh,aggregate],dict(seed=seed,faces_per_segment=3 if crown else 1))


def lake(shape=(14,9), seed=0):
    """Irregular ellipse-like opaque water, centered XY; surface starts at Z=-.025."""
    w,l=area_size(shape)
    random=rng(seed)
    phase=random.random()*math.tau
    mesh=Mesh('lake',materials=[Material('water',(.035,.19,.205),.17,.18,surface='water')],
              occludes=False,smooth=True,motion=dict(kind='water',amplitude=.012,seed=seed))
    n=96
    mesh.vertices.append((0,0,-.025))
    for i in range(n):
        a=i*math.tau/n;r=1+.07*math.sin(3*a+phase)+.04*math.sin(7*a-phase)
        mesh.vertices.append((math.cos(a)*w/2*r,math.sin(a)*l/2*r,-.025))
    for i in range(n): mesh.faces.append((0,i+1,(i+1)%n+1));mesh.indices.append(0)
    return Asset('lake',[mesh],dict(seed=seed,shape=(w,l)))


def river(points=((-10,10,-.03),(0,5,-.03),(10,7,-.03)),width=3.,seed=0,
          banks=False,bank_height=.12):
    """Flowing water ribbon; optional walkable banks for paths monotonic along Y.

    bank_height is measured above each input point, not the wave crest. Banks
    extend 150m sideways; supply monotonic Y points to keep their polygons simple.
    """
    ps=points3(points)
    if not isinstance(banks,bool): raise ValueError('banks must be boolean')
    bank_height=number(bank_height,'bank_height',.01,3)
    if banks and any(b[1]<=a[1] for a,b in zip(ps,ps[1:])):
        raise ValueError('river banks require increasing Y points')
    out=path(ps,width,'stone',seed,crown=False)
    out.kind='river'
    out.parts=out.parts[:1]
    m=out.parts[0]
    # Keep the ribbon only, without path aggregate, and use continuous surface.
    m.faces=m.faces[:len(ps)-1];m.indices=[0]*len(m.faces)
    m.vertices=m.vertices[:4*(len(ps)-1)]
    m.materials=[Material('river_water',(.035,.15,.17),.12,.25,surface='water')]
    m.name='river';m.walkable=False;m.occludes=False;m.smooth=True
    m.motion=dict(kind='water',amplitude=.018,seed=seed)
    if banks:
        left=[m.vertices[0]]+[m.vertices[4*i+3] for i in range(len(ps)-1)]
        right=[m.vertices[1]]+[m.vertices[4*i+2] for i in range(len(ps)-1)]
        for side,edge in ((-1,left),(1,right)):
            top=[(x,y,z-.006+bank_height) for x,y,z in edge]
            outer=side*150
            contour=[(outer,top[0][1],top[0][2]),*top,(outer,top[-1][1],top[-1][2])]
            if side>0: contour.reverse()
            bank=Mesh('river_bank',materials=[Material('riverbank_grass',(.13,.205,.065),surface='grass')],walkable=True)
            bank.face(contour)
            for a,b in zip(top,top[1:]):
                bank.face((a,b,(b[0],b[1],b[2]-.18),(a[0],a[1],a[2]-.18)))
            out.parts.append(bank)
    return out


def sea(area=(300,220),height=.08,seed=0):
    """Low-cost wave grid, centered X and extending +Y; height is wave amplitude."""
    w,l=area_size(area)
    amplitude=number(height,'height',0,.6)
    rng(seed)
    mesh=Mesh('sea',materials=[Material('sea_water',(.025,.22,.29),.20,.25,surface='water')],
        occludes=False,smooth=True,motion=dict(kind='water',amplitude=amplitude,seed=seed))
    for j in range(65):
        for i in range(97):
            x=(i/96-.5)*w;y=j/64*l+(.35*math.sin(x*.2)+.15*math.sin(x*.57))*(1-j/64)**4
            mesh.vertices.append((x,y,-.05+amplitude*.35*math.sin(x*.3+y*.8)))
            if i and j:
                k=j*97+i;mesh.faces.append((k-98,k-97,k,k-1));mesh.indices.append(0)
    return Asset('sea',[mesh],dict(seed=seed))


def waterfall(height=5.,width=1.2,seed=0):
    """Vertical animated water ribbons from Z=0 to height, plus a small spray skirt."""
    h=number(height,'height',.2,60);w=number(width,'width',.1,15)
    random=rng(seed)
    mesh=Mesh('waterfall',materials=[Material('falling_water',(.43,.68,.66),.21,.2,.12,surface='water')],
        occludes=False,motion=dict(kind='waterfall',amplitude=.08,seed=seed))
    for i in range(26):
        x=(i/25-.5)*w
        for j in range(24):
            z=h*j/24;y=.12*math.sin(j*.3+i*.2)
            mesh.face(((x,y,z),(x+w/38,y,z),(x+w/38,y+.02,z+h/24),(x,y+.02,z+h/24)),0)
    for i in range(16):
        a=i*math.tau/16
        mesh.leaf((random.uniform(-w/2,w/2),-.1,.04),.4,.06,a,0)
    return Asset('waterfall',[mesh],dict(seed=seed))


def clouds(cover=.4,height=35.,style='wisps',seed=0):
    """Cheap opaque lobes at nominal altitude; cover 0..1, wisps or cumulus."""
    cover=number(cover,'cover',0,1);h=number(height,'height',5,150)
    if style not in ('wisps','cumulus'): raise ValueError('style must be wisps or cumulus')
    random=rng(seed)
    mesh=Mesh('clouds',materials=[Material('cloud',(.72,.79,.80),1,emission=.20)],
              occludes=False,smooth=True)
    for i in range(round(cover*36)):
        p=(random.uniform(-100,100),random.uniform(20,140),h+random.uniform(-4,4))
        for j in range(5):
            mesh.blob(add(p,(j*2,random.uniform(-2,2),random.uniform(-.4,.4))),
                      (random.uniform(3,7),1.7,.5 if style=='wisps' else 2.3),random,rings=4,sides=10)
    return Asset('clouds',[mesh] if mesh.faces else [],dict(seed=seed))
