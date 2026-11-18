"""Original stylized heroes. Pure geometry, meters/Z-up; no IO or executable input.

Creatures face -Y. Mesh motion specs are realized as saved native shape drivers.
They are designs from anatomical/architectural vocabulary, never named IP assets.
"""
import math
from ..nature.core import Asset, Material, Mesh, rng
from ..nature.props import _box


def _ellipsoid(mesh, p, radii, rings=16, sides=32, mat=0):
    """Smooth closed lathed ellipsoid, with reproducible topology."""
    start = len(mesh.vertices)
    for j in range(rings+1):
        t = .001+(math.pi-.002)*j/rings
        for i in range(sides):
            a=i*math.tau/sides
            mesh.vertices.append((p[0]+radii[0]*math.sin(t)*math.cos(a),
                p[1]+radii[1]*math.sin(t)*math.sin(a), p[2]+radii[2]*math.cos(t)))
    for j in range(rings):
        for i in range(sides):
            k=start+j*sides+i;q=start+j*sides+(i+1)%sides
            mesh.faces.append((k,k+sides,q+sides,q));mesh.indices.append(mat)


def _fin(m, points, thickness=.08, mat=0):
    center=tuple(sum(p[i] for p in points)/len(points) for i in range(3))
    for sign in (-1,1):
        peak=(center[0],center[1],center[2]+sign*thickness)
        for a,b in zip(points,points[1:]+points[:1]):
            m.face((a,b,peak) if sign==1 else (b,a,peak),mat)


def serpent(length=14., radius=.65, segments=80, taper=.85, scales=True,
            horns=True, whiskers=True, fins=True, color=(.045,.32,.29), seed=0):
    """Sinuous tapered body, plated dorsal crest, expressive horned head; saved swim."""
    random=rng(seed);r=radius
    skin=Material('jade_scales',tuple(color),.34,.22)
    gold=Material('ivory_gold',(.86,.53,.16),.32,.45)
    body=Mesh('serpent_body',materials=[skin,Material('belly',(.36,.64,.48),.5),gold],smooth=True,
              motion={'kind':'hero_swim','length':length,'amplitude':r*.28})
    centers=[]
    for j in range(segments+1):
        u=j/segments;y=(u-.5)*length;x=math.sin(u*math.tau*1.15)*length*.12
        z=math.cos(u*math.tau)*length*.055
        rad=r*(1-taper*u**1.7)*(.84+.16*math.sin(math.pi*u))
        centers.append((x,y,z,rad))
        for k in range(16):
            a=k*math.tau/16
            body.vertices.append((x+rad*math.cos(a),y,z+rad*math.sin(a)))
        if j:
            for k in range(16):
                b=(j-1)*16+k;c=(j-1)*16+(k+1)%16
                body.faces.append((b,b+16,c+16,c));body.indices.append(1 if k>=8 else 0)
    body.faces += [tuple(reversed(range(16))),tuple(range(segments*16,(segments+1)*16))]
    body.indices += [0,0]
    detail=Mesh('serpent_crest',materials=[gold,skin],motion=dict(body.motion))
    for j,(x,y,z,rad) in enumerate(centers):
        if j%3==0 and fins:
            _fin(detail,[(x,y-r*.45,z+rad*.9),(x,y+r*.5,z+rad),
                (x,y+r*.6,z+rad+r*.65*(1-j/(segments+1)))],.035)
        if scales and j%2==0:
            for a in (.3,1.,2.1,2.8,3.5,5.7):
                xx=x+rad*1.015*math.cos(a);zz=z+rad*1.015*math.sin(a)
                detail.face(((xx-r*.075,y,zz),(xx,y-r*.19,zz+r*.02),
                             (xx+r*.075,y,zz),(xx,y+r*.19,zz-r*.02)),0)
    x,y,z,_=centers[0]
    head=Mesh('serpent_head',materials=[skin,gold,Material('eye',(1,.73,.19),.2,emission=.8),
        Material('pupil',(.003,.009,.012),.2)],smooth=True,motion=dict(body.motion))
    _ellipsoid(head,(x,y-r*.45,z),(r*1.15,r*1.7,r*.82))
    _ellipsoid(head,(x,y-r*1.5,z-r*.18),(r*.76,r*.9,r*.46))
    for s in (-1,1):
        _ellipsoid(head,(x+s*r*.95,y-r*.8,z+r*.3),(r*.21,r*.32,r*.22),8,16,2)
        _ellipsoid(head,(x+s*r*1.08,y-r*.88,z+r*.31),(r*.065,r*.19,r*.13),8,12,3)
        if horns:
            a=(x+s*r*.64,y+r*.1,z+r*.48);b=(x+s*r*.95,y+r*.7,z+r*1.65)
            head.tube(a,b,r*.17,r*.055,10,1)
            head.tube(b,(x+s*r*1.2,y+r*1.25,z+r*2.1),r*.055,0,8,1)
        if whiskers:
            ps=[(x+s*r*.55,y-r*2,z-r*.14),(x+s*r*1.8,y-r*2.5,z-r*.3),
                (x+s*r*2.5,y-r*2.3,z+r*.12)]
            for a,b in zip(ps,ps[1:]): head.tube(a,b,r*.035,r*.012,6,1)
    return Asset('serpent',[body,detail,head],{'seed':seed})


