"""Original branching trees, folded leaf blades, meadow and agricultural geometry."""
import math
from .core import (Asset, Material, Mesh, add, mul, number, integer, rng,
                   area_size, color as rgb_color, scatter)

TREE_KINDS = ('broadleaf','pine','palm','blossom','maple','banana','bamboo','dead')
SEASONS = ('spring','summer','autumn','dry','wet','winter')


def _season(value):
    if value not in SEASONS: raise ValueError(f'season must be one of {SEASONS}')
    return value


def _seasonal_color(value,default,season):
    c=rgb_color(value);_season(season)
    if c!=default or season=='summer': return c
    return {'spring':(.20,.36,.075),'autumn':(.38,.29,.085),
            'dry':(.36,.28,.09),'wet':(.07,.26,.065),'winter':(.32,.36,.28)}[season]


def tree(kind='broadleaf', height=5., seed=0, season='summer', detail=1.):
    """Two meshes: solid branching wood + non-solid opaque individual foliage.

    detail .25..1 is fixed at build time (never camera-switches). All trees share
    the same conventions; winter broadleaf/maple is bare, pine stays evergreen.
    """
    if kind not in TREE_KINDS: raise ValueError(f'kind must be one of {TREE_KINDS}')
    if season not in SEASONS: raise ValueError(f'season must be one of {SEASONS}')
    h = number(height,'height',.3,40)
    detail = number(detail,'detail',.25,1)
    random = rng(seed)
    wood = Mesh('trunk',materials=[Material('bark',(.16,.075,.032))],solid=True,smooth=True)
    palette = [( .055,.15,.042),(.105,.255,.055),(.23,.37,.075),(.32,.43,.12)]
    if season == 'spring': palette = [(.12,.26,.055),(.26,.41,.09),(.39,.52,.15),(.19,.35,.08)]
    if season == 'dry': palette = [(.23,.22,.055),(.34,.30,.075),(.43,.36,.12),(.18,.23,.06)]
    if season == 'wet': palette = [(.035,.16,.045),(.07,.24,.065),(.16,.32,.07),(.22,.39,.10)]
    if season == 'autumn' and kind not in ('pine','palm','banana','bamboo'):
        palette = [(.43,.075,.018),(.67,.20,.025),(.80,.38,.05),(.35,.10,.022)]
    if kind == 'blossom':
        # Folded petal tufts carry canopy color at distance; resolved five-petal
        # flowers supply the near detail. A few green shoots break up the mass.
        palette=[(.66,.22,.34),(.90,.46,.57),(.98,.70,.72),(.16,.30,.065)]
    leaf = Mesh('foliage',materials=[Material(f'leaf{i}',c) for i,c in enumerate(palette)],
                smooth=False,motion=dict(kind='sway',height=h,amplitude=.045*h,seed=seed))
    flower = Mesh('blossoms',materials=[Material('blossom_rose',(.75,.23,.34)),
        Material('blossom_blush',(.95,.58,.64)),Material('blossom_cream',(1,.82,.78))],
        motion=dict(kind='sway',height=h,amplitude=.045*h,seed=seed))
    if kind == 'bamboo':
        for stem in range(7):
            x,y = random.uniform(-.17,.17)*h,random.uniform(-.17,.17)*h
            top = h*random.uniform(.65,1)
            for j in range(9):
                z = top*j/9
                wood.tube((x,y,z),(x+.02*h,y, z+top/9),.012*h,sides=8)
                wood.tube((x,y,z+.012*h),(x,y,z+.022*h),.015*h,sides=8)
                if j > 2:
                    for k in range(round(9*detail)):
                        a = random.uniform(0,math.tau)
                        p = (x+.13*h*math.cos(a),y+.13*h*math.sin(a),z)
                        leaf.leaf(p,h*.12,h*.009,a,random.uniform(-.4,.4),k%4)
    elif kind in ('palm','banana'):
        points = [(h*.06*(j/9)**2,0,h*j/9) for j in range(10)]
        for j,(a,b) in enumerate(zip(points,points[1:])):
            wood.tube(a,b,h*(.028-.013*j/9),sides=10)
            if kind == 'palm': wood.tube(a,add(a,(0,0,h*.012)),h*(.031-.013*j/9),sides=10)
        for j in range(11 if kind == 'palm' else 8):
            a = j*2.39996 + random.uniform(-.15,.15)
            length = h*random.uniform(.40,.57)
            base = points[-1]
            for k in range(10):
                u = k/10
                p = add(base,(length*u*math.cos(a),length*u*math.sin(a),h*(.22*u-.40*u*u)))
                q = add(base,(length*(u+.1)*math.cos(a),length*(u+.1)*math.sin(a),h*(.22*(u+.1)-.40*(u+.1)**2)))
                wood.tube(p,q,h*.003*(1-u)+.001,sides=5)
                for side in (-1,1):
                    leaf.leaf(p,length*.22*(math.sin(math.pi*u)**.5+.12),
                              length*(.035 if kind == 'palm' else .09),a+side*1.05,-.25,k%4)
    elif kind == 'pine':
        wood.tube((0,0,0),(0,0,h),h*.035,h*.003,sides=9)
        for j in range(9):
            z = h*(.22+j*.079)
            radius = h*.32*(1-j/10)
            for k in range(7):
                a = k*math.tau/7+j*1.1
                tip = (math.cos(a)*radius,math.sin(a)*radius,z-h*.05)
                wood.tube((0,0,z+.05*h),tip,h*.007*(1-j/11),.002,sides=5)
                for n in range(round(19*detail)):
                    u = random.random()
                    p = (tip[0]*u,tip[1]*u,z + random.uniform(-.055,.055)*h)
                    leaf.leaf(p,h*.17*(1-j/12),h*.025,a+random.uniform(-1,1),.08,n%4)
    else:
        wood.tube((0,0,0),(h*.02,0,h*.52),h*.045,h*.018,sides=10)
        terminals = []
        def branch(base,length,angle,radius,depth):
            tilt = random.uniform(.48,1.05)
            tip = add(base,(math.cos(angle)*length*math.cos(tilt),
                math.sin(angle)*length*math.cos(tilt),length*math.sin(tilt)))
            middle = tuple(a*.45+b*.55 for a,b in zip(base,tip))
            wood.tube(base,middle,radius,radius*.65,sides=7)
            wood.tube(middle,tip,radius*.65,radius*.30,sides=6)
            if depth:
                for k in range(3):
                    branch(tip,length*random.uniform(.52,.72),angle+(k-1)*1.2,
                           radius*.48,depth-1)
            else: terminals.append(tip)
        for j in range(7):
            branch((h*.015,0,h*(.32+j*.055)),h*random.uniform(.25,.36),j*2.39996,h*.016,2)
        if kind != 'dead' and not (season == 'winter' and kind in ('broadleaf','maple','blossom')):
            for tip in terminals:
                for n in range(round((15 if kind == 'blossom' else 30)*detail)):
                    a = random.uniform(0,math.tau)
                    r = h*random.uniform(.005,.105)
                    p = add(tip,(r*math.cos(a),r*math.sin(a),random.uniform(-.065,.065)*h))
                    lod_size=detail**-.45
                    leaf.leaf(p,h*random.uniform(.055,.105)*lod_size,h*.025*lod_size,a,
                              random.uniform(-.6,.9),random.randrange(4),kind=='maple')
                if kind == 'blossom' and season != 'winter':
                    for n in range(round(10*detail)):
                        p = add(tip,tuple(random.uniform(-.065,.065)*h for _ in range(3)))
                        _flower(flower,p,h*.024*detail**-.45,random,random.randrange(3),5)
    for part in (wood,leaf,flower):
        part.motion=dict(kind='sway',height=h,base=0,amplitude=.025*h,seed=seed)
    parts = [p for p in (wood,leaf,flower) if p.faces]
    return Asset('tree',parts,dict(kind=kind,height=h,seed=seed,season=season,detail=detail))


