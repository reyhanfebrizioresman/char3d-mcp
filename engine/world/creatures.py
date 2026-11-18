"""Original sculptural sky creatures, swept in 3D with saved analytic articulation."""
import math
from ..nature.core import Asset,Material,Mesh,add,mul,rng
from ..nature.surfaces import ellipsoid,sweep,tendril


def serpent(length=28.,radius=.65,segments=112,taper=.9,scales=True,horns=True,
            whiskers=True,fins=True,color=(.045,.32,.29),seed=0,*,legs=True,coil=1.,emission=.12):
    """Round transported 3D coil; plated belly, scale shader, flowing mane, jaw and claws.

    length is approximate centreline arc length; coil 0..1 blends S to spatial coil.
    Radius is the maximum body radius. Native swim and breathing jaw survive saves.
    """
    random=rng(seed);r=radius
    skin=Material('jade_scales',tuple(color),.32,.28,shader='scales' if scales else 'skin')
    belly=Material('belly',(.46,.66,.48),.48,.12,shader='belly')
    gold=Material('ivory_gold',(.84,.57,.23),.3,.55)
    dark=Material('mouth',(.018,.035,.03),.5)
    glow=Material('mane_glow',(.18,.70,.51),.4,.25,emission)
    raw=[]
    for j in range(segments+1):
        u=j/segments;t=-.45*math.pi+u*math.tau*1.13
        s=(math.sin(u*math.tau*1.1)*.22,(u-.5)*.9,math.cos(u*math.tau)*.10)
        c=(.32*math.sin(t),.21*math.cos(t)+u*.07,.19*math.cos(t*.9)+.025*math.sin(t*3))
        raw.append(tuple((1-coil)*a+coil*b for a,b in zip(s,c)))
    factor=length/sum(math.dist(a,b) for a,b in zip(raw,raw[1:]))
    points=[mul(p,factor) for p in raw]
    radii=[r*(1-taper*(j/segments)**1.65)*(.86+.14*math.sin(j/segments*math.pi)) for j in range(segments+1)]
    motion={'kind':'hero_swim','length':length,'amplitude':r*.45,'spatial':True,'seed':seed}
    body=Mesh('serpent_body',materials=[skin,belly],smooth=True,motion=motion)
    fs=sweep(body,points,radii,32,belly=1,uv=True)
    def at(j,v):
        p=points[j];R,T,U=fs[j]
        return add(p,add(mul(R,v[0]),add(mul(T,v[1]),mul(U,v[2]))))
    detail=Mesh('serpent_mane',materials=[gold,glow],smooth=True,motion=dict(motion))
    if fins:
        # Continuous scalloped sail with a gilded rib every few vertebrae.
        for j in range(1,segments):
            a=at(j-1,(0,0,radii[j-1]*.94));b=at(j,(0,0,radii[j]*.94))
            height=lambda k:radii[k]+r*.65*(1-k/segments)*(.75+.25*math.sin(k*1.3))
            c=at(j,(0,0,height(j)));d=at(j-1,(0,0,height(j-1)))
            detail.face((a,b,c,d),1)
            if j%4==0:detail.tube(b,c,r*.025,r*.009,6,0)
        ridge=[at(j,(0,0,radii[j]+r*.4*(1-j/segments))) for j in range(0,segments+1,2)]
        tendril(detail,ridge,r*.055,0)
    R,T,U=fs[0]
    def headpoint(v):return at(0,mul(v,r))
    def headblob(mesh,p,scale,mat=0,rings=12,sides=24):
        start=len(mesh.vertices);ellipsoid(mesh,(0,0,0),mul(scale,r),rings,sides,mat)
        mesh.vertices[start:]=[add(headpoint(p),add(mul(R,v[0]),add(mul(T,v[1]),mul(U,v[2])))) for v in mesh.vertices[start:]]
    headskin=Material('jade_scales',tuple(color),.32,.28,shader='skin')
    head=Mesh('serpent_head',materials=[headskin,gold,dark,belly,
        Material('eye',(1,.60,.13),.22,.25,.5),Material('pupil',(.002,.009,.008),.12),
        Material('eye_glint',(.75,1,.87),.15,emission=1.2)],smooth=True,motion=dict(motion))
    headblob(head,(0,-.35,.10),(1.24,1.75,.94))
    headblob(head,(0,-1.65,-.02),(.87,1.12,.48))
    headblob(head,(0,-1.5,-.43),(.82,1.18,.13),2)
    jaw=Mesh('serpent_jaw',materials=[belly,gold,dark],smooth=True,
        motion={'kind':'hero_jaw','pivot':headpoint((0,-.4,-.5)),'axis':list(R),'seed':seed,'amplitude':.10,
                'swim_length':length,'swim_amplitude':r*.45,'spatial':True})
    headblob(jaw,(0,-1.5,-.62),(.85,1.17,.22))
    for sign in (-1,1):
        headblob(head,(sign*1.03,-.85,.4),(.30,.40,.28),1)
        headblob(head,(sign*1.24,-1.0,.43),(.16,.24,.19),4)
        headblob(head,(sign*1.35,-1.05,.44),(.055,.12,.14),5)
        headblob(head,(sign*1.39,-1.09,.51),(.029,.045,.036),6,8,12)
        headblob(head,(sign*.52,-2.50,.19),(.13,.17,.07),2,8,16)
        # Brows and cheek plates, rather than eyes pasted on a tube.
        for k in range(4):
            headblob(head,(sign*(1.05-.07*k),-.5+k*.24,.63),(.27,.38,.17),1,8,16)
        if horns:
            ps=[headpoint((sign*(.64+.30*u),.20+1.5*u,.75+1.8*u-.4*u*u)) for u in [i/12 for i in range(13)]]
            tendril(head,ps,r*.21,1,12)
            tendril(head,[ps[6],headpoint((sign*1.5,.65,2)),headpoint((sign*1.7,.8,2.3))],r*.09,1)
        if whiskers:
            for row in (0,1):
                ps=[headpoint((sign*(.65+3.7*u),-2.0-1.1*math.sin(u*math.pi),-.17+row*.18+.65*u*u)) for u in [i/20 for i in range(21)]]
                tendril(head,ps,r*(.045-row*.01),1)
        for k in range(5):
            a=headpoint((sign*.66,-2.25+k*.32,-.39))
            head.tube(a,add(a,mul(U,-r*.20)),r*.055,0,8,1)
    limbs=Mesh('serpent_limbs',materials=[headskin,gold],smooth=True,motion=dict(motion))
    if legs:
        for u in (.13,.60):
            j=round(u*segments);rr=radii[j]
            for sign in (-1,1):
                ps=[at(j,(sign*rr*.72,0,-rr*.2)),at(j,(sign*rr*1.8,-r*.35,-r*.8)),at(j,(sign*rr*2.1,-r*1.3,-r*.9))]
                sweep(limbs,ps,[rr*.32,rr*.23,rr*.16],12)
                for toe in (-1,0,1):
                    q=add(ps[-1],add(mul(fs[j][0],toe*r*.18),mul(fs[j][1],-r*.5)))
                    tendril(limbs,[ps[-1],q,add(q,mul(fs[j][2],-r*.27))],r*.08,1)
    return Asset('serpent',[body,detail,head,jaw,limbs],{'seed':seed})