def whale_like(length=12., color=(.075,.24,.34), seed=0):
    """Broad smooth sky swimmer with throat pleats, swept pectorals and split flukes."""
    rng(seed);l=length
    skin=Material('whale_blue',tuple(color),.4,.15)
    cream=Material('whale_underside',(.64,.78,.73),.55)
    m=Mesh('whale_body',materials=[skin,cream],smooth=True,
           motion={'kind':'hero_swim','length':l,'amplitude':l*.018})
    _ellipsoid(m,(0,-l*.12,0),(l*.17,l*.37,l*.15),24,48)
    _ellipsoid(m,(0,-l*.17,-l*.065),(l*.145,l*.31,l*.095),16,32,1)
    for j in range(7):
        x=(j-3)*l*.026
        m.tube((x,-l*.43,-l*.087),(x,-l*.05,-l*.16),l*.002,sides=5)
    m.tube((0,l*.1,0),(0,l*.48,-l*.015),l*.12,l*.035,24)
    fins=Mesh('whale_fins',materials=[skin,cream],smooth=True,
              motion={'kind':'hero_swim','length':l,'amplitude':l*.045})
    for s in (-1,1):
        _fin(fins,[(s*l*.11,-l*.2,-l*.03),(s*l*.46,l*.02,-l*.12),
                   (s*l*.38,l*.12,-l*.14),(s*l*.12,-l*.02,-l*.08)],l*.022)
        _fin(fins,[(0,l*.40,0),(s*l*.25,l*.49,.02*l),(s*l*.21,l*.59,.045*l),
                   (s*l*.06,l*.53,-l*.01),(0,l*.55,0)],l*.014)
    _fin(fins,[(0,l*.07,l*.12),(0,l*.16,l*.23),(0,l*.25,l*.08)],l*.01)
    eyes=Mesh('whale_eyes',materials=[Material('eye',(.005,.014,.018),.1),
                   Material('eye_glint',(.8,.95,1),.2,emission=.4)],smooth=True,
        motion={'kind':'hero_swim','length':l,'amplitude':l*.018})
    for s in (-1,1):
        _ellipsoid(eyes,(s*l*.153,-l*.3,l*.015),(l*.012,l*.023,l*.012),8,16)
        _ellipsoid(eyes,(s*l*.163,-l*.307,l*.019),(l*.003,l*.006,l*.003),6,8,1)
    return Asset('whale_like',[m,fins,eyes],{'seed':seed})


