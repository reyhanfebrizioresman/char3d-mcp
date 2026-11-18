"""Distinct staged landscapes built from the public, deterministic nature recipes.

The cast stays at the subject-foot plane. Each preset has its own ground layout,
landmark and planting plan; near/middle/far detail is frozen at build time.
"""
import json
import math

from . import (birds_flock,bush,clouds,falling_petals,flowers,grass_field,hills,
               lake,mountains_backdrop,path,reeds,rice_paddies,river,rocks,sea,tree,
               ferns,fallen_log,field_hut,gazebo,wooden_bridge)
from .blender import realize, _material
from .core import Material, Asset, Mesh
from .presets import COMPOSITIONS


def _curve(points,steps=8):
    """Bounded Hermite tangents round corners without long-segment overshoot."""
    out=[]
    for i,(a,b) in enumerate(zip(points,points[1:])):
        before=points[max(0,i-1)];after=points[min(len(points)-1,i+2)]
        length=math.dist(a,b)
        def tangent(p,q):
            size=max(math.dist(p,q),1e-9)
            return tuple((y-x)/size*length*.65 for x,y in zip(p,q))
        u,v=tangent(before,b),tangent(a,after)
        for k in range(steps):
            t=k/steps
            out.append(tuple((2*t**3-3*t*t+1)*x+(t**3-2*t*t+t)*dx+
                             (-2*t**3+3*t*t)*y+(t**3-t*t)*dy for x,y,dx,dy in zip(a,b,u,v)))
    return [*out,points[-1]]


