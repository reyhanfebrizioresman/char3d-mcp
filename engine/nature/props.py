"""Original, reusable outdoor dressing. These recipes remain Blender-free."""
import math
from .core import Asset, Material, Mesh, add, integer, number, rng


def _box(mesh, p, dims, mat=0):
    x,y,z=p;w,d,h=(v/2 for v in dims);k=len(mesh.vertices)
    mesh.vertices.extend((x+a*w,y+b*d,z+c*h) for a,b,c in
        ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)))
    mesh.faces.extend(tuple(k+i for i in f) for f in
        ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)))
    mesh.indices.extend([mat]*6)


def fence(length=5.,height=1.,seed=0):
    """Timber posts and two rails along local X; one continuous solid footprint."""
    length=number(length,'length',.5,100);h=number(height,'height',.2,3);rng(seed)
    m=Mesh('fence',materials=[Material('fence_wood',(.25,.13,.055))],solid=True)
    n=min(100,max(1,math.ceil(length/1.4)))
    for i in range(n+1):
        x=-length/2+length*i/n
        _box(m,(x,0,h/2),(.09,.09,h))
        m.tube((x,0,h),(x,0,h+.08),.065,0,sides=4)
    for z in (.35*h,.75*h): _box(m,(0,0,z),(length,.065,.09))
    return Asset('fence',[m],dict(seed=seed))


def lantern(height=1.7,seed=0):
    """Small timber post and warm practical lamp; no external lamp model."""
    h=number(height,'height',.3,5);rng(seed)
    m=Mesh('lantern_frame',materials=[Material('lantern_wood',(.13,.065,.025))],solid=True)
    m.tube((0,0,0),(0,0,h-.28),.035,sides=8)
    for z in (h-.35,h-.06): _box(m,(0,0,z),(.28,.28,.045))
    for x in (-.10,.10):
        for y in (-.10,.10): m.tube((x,y,h-.35),(x,y,h-.06),.012,sides=5)
    glow=Mesh('lantern_glow',materials=[Material('lantern_amber',(1,.51,.16),.5,emission=3)],occludes=False)
    _box(glow,(0,0,h-.20),(.16,.16,.23))
    return Asset('lantern',[m,glow],dict(seed=seed,
        lights=[dict(name='lantern_lamp',location=[0,0,h-.2],energy=40,color=[1,.65,.30])]))