def bird_like(wingspan=9., glowing=False, color=(.48,.12,.045), seed=0):
    """Long feathered wings and trailing fan tail; optional ember-emissive plumage."""
    rng(seed);s=wingspan
    gold=Material('plumage',tuple(color),.4,.12,1.3 if glowing else 0)
    tips=Material('feather_tips',(1,.56,.12),.45,.1,2 if glowing else 0)
    body=Mesh('bird_body',materials=[gold,tips],smooth=True)
    _ellipsoid(body,(0,0,0),(s*.045,s*.16,s*.055))
    _ellipsoid(body,(0,-s*.16,s*.04),(s*.04,s*.06,s*.045))
    body.tube((0,-s*.19,s*.035),(0,-s*.27,s*.015),s*.024,0,8,1)
    wing=Mesh('bird_wings',materials=[gold,tips],motion={'kind':'hero_flap','amplitude':.6})
    for sign in (-1,1):
        _fin(wing,[(0,-s*.05,0),(sign*s*.24,-s*.08,s*.06),(sign*s*.5,s*.10,s*.05),
                   (sign*s*.24,s*.12,0),(0,s*.08,0)],s*.005)
        for j in range(12):
            u=j/12;x=sign*s*(.14+.32*u)
            wing.leaf((x,s*(.03+.06*u),s*.025),s*(.22-.08*u),s*.016,1.3 if sign==1 else 1.84,-.1,j%2)
        for j in range(4):
            body.leaf((sign*s*.012*j,s*.1,0),s*(.35-j*.035),s*.018,math.pi/2+sign*j*.07,-.15,j%2)
    return Asset('bird_like',[body,wing],{'seed':seed})


def crystal_cluster(count=9,height=3.,color=(.12,.55,.65),seed=0):
    """Faceted hexagonal prisms with luminous tips, no expensive transmission."""
    random=rng(seed)
    m=Mesh('crystals',materials=[Material('crystal',tuple(color),.19,.4,.18),
        Material('crystal_tip',(.54,.91,.86),.22,.25,.65)],solid=True)
    for i in range(count):
        x,y=random.uniform(-height*.45,height*.45),random.uniform(-height*.3,height*.3)
        h=height*(1 if i==0 else random.uniform(.25,.8));r=h*random.uniform(.12,.23)
        m.tube((x,y,0),(x,y,h*.78),r,r*.85,6)
        m.tube((x,y,h*.78),(x+random.uniform(-r,r),y,h),r*.85,0,6,1)
    return Asset('crystal_cluster',[m],{'seed':seed})


def arch_gate(width=6.,height=6.,style='arch',seed=0):
    """Generic arch or paired-post curved-beam gateway, no landmark reproduction."""
    rng(seed)
    stone=Material('gate_stone',(.22,.31,.30),.7,.08)
    gold=Material('gate_trim',(.65,.35,.10),.4,.4)
    parts=[]
    for sign in (-1,1):
        m=Mesh('gate_pillar',materials=[stone,gold],solid=True)
        _box(m,(sign*width/2,0,height*.42),(.48,.65,height*.84))
        for z in (.12,height*.18,height*.72): _box(m,(sign*width/2,0,z),(.7,.8,.18),1)
        parts.append(m)
    roof=Mesh('gate_crown',materials=[stone,gold],solid=True)
    if style=='arch':
        for i in range(32):
            a=i*math.pi/32;b=(i+1)*math.pi/32
            p=(math.cos(a)*width/2,0,height*.65+math.sin(a)*height*.35)
            q=(math.cos(b)*width/2,0,height*.65+math.sin(b)*height*.35)
            roof.tube(p,q,.32,sides=8,mat=1 if i%4==0 else 0)
    else:
        for j in range(24):
            x=(j/24-.5)*width*1.35;q=x+width*1.35/24
            z=lambda v: height*.88+height*.12*(abs(v)/(width*.675))**3
            roof.tube((x,0,z(x)),(q,0,z(q)),.22,sides=6)
        _box(roof,(0,0,height*.70),(width*1.18,.35,.18),1)
    parts.append(roof)
    return Asset('arch_gate',parts,{'seed':seed})