def _flower(mesh,p,r,random,mat=0,petals=5):
    a0 = random.random()*math.tau
    for i in range(petals):
        a = a0+i*math.tau/petals
        q = add(p,(r*.5*math.cos(a),r*.5*math.sin(a),r*.12))
        tilt=random.uniform(-.1,.25)
        forward=(math.cos(a),math.sin(a),tilt)
        side=(-math.sin(a),math.cos(a),0)
        # Five shared contour vertices replace six disconnected leaf triangles.
        # At blossom scale the silhouette carries the detail, not inner folds.
        mesh.face([add(q,add(mul(forward,u*r),add(mul(side,v*r),(0,0,z*r))))
                   for u,v,z in ((0,0,0),(.5,-.4,.12),(1,-.15,0),(1,.15,0),(.5,.4,.12))],mat)


def bush(height=.8, seed=0, color=(.13,.26,.06), detail=1., season='summer'):
    """Rounded twig/leaf shrub at the origin; solid footprint and camera occluder."""
    h = number(height,'height',.1,5)
    detail = number(detail,'detail',.25,1)
    random = rng(seed)
    color = _seasonal_color(color,(.13,.26,.06),season)
    leaves = Mesh('bush',materials=[Material('bush_leaf',color),
        Material('bush_tips',tuple(min(1,c*1.4) for c in color))],solid=True,
        motion=dict(kind='sway',height=h,amplitude=h*.045,seed=seed))
    for i in range(round(270*detail)):
        a = random.random()*math.tau
        z = random.uniform(.08,1)*h
        r = math.sqrt(max(0,1-(z/h-.4)**2))*h*random.uniform(.25,.7)
        p = (math.cos(a)*r,math.sin(a)*r*.75,z)
        leaves.leaf(p,h*.19,h*.045,a,random.uniform(-.2,.8),i%2)
    return Asset('bush',[leaves],dict(seed=seed))