def whale_like(length=12.,color=(.075,.24,.34),seed=0,*,motion=1.5):
    """Sculpted continuous sky swimmer, curved pleats and independently hinged fins/flukes."""
    rng(seed);l=length
    skin=Material('whale_blue',tuple(color),.36,.12,shader='skin')
    cream=Material('whale_underside',(.58,.76,.72),.48,shader='belly')
    dark=Material('whale_seam',(.018,.065,.08),.38)
    tail_pivot=[0,l*.15,-l*.015]
    m=Mesh('whale_body',materials=[skin,cream,dark],smooth=True,
        motion={'kind':'hero_swim','length':l,'amplitude':l*.016,'seed':seed,
                'tail_amplitude':.36*motion,'tail_pivot':tail_pivot})
    # Closed round profile, no intersecting ellipsoids at the belly.
    n=80;sides=48
    for j in range(n+1):
        u=j/n;y=l*(-.5+u);shape=math.sin(math.pi*u)**.65
        taper=1-.72*u**1.25;rx=l*.235*shape*taper;rz=l*.195*shape*taper
        z=-l*.035*u+math.sin(u*math.pi)*l*.025
        for k in range(sides):
            a=k*math.tau/sides;m.vertices.append((rx*math.cos(a),y,z+rz*math.sin(a)))
        if j:
            for k in range(sides):
                b=(j-1)*sides+k;c=(j-1)*sides+(k+1)%sides
                m.faces.append((b,b+sides,c+sides,c));m.indices.append(1 if math.sin((k+.5)*math.tau/sides)<-.30 and u<.68 else 0)
    fins=[]
    def flipper(name,outline,pivot,axis,angle,phase=0):
        mesh=Mesh(name,materials=[skin,cream],smooth=True,motion={'kind':'hero_hinge','pivot':pivot,'axis':axis,
            'amplitude':angle*motion,'speed':1.4,'phase':phase,'seed':seed,
            'swim_length':l,'swim_amplitude':l*.016})
        # A swept hydrofoil with a rounded leading edge and tapering tip.
        start=len(mesh.vertices);steps=24;around=16
        for j in range(steps+1):
            u=j/steps;p,width=outline(u)
            for k in range(around):
                a=k*math.tau/around
                mesh.vertices.append((p[0],p[1]+width*math.cos(a),p[2]+width*.16*math.sin(a)))
            if j:
                for k in range(around):
                    b=start+(j-1)*around+k;c=start+(j-1)*around+(k+1)%around
                    mesh.faces.append((b,c,c+around,b+around) if outline(1)[0][0]>0 else (b,b+around,c+around,c));mesh.indices.append(1 if k>=8 else 0)
        fins.append(mesh)
    for sign in (-1,1):
        pivot=(sign*l*.12,-l*.22,-l*.04)
        flipper('pectoral_'+str(sign),lambda u,s=sign:((s*l*(.12+.34*u),l*(-.22+.23*u+.045*math.sin(u*math.pi)),
            -l*(.04+.06*u)),l*(.07*math.sin(math.pi*(.12+.87*u))+.001)),pivot,[0,1,0],sign*.27,sign*.6)
        flipper('fluke_'+str(sign),lambda u,s=sign:((s*l*.27*u,l*(.43+.10*u-.06*u*u),-l*.035+l*.025*u),
            l*(.075*math.sin(math.pi*(.06+.93*u))+.001)),tail_pivot,[1,0,0],.36,0)
    # Dorsal, curved mouth line and ventral grooves share the body motion field.
    for sign in (-1,1):
        ps=[]
        for j in range(25):
            u=.04+j/24*.34;shape=math.sin(math.pi*u)**.65*(1-.72*u**1.25)
            ps.append((sign*l*.235*shape*.92,l*(-.5+u),-l*.035*u+l*.025*math.sin(math.pi*u)-l*.195*shape*.36))
        tendril(m,ps,l*.0025,2)
    for k in range(9):
        ps=[]
        for j in range(28):
            u=.07+j/27*.47;shape=math.sin(math.pi*u)**.65*(1-.72*u**1.25);a=-math.pi/2+(k-4)*.11
            ps.append((l*.235*shape*math.cos(a),l*(-.5+u),-l*.035*u+l*.025*math.sin(math.pi*u)+l*.195*shape*math.sin(a)-l*.001))
        tendril(m,ps,l*.0017,2,6)
    # Filled swept dorsal fin (a tube outline reads as an accidental empty A).
    dorsal=[(0,l*.06,l*.10),(0,l*.13,l*.19),(0,l*.17,l*.205),
        (0,l*.18,l*.15),(0,l*.25,l*.065)]
    for sign in (-1,1):
        center=(sign*l*.008,l*.16,l*.115)
        for a,b in zip(dorsal,dorsal[1:]+dorsal[:1]):
            m.face((center,a,b) if sign==1 else (center,b,a))
    eyes=Mesh('whale_eyes',materials=[dark,Material('eye',(.005,.018,.025),.12),Material('eye_glint',(.6,.86,1),.1,emission=.5)],smooth=True,
        motion={'kind':'hero_swim','length':l,'amplitude':l*.016,'seed':seed})
    for sign in (-1,1):
        ellipsoid(eyes,(sign*l*.142,-l*.31,l*.013),(l*.018,l*.028,l*.017),12,24)
        ellipsoid(eyes,(sign*l*.154,-l*.315,l*.014),(l*.009,l*.016,l*.010),12,24,1)
        ellipsoid(eyes,(sign*l*.161,-l*.320,l*.019),(l*.003,l*.005,l*.003),8,12,2)
    return Asset('whale_like',[m,*fins,eyes],{'seed':seed})