def pagoda_like(width=6.,height=9.,tiers=3,seed=0):
    """Original open tiered pavilion: upturned layered eaves and warm window ribs."""
    rng(seed);parts=[]
    wood=Material('pavilion_timber',(.18,.075,.032));jade=Material('pavilion_roof',(.045,.21,.19),.4,.3)
    trim=Material('roof_trim',(.73,.45,.16),.4,.35)
    for j in range(tiers):
        w=width*(1-j*.17);base=j*height/tiers;h=height/tiers
        m=Mesh('pavilion_tier',materials=[wood,jade,trim],solid=True)
        for x in (-w*.33,w*.33):
            for y in (-w*.33,w*.33): _box(m,(x,y,base+h*.36),(.14,.14,h*.72))
        _box(m,(0,0,base+.08),(w*.82,w*.82,.16))
        # Three nested ring bands give curved upturned eaves.
        for k in range(3):
            u=k/3;v=(k+1)/3
            def ring(t):
                r=w*(.61-.45*t);z=base+h*(.70+.23*t)+h*.10*(1-t)**5
                return [(-r,-r,z),(r,-r,z),(r,r,z),(-r,r,z)]
            a,b=ring(u),ring(v)
            for n in range(4): m.face((a[n],a[(n+1)%4],b[(n+1)%4],b[n]),1)
        for a,b in zip(ring(0),ring(0)[1:]+ring(0)[:1]):m.tube(a,b,.045,sides=6,mat=2)
        parts.append(m)
    parts[-1].tube((0,0,height*.94),(0,0,height*1.08),.06,0,8,2)
    return Asset('pagoda_like',parts,{'seed':seed})


def lantern_swarm(count=24,area=(18,14),height=10.,size=.45,rise=.12,reflection=False,seed=0):
    """Individual ribbed paper lanterns, seeded rise/bob and emissive flicker; zero lights."""
    random=rng(seed);out=Asset('lantern_swarm',metadata={'seed':seed,'instances':count})
    reflected=Mesh('lantern_reflections',materials=[Material('reflected_gold',(1,.43,.12),.35,.18,.7)],
        occludes=False,motion={'kind':'water','amplitude':.003,'seed':seed})
    for i in range(count):
        x=random.uniform(-area[0]/2,area[0]/2);y=random.uniform(-area[1]/2,area[1]/2);z=random.uniform(1,height)
        r=size*random.uniform(.6,1.25)
        m=Mesh(f'lantern_{i}',materials=[Material('paper',(1,.38+random.random()*.18,.10),.65,emission=2.1),
            Material('ribs',(.32,.11,.025),.7),Material('flame',(1,.72,.28),.4,emission=5)],
            occludes=False,smooth=True,motion={'kind':'hero_lantern','seed':seed+i,'amplitude':.25,'rise':rise})
        _ellipsoid(m,(x,y,z),(r*.48,r*.48,r*.64),8,12)
        for k in range(8):
            a=k*math.tau/8;dx,dy=math.cos(a)*r*.46,math.sin(a)*r*.46
            m.tube((x+dx,y+dy,z-r*.35),(x+dx,y+dy,z+r*.35),r*.013,sides=4,mat=1)
        for dz in (-.46,.46):
            m.tube((x,y,z+dz*r-r*.025),(x,y,z+dz*r+r*.025),r*.36,sides=12,mat=1)
        _ellipsoid(m,(x,y,z-r*.44),(r*.08,r*.08,r*.12),4,8,2)
        out.parts.append(m)
        if reflection:
            # Broken warm glints are an intentionally stylized water reflection,
            # not screen-space tracing or a simulated reflection of unseen objects.
            for j in range(12):
                length=r*(1.2-.07*j);yy=y-j*r*.3;xx=x+math.sin(j*2.4+i)*r*.25
                reflected.face(((xx-length/2,yy,-.20),(xx+length/2,yy,-.20),
                    (xx+length*.35,yy+r*.045,-.20),(xx-length*.35,yy+r*.045,-.20)))
    if reflection:out.parts.append(reflected)
    return out


