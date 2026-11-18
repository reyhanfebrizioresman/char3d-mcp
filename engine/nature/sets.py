"""Outdoor sets using the public nature library and existing furniture builders.

Near details / midground groves / far silhouettes are fixed at build time. No
camera-triggered instancing, culling or LOD changes, so dialog cuts cannot pop.
"""
import math

from . import (birds_flock,bush,clouds,falling_petals,flowers,grass_field,hills,
               lake,mountains_backdrop,path,reeds,rice_paddies,river,rocks,sea,tree)
from .blender import realize, _material
from .core import Material, Asset, Mesh


def build_nature_set(b,preset,variant,density=1.):
    from ..commands.outdoor import _ground,_bench,_lamp,_umbrella
    b.root['c3d_nature_preset']=preset
    b.root['c3d_nature_density']=density
    variant %= 2147480000
    from .camera import coverage, weight
    import json
    bounds=coverage(b.root)
    b.root['c3d_nature_coverage']=json.dumps(bounds)
    # Ground palette is deliberately muted; faces, clothes and flowers carry accents.
    for name,c in dict(grass=(.13,.21,.065),sand=(.57,.45,.28),path=(.42,.37,.27)).items():
        b.materials[name]=_material(b,Material(name,c,surface='sand' if name=='sand' else 'grass'))
    def put(asset,loc=(0,0,0),rotation=0,scale=1):
        # Scenery stones can be buried slightly in the meadow. Their seat floor
        # remains the set's walking level rather than following the buried base.
        if loc[2]<0:
            for part in asset.parts:
                if part.seat: part.seat['floor']=-loc[2]/scale
        return realize(b,asset,loc,rotation,scale)
    sand=preset=='beach'
    # A continuous low floor is below the water. Separate shore banks never cover it.
    if sand:
        shore=Mesh('sand_bank',materials=[Material('sand',(.57,.45,.28),surface='sand')],walkable=True)
        edge=[(-180+i*360/180,6+.35*math.sin((-180+i*2)*.2)+.15*math.sin((-180+i*2)*.57),0) for i in range(181)]
        shore.face([(-180,-110,0),(180,-110,0),*reversed(edge)])
        for a,c in zip(edge,edge[1:]): shore.face((a,c,(c[0],c[1],-.20),(a[0],a[1],-.20)))
        put(Asset('shore',[shore]))
    else:
        _ground(b,'meadow',(0,0,-.05),(240,240,.10),'grass')
    points=((0,-80,0),(.1,1,0),(-.5,5,0))
    if preset not in ('beach','lakeside','riverside','rice_terraces'):
        points+=((1.2,12,0),(0,20,0))
    if not sand:
        put(path(points,2.7,'stone' if preset=='mountain_village' else 'gravel',variant))
    side=-1 if variant%2 else 1
    if sand:
        start=len(b.objects)
        b.prop('chair',(-side*2.7,1.3,0))
        seat=next(o for o in reversed(b.objects) if 'c3d_seat_centers' in o)
        seat['c3d_seat_kind']='deck_chair'
        for part in b.objects[start:]:
            if 'chair_back' in part.name:
                part.rotation_euler.x=math.radians(-15);part.location.y+=.07
    else:
        bench=_bench(b,-side*2.8,1.8)
        bench.data.materials[0]=b.materials['accent']
    def plant(kind,x,y,h,detail=1,season='summer'):
        return put(tree(kind,h,(variant+round(abs(x*31+y*73)))%2147483648,season,detail),(x,y,0),b.rng.uniform(0,360))
    def grove(kind='broadleaf',n=25,low=6,high=40,height=5):
        count=min(100,round(n*density))
        for i in range(count):
            x=b.rng.uniform(-30,30);y=b.rng.uniform(low,high)
            if bounds is not None and b.rng.random()>weight((x,y),bounds): continue
            # The whole near central corridor is kept free for blocking and cameras.
            if abs(x)<2.7 and y<13: x+=5 if x>=0 else -5
            detail=(.8 if weight((x,y),bounds)>.8 else .3) if bounds is not None else (.8 if y<14 else .35)
            plant(kind,x,y,height*b.rng.uniform(.8,1.35),detail)
    def meadow(x,y,w,l,seed,flower=True):
        put(grass_field((w,l),15*density,.38,(.12,.235,.045),seed),(x,y,0))
        if flower:
            put(flowers((w,l),density=1.1*density,height=.35,seed=seed+1),(x,y,0))
    for sign in (-1,1):
        if not sand:
            wet=preset in ('lakeside','riverside','rice_terraces')
            meadow(sign*5,1 if wet else 4,5.2,9 if wet else 13,variant+40+(sign+1)*11)
    if preset in ('park','blossom_garden','pine_forest','mountain_village'):
        put(grass_field((70,45),.9*density,.34,(.13,.23,.055),variant+90,
            exclude=[(0,y-23,1.8) for y in range(0,24,2)]),(0,23,0))
    if preset in ('park','blossom_garden'):
        grove('blossom' if preset=='blossom_garden' else 'broadleaf',42,height=5.2)
        for x,y,h in ((-4.7,3.8,5.2),(4.8,5.5,5.8),(-7,10,6.1),(8,12,6.5)):
            plant('blossom' if preset=='blossom_garden' else 'maple',x,y,h,season='spring')
        for sign in (-1,1):
            for j in range(5): put(bush(.8,variant+j+sign+3),(sign*(3.3+j*.38),7+j*2,-.06))
        put(falling_petals((14,17),round(90*density),6,variant,
            'petals' if preset=='blossom_garden' else 'leaves'),(0,6,0))
        _lamp(b,side*3.3,3.0)
    elif preset=='pine_forest':
        grove('pine',48,4,55,8)
        for x,y,h in ((-4.5,3,9),(5.5,5,10),(-7,8,11),(8,10,9)):
            plant('pine',x,y,h)
        for sign in (-1,1):
            put(rocks(10,(5,15),.65,variant+sign+2),(sign*5.5,8,-.06))
            # Broad fern-like blades among finer grasses.
            put(grass_field((5,14),1.8*density,.8,(.07,.18,.055),variant+sign+9),(sign*5.5,9,-.06))
        put(falling_petals((12,14),round(38*density),7,variant,'leaves'),(0,7,0))
    elif preset=='beach':
        put(sea(seed=variant),(0,6,0))
        for x,y,h in ((-4.5,4.5,3.5),(4.8,5,3.9),(-8,5.2,4.2),(10,5,4.4),(-14,5,4.5),(18,4.9,4.8)):
            plant('palm',x,y,h)
        for sign in (-1,1):
            put(grass_field((8,5),7*density,.44,(.25,.30,.09),variant+sign+5),(sign*7.5,1,0))
            put(rocks(4,(5,3),.65,variant+sign+8),(sign*7,4,0))
        # Foam is broken geometry following the shore, not stacked water planes.
        foam=b.material('foam',(.72,.78,.70))
        for i in range(100):
            x=b.rng.uniform(-80,80);y=6+b.rng.uniform(.25,1.0)
            b.box('shore_foam',(x,y,-.018),(b.rng.uniform(.15,.7),.018,.006),foam,0)['c3d_nature_occludes']=False
        _umbrella(b,-side*3.8,2.6)
        put(mountains_backdrop(2,(180,30),6,variant),(0,120,-.4))
    elif preset in ('lakeside','riverside'):
        # The near bank ends at y=6, leaving a real water surface and a distant bank.
        if preset=='lakeside': put(lake((48,25),variant),(0,19,.065))
        else: put(river(((-70,9,.045),(-22,10,.045),(0,11,.045),(22,8,.045),(70,12,.045)),7,variant))
        for sign in (-1,1):
            for x,y,h in ((sign*5,5,6),(sign*11,7,6.5),(sign*18,4,5)):
                plant('maple',x,y,h)
            put(reeds((12,1.8),4*density,1.1,variant+sign+2),(sign*11,7,-.06))
            put(rocks(5,(12,2.0),.75,variant+sign+3),(sign*11,6,-.04))
        grove('broadleaf',25,35,55,6)
        put(falling_petals((14,15),round(55*density),6,variant,'leaves'),(0,5,0))
        if preset=='riverside':
            for sign in (-1,1): _lamp(b,sign*3.4,3.2)
    elif preset=='rice_terraces':
        put(rice_paddies(7,(54,42),5.2,density=3*density,seed=variant),(-1,7,.12))
        for sign in (-1,1): plant('banana',sign*5.5,4.8,3.4)
        for x in (-25,-18,19,26): plant('palm',x,20,6.5,.5)
        grove('bamboo',10,35,55,7)
    elif preset=='mountain_village':
        grove('pine',25,15,55,8)
        for x,y,h in ((-5,5,6),(6,7,7),(-9,14,8)):
            plant('blossom',x,y,h,.7,season='spring')
        for x,y,s in ((-8,10,1),(8,12,1.15),(-14,18,.9),(15,23,1.1),(-5,27,.85)):
            _cottage(b,x,y,s)
        put(falling_petals((14,18),round(65*density),6,variant),(0,7,0))
        for sign in (-1,1): _lamp(b,sign*3.7,3.6)
    if preset!='beach':
        put(hills((70,35),4,.5,variant),(0,52,-.08))
        put(mountains_backdrop(3,(190,55),25 if preset!='mountain_village' else 34,variant),(0,65,-.3))
    put(clouds(.28,25,'wisps',variant))
    put(birds_flock(7,((-16,22,10),(0,27,11),(18,23,12),(1,34,13)),variant))
    if preset in ('riverside','mountain_village'):
        from .blender import install_night_fill
        install_night_fill(b.root,b)
    return dict(preset=preset,density=density,lod='fixed near/middle/far detail; no camera switching',
                generators='engine.nature',animation='saved analytic drivers and geometry nodes')