def grass_field(area=(10,10), density=8., height=.3, color=(.15,.29,.055), seed=0, exclude=(), season='summer'):
    """Rooted blade clumps/m² in a centered XY rectangle; exclude XY circles.

    Hard cap 18,000 clumps. Thin cover never blocks walking or camera probes.
    """
    size = area_size(area)
    h = number(height,'height',.02,2.)
    c = _seasonal_color(color,(.15,.29,.055),season)
    random = rng(seed)
    mesh = Mesh('grass',materials=[Material('grass',c),Material('grass_tip',tuple(min(1,x*1.6) for x in c))],
        occludes=False,motion=dict(kind='sway',height=h,amplitude=h*.20,seed=seed))
    for x,y,u,v in scatter(size,density,seed,exclude=exclude):
        for k in range(4):
            angle = u*math.tau+k*2.39996
            blade_h = h*(.35+v*.85)*random.uniform(.6,1)
            side = (-math.sin(angle)*h*.025,math.cos(angle)*h*.025,0)
            base = (x,y,0)
            mid = (x+math.cos(angle)*h*.10,y+math.sin(angle)*h*.10,blade_h*.62)
            top = (x+math.cos(angle)*h*.30,y+math.sin(angle)*h*.30,blade_h)
            mesh.face((add(base,side),add(base,mul(side,-1)),add(mid,mul(side,-.6)),add(mid,mul(side,.6))),k%2)
            mesh.face((add(mid,mul(side,.6)),add(mid,mul(side,-.6)),top),k%2)
    return Asset('grass_field',[mesh],dict(seed=seed,area=size,density=density))


def flowers(area=(6,6), palette=((.78,.35,.15),(.92,.73,.38),(.62,.26,.43)), density=2., height=.4, seed=0, exclude=(), season='summer'):
    """Stemmed five-petal flowers/m², centered XY; cap 3,000, absent in winter."""
    size = area_size(area)
    h = number(height,'height',.05,2)
    if not isinstance(palette,(list,tuple)) or not 1 <= len(palette) <= 8:
        raise ValueError('palette must contain 1..8 RGB colors')
    colors = [rgb_color(c) for c in palette]
    random = rng(seed)
    _season(season)
    if season=='winter': density=0
    mesh = Mesh('flowers',materials=[Material(f'petals{i}',c) for i,c in enumerate(colors)]+[
        Material('flower_stem',(.09,.20,.035)),Material('pollen',(.76,.44,.045))],occludes=False,
        motion=dict(kind='sway',height=h,amplitude=h*.11,seed=seed))
    for x,y,u,v in scatter(size,density,seed,limit=3000,exclude=exclude):
        top = (x+h*.10*math.cos(u*math.tau),y,h*(.55+v*.6))
        mesh.tube((x,y,0),top,.003, sides=4,mat=len(colors))
        mesh.leaf((x,y,h*.4),h*.25,h*.07,u*math.tau,.3,len(colors))
        _flower(mesh,top,h*.11,random,random.randrange(len(colors)),6)
        mesh.face([add(top,(math.cos(i*math.tau/6)*h*.026,math.sin(i*math.tau/6)*h*.026,.008)) for i in range(6)],len(colors)+1)
    return Asset('flowers',[mesh],dict(seed=seed,area=size))