def hot_air_balloons(count=3,area=(30,18),height=18.,size=2.,seed=0):
    """Striped silk envelopes, suspension ropes and wicker baskets; seeded saved drift."""
    random=rng(seed);out=Asset('hot_air_balloons',metadata={'seed':seed,'instances':count})
    for i in range(count):
        x=random.uniform(-area[0]/2,area[0]/2);y=random.uniform(-area[1]/2,area[1]/2);z=height+random.uniform(-3,3)
        m=Mesh(f'balloon_{i}',materials=[Material('silk_red',(.57,.12,.065),.6),Material('silk_cream',(.9,.70,.36),.7),
            Material('wicker',(.25,.12,.04))],smooth=True,motion={'kind':'hero_lantern','seed':seed+i,'amplitude':.32})
        start=len(m.faces);_ellipsoid(m,(x,y,z),(size,size,size*1.25),16,24)
        for j in range(start,len(m.indices)):m.indices[j]=((j-start)%24)//3%2
        _box(m,(x,y,z-size*2),(.6*size,.5*size,.4*size),2)
        for dx in (-.25,.25):
            for dy in (-.2,.2):m.tube((x+dx*size,y+dy*size,z-size*1.9),(x+dx*size,y+dy*size,z-size*.9),.015*size,sides=5,mat=2)
        out.parts.append(m)
    return out


def floating_island(radius=5.,depth=7.,vegetation=True,waterfall=True,seed=0):
    """Hanging faceted rock cone with moss rim, small grove and descending water ribbons."""
    from ..nature import tree, waterfall as falling_water
    random=rng(seed);r=radius
    m=Mesh('island_rock',materials=[Material('island_slate',(.17,.22,.23)),Material('island_edge',(.28,.34,.32)),
        Material('moss_top',(.14,.29,.08),surface='grass')],walkable=True)
    rings=[(1,0),(.94,-depth*.14),(.60,-depth*.57),(.12,-depth),(0,-depth*1.08)]
    n=32
    for j,(factor,z) in enumerate(rings):
        for i in range(n):
            a=i*math.tau/n;rr=r*factor*(1+.08*math.sin(a*5)+random.uniform(-.035,.035))
            m.vertices.append((rr*math.cos(a),rr*.82*math.sin(a),z))
        if j:
            for i in range(n):
                k=(j-1)*n+i;q=(j-1)*n+(i+1)%n
                m.faces.append((k,k+n,q+n,q));m.indices.append(1 if j==1 else 0)
    m.faces.append(tuple(range(n)));m.indices.append(2)
    out=Asset('floating_island',[m],{'seed':seed})
    if vegetation:
        for i in range(4):
            a=i*2.4
            out.parts.extend(tree('broadleaf',height=r*.6,detail=.25,seed=(seed+i)%2147483648).placed(
                (math.cos(a)*r*.48,math.sin(a)*r*.38,0)).parts)
    if waterfall:
        out.parts.extend(falling_water(height=depth*1.6,width=r*.24,seed=seed).placed((0,-r*.78,-depth*1.6)).parts)
    return out


def banner_cloth(width=1.8,height=4.,color=(.65,.14,.09),seed=0):
    """Tapered hanging cloth on a gilded pole; saved rippling deformation."""
    rng(seed)
    pole=Mesh('banner_pole',materials=[Material('banner_gold',(.63,.4,.12),.4,.5)],solid=True)
    pole.tube((0,0,0),(0,0,height*1.1),.045,sides=10)
    pole.tube((0,0,height),(width,0,height),.035,sides=8)
    m=Mesh('banner_cloth',materials=[Material('banner_fabric',tuple(color),.85)],occludes=False,
        motion={'kind':'hero_banner','height':height,'amplitude':width*.15})
    for j in range(17):
        for i in range(9):
            u=i/8;v=j/16
            m.vertices.append((u*width,.04*math.sin(u*6+v*5),height*(1-v*.76)+.18*v**6*math.sin(u*math.pi)))
            if i and j:
                k=j*9+i;m.faces.append((k-10,k-9,k,k-1));m.indices.append(0)
    return Asset('banner_cloth',[pole,m],{'seed':seed})


GENERATORS={f.__name__:f for f in (serpent,whale_like,bird_like,floating_island,lantern_swarm,
    hot_air_balloons,crystal_cluster,arch_gate,pagoda_like,banner_cloth)}