def _cottage(b,x,y,s):
    def box(name,loc,dims,mat,bevel=0):
        return b.box(name,(x+loc[0]*s,y+loc[1]*s,loc[2]*s),tuple(v*s for v in dims),mat,bevel)
    plaster=b.material('village_plaster',(.48,.37,.23))
    tile=b.material('roof_clay',(.22,.085,.035))
    box('cottage',(0,0,1.5),(4,3.4,3),plaster)
    for dx in (-1.9,1.9): box('timber_post',(dx,-1.72,1.5),(.12,.12,3.1),'wood')
    box('door',(0,-1.72,1),(.8,.05,2),'wood')
    for dx in (-1.2,1.2):
        box('window_frame',(dx,-1.74,1.85),(.85,.1,.9),'wood')
        box('window_lamp',(dx,-1.80,1.85),(.67,.015,.72),'bulb')
        box('window_mullion',(dx,-1.82,1.85),(.04,.03,.75),'wood')
    for sign in (-1,1):
        roof=box('roof',(sign*1.1,0,3.42),(2.5,4.2,.14),tile)
        roof.rotation_euler.y=sign*math.radians(24)
        for j in range(12):
            rib=box('roof_seam',(sign*1.1,-1.95+j*.35,3.51),(2.5,.028,.03),'wood')
            rib.rotation_euler.y=sign*math.radians(24)
    b.light('cottage_lamp',(x,y-1.9*s,1.8*s),(x,y-3,0),35*s*s,kind='POINT')