def hedge(length=4., height=1., seed=0, season='summer'):
    """Solid row of overlapping shrubs along local X, centered at the origin."""
    length = number(length,'length',.2,100)
    h = number(height,'height',.1,5)
    rng(seed)
    out = Asset('hedge')
    for i in range(min(160,max(1,math.ceil(length/h)))):
        out.parts.extend(bush(h,(seed+i)%2147483648,season=season).placed((i*h-length/2,0,0)).parts)
    return out


def reeds(area=(8,2), density=5., height=1.2, seed=0, season='summer'):
    """Rooted reeds and seed heads in a centered rectangle; nonblocking cover."""
    h = number(height,'height',.1,4)
    _season(season)
    reed_color=(.22,.32,.075) if season in ('summer','spring','wet') else (.38,.30,.13)
    out = grass_field(area,density,h,reed_color,seed,season=season)
    random = rng(seed)
    stalk = Mesh('reed_heads',materials=[Material('reed_head',(.21,.09,.025))],occludes=False,
                 motion=dict(kind='sway',height=h,amplitude=h*.15,seed=seed))
    for x,y,u,v in scatter(area,density*.25,seed,limit=2000):
        z = h*(.7+v*.3)
        stalk.tube((x,y,0),(x,y,z),.009,sides=5)
        stalk.tube((x,y,z),(x,y,z+h*.13),h*.018,sides=6)
    out.parts.append(stalk)
    out.kind = 'reeds'
    return out


def rice_paddies(terraces=5, area=(30,28), height=3., density=4., seed=0, season='summer'):
    """Curved flooded beds and earthen banks. Banks are tagged walkable.

    Terraces are scenery: rises > .25m block walking. Use add_terrain stairs for
    access between large levels; the acting area remains outside the paddies.
    """
    n = integer(terraces,'terraces',1,16)
    w,l = area_size(area)
    h = number(height,'height',0,20)
    density = number(density,'density',0,40)
    rng(seed)
    _season(season)
    out = Asset('rice_paddies',metadata=dict(seed=seed,terraces=n))
    bank = Mesh('terrace_banks',materials=[Material('earth',(.20,.16,.065),surface='grass')],walkable=True)
    water = Mesh('paddy_water',materials=[Material('paddy_water',(.10,.22,.14),.2,surface='water')],occludes=False)
    rice_parts=[]
    for j in range(n):
        z = j*h/max(1,n-1)
        rice = Mesh(f'rice_{j}',materials=[Material('rice',(.27,.40,.045)),Material('rice_gold',(.48,.49,.095))],
            occludes=False,motion=dict(kind='sway',height=.5,base=z-.02,amplitude=.08,seed=seed+j))
        rice_parts.append(rice)
        if season in ('autumn','dry','winter'):
            rice.materials=[Material('rice_straw',(.50,.38,.12)),Material('rice_dry_tips',(.61,.49,.19))]
        def edge(x): return j*l/n + .65*math.sin(x/w*math.tau+j*.48)
        for i in range(64):
            a,b = -w/2+i*w/64,-w/2+(i+1)*w/64
            ya,yb = edge(a),edge(b)
            bank.face(((a,ya,z),(b,yb,z),(b,yb+.32,z),(a,ya+.32,z)))
            bank.face(((a,ya,-.1),(b,yb,-.1),(b,yb,z),(a,ya,z)))
            water.face(((a,ya+.36,z-.025),(b,yb+.36,z-.025),(b,yb+l/n-.05,z-.025),(a,ya+l/n-.05,z-.025)))
        for x,y,u,v in scatter((w,l/n),density,(seed+j)%2147483648,limit=9000//n):
            y += j*l/n+l/(n*2)+.65*math.sin(x/w*math.tau+j*.48)
            for k in range(3):
                a = u*math.tau+k*2.4
                rice.leaf((x,y,z-.02),.45+v*.2,.015,a,1.1,k%2)
    out.parts.extend((bank,water,*rice_parts))
    return out