def build_nature_set(b,preset,variant,density=1.):
    from ..commands.outdoor import _ground,_bench,_lamp,_umbrella
    from .camera import coverage, weight
    b.root['c3d_nature_preset']=preset;b.root['c3d_nature_density']=density
    b.root['c3d_nature_composition']=json.dumps(COMPOSITIONS[preset])
    b.root['c3d_nature_reflections']=preset in ('lakeside','riverside','rice_terraces','blossom_garden')
    variant%=2147480000;side=-1 if variant%2 else 1;bounds=coverage(b.root)
    b.root['c3d_nature_coverage']=json.dumps(bounds)
    clearings=[]
    for name,c in dict(grass=(.13,.21,.065),sand=(.57,.45,.28),path=(.42,.37,.27)).items():
        b.materials[name]=_material(b,Material(name,c,surface='sand' if name=='sand' else 'grass'))

    def put(asset,loc=(0,0,0),rotation=0,scale=1,landmark=None):
        if loc[2]<0:
            for part in asset.parts:
                if part.seat: part.seat['floor']=-loc[2]/scale
        names=realize(b,asset,loc,rotation,scale)
        if landmark:
            import bpy
            for name in names: bpy.data.objects[name]['c3d_nature_landmark']=landmark
        return names

    def land(name,points,z=0):
        m=Mesh(name,materials=[Material('bank_grass',(.13,.205,.065),surface='grass')],walkable=True)
        ps=[(x,y,z) for x,y in points]
        area=sum(a[0]*c[1]-c[0]*a[1] for a,c in zip(ps,ps[1:]+ps[:1]))
        m.face(ps if area>0 else list(reversed(ps)))
        return put(Asset(name,[m]))

    def route(points,width=2.7,material='gravel',raised=False,field_levels=None):
        curved=_curve(points);clearings.extend((x,y,width*.62) for x,y,z in curved)
        # Raised dikes need their full width as a planar tread. A cambered
        # shoulder is appropriate only where the path feathers into flat ground.
        asset=path(curved,width,material,variant,crown=not raised)
        if raised:
            # Use planar grades between height stations. Twisted, cambered
            # ribbons can leave a rigid sole straddling several tiny slopes.
            axis=max(range(2),key=lambda k:max(p[k] for p in points)-min(p[k] for p in points))
            def grade(q):
                if q<=points[0][axis]: return points[0][2]
                if q>=points[-1][axis]: return points[-1][2]
                a,c=next((a,c) for a,c in zip(points,points[1:]) if a[axis]<=q<=c[axis])
                return a[2]+(c[2]-a[2])*(q-a[axis])/(c[axis]-a[axis])
            asset.parts=asset.parts[:1]
            tread=asset.parts[0]
            for i,face in enumerate(tread.faces):
                for j,index in enumerate(face):
                    p=list(tread.vertices[index]);q=curved[i+(j>=2)][axis]
                    p[axis]=q;p[2]=grade(q)+.006;tread.vertices[index]=tuple(p)
        if field_levels:
            def center(y):
                a,c=next(((a,c) for a,c in zip(curved,curved[1:]) if a[1]<=y<=c[1]),
                         (curved[0],curved[1]) if y<curved[0][1] else (curved[-2],curved[-1]))
                return a[0]+(c[0]-a[0])*(y-a[1])/max(c[1]-a[1],1e-9)
            for part in asset.parts:
                part.vertices=[(center(y)+(x-center(y))*(1-.5*min(1,max(0,(y-2)/8))),y,z)
                               for x,y,z in part.vertices]
        if raised:
            m=asset.parts[0];m.materials.append(Material('path_embankment',(.22,.16,.075),surface='earth'))
            # Only ribbon faces precede the small aggregate. Close both sides.
            span=asset.metadata['faces_per_segment']
            for i in range(len(curved)-1):
                first,last=m.faces[i*span],m.faces[(i+1)*span-1]
                a,e=m.vertices[first[0]],m.vertices[first[3]]
                c,d=m.vertices[last[1]],m.vertices[last[2]]
                for sign,p,q in ((-1,a,e),(1,d,c)):
                    def base(point):
                        if not field_levels: return (point[0],point[1],-.32)
                        level=max((z for y,z in field_levels if y<=point[1]),default=-.18)
                        return (sign*1.8,point[1],level-.30)
                    m.face((p,q,base(q),base(p)),1)
        return put(asset,landmark='raised_causeway' if raised else 'curved_path')

    def plant(kind,x,y,h,detail=.65,season='summer',z=0):
        seed=(variant+round(abs(x*31+y*73)))%2147483648
        return put(tree(kind,h,seed,season,detail),(x,y,z),b.rng.uniform(0,360))

    def grove(kind='broadleaf',n=25,low=7,high=40,height=5,reject=None):
        for i in range(min(100,round(n*density))):
            x=b.rng.uniform(-30,30);y=b.rng.uniform(low,high)
            if bounds is not None and b.rng.random()>weight((x,y),bounds): continue
            if abs(x)<3 and y<13: x+=5 if x>=0 else -5
            if reject and reject(x,y): continue
            detail=(.7 if weight((x,y),bounds)>.8 else .3) if bounds else (.65 if y<14 else .30)
            plant(kind,x,y,height*b.rng.uniform(.8,1.3),detail)

    def meadow(x,y,w,l,seed,flower=True,exclude=(),height=.36):
        lod=weight((x,y),bounds)
        exclude=[*exclude,*((px-x,py-y,r) for px,py,r in clearings)]
        put(grass_field((w,l),12*density*lod,height,(.12,.235,.045),seed,exclude=exclude),(x,y,0))
        if flower: put(flowers((w,l),density=1.2*density*lod,height=.34,seed=seed+1,exclude=exclude),(x,y,0))

    def bench(x,y):
        seat=_bench(b,x,y);seat.data.materials[0]=b.materials['accent'];return seat

    wet=preset in ('lakeside','riverside','rice_terraces')
    if preset=='beach':
        edge=[(-180+i*2,6+.35*math.sin((-180+i*2)*.2)+.15*math.sin((-180+i*2)*.57)) for i in range(181)]
        shore=Mesh('sand_bank',materials=[Material('sand',(.57,.45,.28),surface='sand')],walkable=True)
        shore.face([(-180,-110,0),(180,-110,0),*[(x,y,0) for x,y in reversed(edge)]])
        for (x,y),(u,v) in zip(edge,edge[1:]): shore.face(((x,y,0),(u,v,0),(u,v,-.20),(x,y,-.20)))
        put(Asset('shore',[shore]))
    else:
        _ground(b,'deep_floor' if wet else 'meadow',(0,0,-.50 if wet else -.05),
                (240,240,.10),'grass')

    if preset=='park':
        route(((0,-80,0),(0,-5,0),(0,1,0),(1.8,6,0),(4.5,10,0),(2,17,0),(-4,26,0)))
        bench(-side*2.8,1.8);_lamp(b,side*3.4,3.0)
        for sign in (-1,1): meadow(sign*5,3,5.2,13,variant+40+(sign+1)*11)
        put(grass_field((65,40),.8*density,.32,seed=variant+90,exclude=[(x,y-22,r) for x,y,r in clearings]),(0,22,0))
        grove(n=30,height=5.2)
        for x,y,h in ((-5,4,5.2),(5,6,5.8),(-8,12,6),(9,15,6.5)):
            plant('maple',x,y,h,season='spring')
        # A layered green middle storey fills portrait backgrounds below the crowns.
        for x,y,h in ((-3.8,5.7,2.9),(3.8,6.5,3.1),(-4.5,11,3.3),(6,12,3.0)):
            plant('broadleaf',x,y,h,.45)
        for x,y,h in ((-3.8,4,1.5),(3.7,4.8,1.8),(-4.8,8,2.0),(4.7,9,1.8),(-5,13,2),(7,7,1.6)):
            put(bush(h,variant+round(y*9),detail=.65),(x,y,-.03))
        put(flowers((5,4),palette=((.88,.64,.20),(.96,.84,.48)),density=2*density,seed=variant),(6,10,0),landmark='sunny_flower_island')
        put(falling_petals((14,17),round(60*density),6,variant,'leaves'),(0,6,0))

    elif preset=='lakeside':
        # Cast on an L pier: open foreground water and a long reflected skyline.
        water=lake((100,78),variant);water.parts[0].materials[0].roughness=.07
        put(water,(4,20,-.075),landmark='open_lake')
        land('lake_west_shore',((-150,-100),(-5.5,-100),(-5.5,0),(-7,7),(-12,16),(-24,35),(-150,45)))
        land('lake_east_shore',((20,-100),(150,-100),(150,70),(20,70),(24,35),(21,18),(18,5)))
        _ground(b,'far_lake_bank',(0,103,-.05),(240,110,.10),'grass')
        for name,loc,dims in (('pier_deck',(0,-9.5,-.08),(3.6,24,.16)),('pier_head',(3.2,.9,-.08),(3.6,2.4,.16))):
            o=b.box(name,loc,dims,'wood',0);o['char3d_walkable']=True;o['c3d_weather_ground']=True;o['c3d_nature_landmark']='shore_pier'
        for x in (-1.75,1.75):
            for y in (-8,-3,1.8): b.box('pier_post',(x,y,.28),(.14,.14,1.1),'wood',0)
        # Broad seams are shallow grooves; they do not break the walking surface.
        joint=b.material('pier_joint',(.035,.023,.012))
        for y in range(-20,3):
            b.box('pier_seam',(0,y,.001),(3.52,.012,.002),joint,0)['c3d_nature_occludes']=False
        bench(3.2,1.0)
        for x,y,h in ((-8,3,3.7),(-10,10,5.2),(-18,23,6),(21,10,5.5),(25,24,6.8)):
            plant('maple',x,y,h,.55)
        put(reeds((2,10),4*density,1.0,variant),(-6.2,1,-.12))
        put(rocks(8,(2,12),.55,variant),(-6.4,3,-.14))
        meadow(-10,2,5,10,variant+41)
        grove(n=18,low=49,high=53,height=5.3,reject=lambda x,y:abs(x)<17)

    elif preset=='riverside':
        controls=((-18,-60),(-14,-12),(-8,0),(-6,3),(-1,8),(7,13),(11,21),(20,32),(25,75))
        points=[]
        for j,(a,c) in enumerate(zip(controls,controls[1:])):
            before=controls[max(0,j-1)][0];after=controls[min(len(controls)-1,j+2)][0]
            for k in range(8):
                u=k/8;x=.5*((2*a[0])+(-before+c[0])*u+(2*before-5*a[0]+4*c[0]-after)*u*u+(-before+3*a[0]-3*c[0]+after)*u**3)
                points.append((x,a[1]+(c[1]-a[1])*u,-.12))
        points.append((*controls[-1],-.12))
        put(river(points,5.2,variant,banks=True),landmark='winding_river')
        route(((0,-80,0),(0,-4,0),(0,1,0),(3.4,3.6,0),(4.7,6,0),(3.2,7.7,0)),2.5,'earth')
        put(wooden_bridge(8.2,1.7,.20,variant),(-1,8,-.08),82,landmark='river_bridge')
        route(((-5,8.6,0),(-8,12,0),(-11,18,0),(-9,26,0)),1.6,'earth')
        put(fallen_log(seed=variant),(4.1,1.9,-.02),-15,landmark='river_log_seat')
        for x,y,h in ((-13,-1,4.5),(-10,5,5.2),(-9,11,5.7),(5,3.5,3.8),(10,5,5.2),(13,13,6),(-7,19,6.4)):
            plant('maple',x,y,h,.55)
        for x,y in ((-10,0),(-8,5),(2,9),(9,15)):
            put(rocks(4,(2,3),.60,variant+round(y+2)),(x,y,-.15))
            put(reeds((1.3,3.2),3*density,.9,variant+round(y+9)),(x,y,-.12))
        meadow(4.5,1,5,8,variant+60);meadow(-13,7,4,12,variant+61)
        def in_river(x,y):
            a,c=next((a,c) for a,c in zip(controls,controls[1:]) if a[1]<=y<=c[1])
            center=a[0]+(c[0]-a[0])*(y-a[1])/(c[1]-a[1])
            return abs(x-center)<5.5
        grove(n=18,low=25,high=45,height=5.5,reject=in_river)
        _lamp(b,5.7,4.0)
        put(falling_petals((15,18),round(45*density),5,variant,'leaves'),(0,4,0))

    elif preset=='rice_terraces':
        # Clear crop roots beneath the gubuk and banana pads, including blade reach.
        paddies=rice_paddies(8,(56,42),6.4,2.8*density,variant,corridor=3.6,
                            exclude=((4.8,11.6,3.2),(-4.5,8.1,1.7)))
        put(paddies,(0,-4,-.18),landmark='contoured_sawah')
        levels=[(min(contour,key=lambda p:abs(p[0]))[1]-4,contour[0][2]-.18) for contour in paddies.metadata['dikes']]
        landing=paddies.metadata['dikes'][1][0][2]+.14
        route(((0,-80,0),(0,-4,0),(0,1,0),(.4,3,.20),(.5,6.8,landing),(.3,8.4,landing),(-.5,12,1.95),
               (.5,17,2.95),(-.4,22,3.92),(.3,29,5.25),(0,37,6.35)),2.8,'earth',raised=True,field_levels=levels)
        for j,x,kind,h in ((3,-15,'banana',3.0),(2,8,'palm',3.4),(5,24,'palm',5.5)):
            p=min(paddies.metadata['dikes'][j],key=lambda p:abs(p[0]-x))
            plant(kind,p[0],p[1]-4+.12,h,.75,z=p[2]-.18)
        # The field hut stands on a widened, dry pad beside the second dike.
        p=min(paddies.metadata['dikes'][1],key=lambda p:abs(p[0]-4.8))
        base=p[2]-.18
        top=base+.02;bottom=-.5
        o=b.box('hut_earth_pad',(4.8,7.6,(top+bottom)/2),(3.6,3.,top-bottom),'grass',0)
        o['char3d_walkable']=True
        put(field_hut(seed=variant),(4.8,7.6,base+.02),landmark='gubuk')
        route(((.4,7.6,landing),(1.7,7.6,landing),(3.6,7.6,landing)),
              1.3,'earth',raised=True)
        put(fallen_log(1.8,.22,variant),(4.8,7.9,base+.32),landmark='hut_seat')
        banana_base=paddies.metadata['dikes'][1][0][2]-.18
        top=banana_base+.02
        o=b.box('banana_dike_pad',(-4.5,4.1,(top+bottom)/2),(1.6,1.7,top-bottom),'grass',0)
        o['char3d_walkable']=True
        plant('banana',-4.5,4.1,2.8,.8,z=top)
        for x in (-26,26):
            p=min(paddies.metadata['dikes'][6],key=lambda p:abs(p[0]-x))
            plant('bamboo',p[0],p[1]-4,7,.4,z=p[2]-.18)

    elif preset=='blossom_garden':
        route(((0,-80,0),(0,-4,0),(0,1,0),(2.5,4,0),(5.4,8,0),(6,12,0),(2,18,0)),2.8,'stone')
        put(lake((9,7),variant),(-6.5,8,.075),landmark='garden_pond')
        put(gazebo(3.8,3.2,variant),(6,12,0),landmark='garden_gazebo')
        bench(4.5,3.2)
        for sign in (-1,1):
            meadow(sign*5,3,5.4,12,variant+41+(sign+1)*11,exclude=[(-6.5-sign*5,5,5)])
        grove('blossom',26,10,36,4.7,reject=lambda x,y:((x+6.5)/5)**2+((y-8)/4)**2<1.2)
        for x,y,h in ((-4.6,2.5,4.0),(4.6,4.8,4.3),(-11,9,4.8),(8,15,5.2),(-3.8,7.5,3.1)):
            plant('blossom',x,y,h,.7,'spring')
        for x,y,h in ((3.5,6.8,1.5),(-4,4.6,1.3),(-11,5,1.4),(8,8,1.6)):
            put(bush(h,variant+round(y*9),color=(.17,.28,.07),detail=.6),(x,y,-.02))
        stepping=Mesh('stepping_stones',materials=[Material('garden_stone',(.34,.35,.29),surface='stone')],walkable=True)
        for x,y in ((-1.8,2.0),(-2.7,2.6),(-3.4,3.3),(-3.8,4.2)):
            stepping.face([(x+.42*math.cos(j*math.tau/9),y+.30*math.sin(j*math.tau/9),.016) for j in range(9)])
        put(Asset('stepping_stones',[stepping]),landmark='pond_stepping_stones')
        put(falling_petals((12,14),min(500,round(450*density)),seed=variant,ground=True),(0,4,0))
        put(falling_petals((6,6),min(500,round(250*density)),seed=variant+1,ground=True),(-4,4,0))
        put(falling_petals((14,17),round(90*density),5,variant),(0,6,0))
        put(reeds((2,2),2*density,.65,variant),(-10,9,0))

    elif preset=='pine_forest':
        route(((0,-80,0),(0,-4,0),(0,1,0),(-1.2,6,0),(-2,11,0),(2,19,0),(3,28,0)),2.7,'earth')
        put(fallen_log(seed=variant),(3.8,2.6,-.02),-20,landmark='forest_log_seat')
        grove('pine',38,5,60,8.0)
        for x,y,h in ((-4.7,3.5,8.5),(5.5,5.5,9.5),(-7,10,11),(9,13,10)):
            plant('pine',x,y,h,.8)
        for sign in (-1,1):
            meadow(sign*5,4,5.0,14,variant+44+(sign+1)*9,flower=False)
            put(ferns((5,14),round(28*density),.95,variant+sign+9),(sign*5.3,7,0))
            put(rocks(7,(5,12),.65,variant+sign+2),(sign*6,9,-.06))
            for j in range(3): put(bush(1.2,variant+j+sign+8,color=(.045,.14,.055),detail=.45),(sign*(4.2+j),10+j*4,-.02))
        put(fallen_log(3.8,.20,variant+2),(-6,10,-.03),38)
        for x,y in ((-3.4,-.8),(-4.1,2),(3.8,1)):
            put(ferns((.3,.3),1,1.1,variant+round(y*3)+9),(x,y,0))
        put(falling_petals((12,14),round(38*density),7,variant,'leaves'),(0,7,0))

    elif preset=='beach':
        start=len(b.objects);b.prop('chair',(-side*2.7,1.3,0))
        seat=next(o for o in reversed(b.objects) if 'c3d_seat_centers' in o);seat['c3d_seat_kind']='deck_chair'
        for part in b.objects[start:]:
            if 'chair_back' in part.name: part.rotation_euler.x=math.radians(-15);part.location.y+=.07
        put(sea(seed=variant),(0,6,0))
        for x,y,h in ((-4.5,4.5,3.5),(4.8,5,3.9),(-8,5.2,4.2),(10,5,4.4),(-14,5,4.5),(18,4.9,4.8)):
            plant('palm',x,y,h,.8)
        for sign in (-1,1):
            put(grass_field((8,5),7*density,.44,(.25,.30,.09),variant+sign+5),(sign*7.5,1,0))
            put(rocks(4,(5,3),.65,variant+sign+8),(sign*7,4,0))
        foam=b.material('foam',(.72,.78,.70))
        for i in range(100):
            x=b.rng.uniform(-80,80);y=6+b.rng.uniform(.25,1.0)
            b.box('shore_foam',(x,y,-.018),(b.rng.uniform(.15,.7),.018,.006),foam,0)['c3d_nature_occludes']=False
        _umbrella(b,-side*3.8,2.6)
        put(mountains_backdrop(2,(180,30),6,variant),(0,120,-.4))

    elif preset=='mountain_village':
        route(((0,-80,0),(0,1,0),(-.5,5,0),(1.2,12,0),(0,20,0)),2.7,'stone')
        bench(-side*2.8,1.8)
        for sign in (-1,1): meadow(sign*5,4,5.2,13,variant+40+(sign+1)*11)
        put(grass_field((70,45),.9*density,.34,seed=variant+90,exclude=[(0,y-23,1.8) for y in range(0,24,2)]),(0,23,0))
        grove('pine',25,15,55,8)
        for x,y,h in ((-5,5,6),(6,7,7),(-9,14,8)): plant('blossom',x,y,h,.7,'spring')
        for x,y,s in ((-8,10,1),(8,12,1.15),(-14,18,.9),(15,23,1.1),(-5,27,.85)): _cottage(b,x,y,s)
        put(falling_petals((14,18),round(65*density),6,variant),(0,7,0))
        for sign in (-1,1): _lamp(b,sign*3.7,3.6)

    if preset!='beach':
        if not wet: put(hills((70,35),4,.5,variant),(0,52,-.08))
        height=34 if preset=='mountain_village' else 16 if wet else 24
        put(mountains_backdrop(3,(190,55),height,variant),(0,65,-.3))
    put(clouds(.28,25,'wisps',variant))
    put(birds_flock(7,((-16,22,10),(0,27,11),(18,23,12),(1,34,13)),variant))
    if preset in ('riverside','mountain_village'):
        from .blender import install_night_fill
        install_night_fill(b.root,b)
    return dict(preset=preset,density=density,composition=COMPOSITIONS[preset],
                lod='fixed near/middle/far detail; no frame switching',generators='engine.nature')


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