def wooden_bridge(length=5.,width=1.8,height=.25,seed=0):
    """Gently arched plank deck along Y, with separate solid side rails.

    Deck tops are walkable. The default entrance is an 8cm step; arch height
    controls the middle, not the entrance. Put banks beneath both bridge ends.
    """
    l=number(length,'length',1,30);w=number(width,'width',.8,8)
    h=number(height,'height',0,2);random=rng(seed)
    deck=Mesh('bridge_deck',materials=[Material('bridge_wood',(.26,.14,.055),surface='wood')],walkable=True)
    n=min(120,max(4,math.ceil(l/.45)))
    rails=[]
    for i in range(n):
        u=(i+.5)/n;y=(u-.5)*l;z=h*math.sin(math.pi*u)**2
        # Touching planks keep the sampled walking surface continuous. Narrow
        # open seams would become false cliff edges in the 5cm route grid.
        _box(deck,(0,y,z+.04),(w,l/n,.08))
    for sign in (-1,1):
        rail=Mesh('bridge_rail',materials=deck.materials,solid=True)
        ps=[]
        for i in range(n+1):
            u=i/n;y=(u-.5)*l;z=h*math.sin(math.pi*u)**2
            if i%max(1,n//5)==0 or i==n:
                _box(rail,(sign*(w/2-.04),y,z+.48),(.07,.07,.96))
            ps.append((sign*(w/2-.04),y,z+.96))
        for a,b in zip(ps,ps[1:]): rail.tube(a,b,.035,sides=6)
        rails.append(rail)
    return Asset('wooden_bridge',[deck,*rails],dict(seed=seed))


def gazebo(width=3.2,height=2.8,seed=0):
    """Open timber shelter; separate posts keep the floor navigable."""
    w=number(width,'width',1.6,10);h=number(height,'height',2,8);rng(seed)
    wood=Material('gazebo_wood',(.24,.12,.045),surface='wood')
    floor=Mesh('gazebo_floor',materials=[wood],walkable=True)
    _box(floor,(0,0,.05),(w,w,.10))
    parts=[floor]
    for x in (-w*.42,w*.42):
        for y in (-w*.42,w*.42):
            post=Mesh('gazebo_post',materials=[wood],solid=True)
            _box(post,(x,y,(h-.5)/2),(.12,.12,h-.5));parts.append(post)
    roof=Mesh('gazebo_roof',materials=[Material('gazebo_roof',(.16,.12,.07))],solid=True)
    ps=[(-w*.6,-w*.6,h-.55),(w*.6,-w*.6,h-.55),(w*.6,w*.6,h-.55),(-w*.6,w*.6,h-.55)]
    for a,b in zip(ps,ps[1:]+ps[:1]): roof.face((a,b,(0,0,h)))
    parts.append(roof)
    return Asset('gazebo',parts,dict(seed=seed))


def village_house(width=4.,depth=3.4,height=3.,seed=0):
    """Original gabled timber/plaster village house, front -Y. General kampung cue,
    not a reconstruction of any named regional or sacred building tradition.
    """
    w=number(width,'width',2,15);d=number(depth,'depth',2,15);h=number(height,'height',2,8)
    random=rng(seed)
    plaster=Material('village_plaster',(.42+random.random()*.08,.34,.22))
    wood=Material('house_timber',(.22,.10,.035))
    body=Mesh('house_walls',materials=[plaster,wood],solid=True)
    _box(body,(0,0,h/2),(w,d,h))
    for x in (-w*.46,w*.46): _box(body,(x,-d/2-.03,h/2),(.12,.10,h),1)
    _box(body,(0,-d/2-.035,h*.34),(w*.20,.05,h*.68),1)
    windows=Mesh('house_windows',materials=[Material('house_window',(1,.56,.23),.6,emission=2.5)],occludes=False)
    for x in (-w*.30,w*.30):
        _box(body,(x,-d/2-.045,h*.61),(w*.22,.08,h*.32),1)
        _box(windows,(x,-d/2-.09,h*.61),(w*.17,.015,h*.25))
    roof=Mesh('house_roof',materials=[Material('clay_roof',(.27,.095,.045))],solid=True)
    for sign in (-1,1):
        face=((0,-d/2-.35,h+.82),(sign*(w/2+.35),-d/2-.35,h),
              (sign*(w/2+.35),d/2+.35,h),(0,d/2+.35,h+.82))
        roof.face(face if sign>0 else tuple(reversed(face)))
    return Asset('village_house',[body,windows,roof],dict(seed=seed,
        lights=[dict(name='house_lamp',location=[0,-d/2-.25,h*.6],energy=40,color=[1,.65,.30])]))


def fireflies(area=(8,8),count=60,height=1.3,night=True,seed=0):
    """Small emissive motes with deterministic saved flight; explicit night=False
    returns no motes rather than adding invisible daytime draw objects.
    """
    from .core import area_size
    w,l=area_size(area);n=integer(count,'count',0,500);h=number(height,'height',.2,10)
    if not isinstance(night,bool): raise ValueError('night must be boolean')
    random=rng(seed)
    m=Mesh('fireflies',materials=[Material('firefly_glow',(.55,1,.12),.7,emission=5)],
        occludes=False,motion=dict(kind='fireflies',seed=seed))
    for i in range(n if night else 0):
        p=(random.uniform(-w/2,w/2),random.uniform(-l/2,l/2),random.uniform(.15,h))
        m.blob(p,(.009,.009,.009),random,rings=2,sides=5)
    return Asset('fireflies',[m] if m.faces else [],dict(seed=seed,night=night))
