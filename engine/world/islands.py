"""Stratified hanging gardens, rooted ledges and mist-fed waterfalls."""
import math
from ..nature.core import Asset,Mesh,Material,rng,add
from ..nature.surfaces import ellipsoid,tendril


def floating_island(radius=5.,depth=7.,vegetation=True,waterfall=True,seed=0,*,vines=True,mist=True,orbiting_rocks=5):
    """Stratified rock, grass cap, hanging roots, grove, falls/mist and orbiting fragments.

    The central cap stays walkable; edge planting leaves the acting area open.
    Mist uses translucent surface billows, no additional volume budget.
    """
    from ..nature import tree,bush,waterfall as falling_water
    random=rng(seed);r=radius;d=depth;n=48
    slate=Material('island_slate',(.21,.26,.27),shader='strata')
    edge=Material('island_edge',(.26,.31,.28),shader='strata')
    grass=Material('moss_top',(.13,.29,.055),surface='grass')
    m=Mesh('island_rock',materials=[slate,edge,grass],walkable=True)
    rings=[(1,0),(1.02,-.06),(.90,-.15),(.96,-.22),(.75,-.36),(.81,-.43),(.57,-.62),(.40,-.77),(.17,-.96),(.025,-1.08)]
    for j,(factor,z) in enumerate(rings):
        for i in range(n):
            a=i*math.tau/n;rr=r*factor*(1+.09*math.sin(a*5+.4)+.06*math.cos(a*9)+random.uniform(-.025,.025))
            m.vertices.append((rr*math.cos(a)+r*.12*(-z)**2,rr*.82*math.sin(a),d*z+(0 if j==0 else random.uniform(-.035,.035)*d)))
        if j:
            for i in range(n):
                k=(j-1)*n+i;q=(j-1)*n+(i+1)%n
                m.faces.append((k,k+n,q+n,q));m.indices.append(1 if j in (1,3,5) else 0)
    m.faces.append(tuple(range(n)));m.indices.append(2)
    out=Asset('floating_island',[m],{'seed':seed,'instances':1+orbiting_rocks})
    rim=Mesh('island_grass_rim',materials=[grass,Material('root_bark',(.15,.12,.055)),Material('vine_leaf',(.12,.27,.055))],smooth=True)
    for i in range(100):
        a=random.random()*math.tau;rr=r*random.uniform(.84,1.0);p=(rr*math.cos(a),rr*.8*math.sin(a),.015)
        for k in range(3):rim.leaf(p,r*random.uniform(.04,.095),r*.012,a+k*.8,.7)
    if vines:
        for i in range(24):
            a=i*2.4;rr=r*random.uniform(.82,.99);height=d*random.uniform(.3,.9)
            ps=[(math.cos(a)*(rr-j/16*r*.25)+.12*math.sin(j*.6+i),math.sin(a)*(rr*.81-j/16*r*.12),-j/16*height) for j in range(17)]
            tendril(rim,ps,r*.020,1)
            for j in range(3,15,2):
                rim.leaf(ps[j],r*.10,r*.037,a+j*.7,-.6,2)
    out.parts.append(rim)
    if vegetation:
        for i,(x,y,h) in enumerate([(-.45,.22,.85),(.30,.43,.64),(.53,-.14,.53)]):
            out.parts.extend(tree('broadleaf',height=r*h,detail=.65,seed=(seed+i)%2147483648).placed((x*r,y*r,0)).parts)
        for i in range(5):
            a=i*2.4;out.parts.extend(bush(height=r*.15,detail=.3,seed=(seed+i)%2147483648).placed((math.cos(a)*r*.65,math.sin(a)*r*.5,0)).parts)
    crags=Mesh('island_fractured_rock',materials=[slate,edge])
    for i in range(9):
        a=i*2.4;z=-d*random.uniform(.25,.72);rr=r*(.78+.52*z/d)
        ellipsoid(crags,(rr*math.cos(a),rr*.8*math.sin(a),z),
            (r*random.uniform(.12,.22),r*.14,d*random.uniform(.12,.22)),5,9,i%2,phase=a,displacement=.35)
    out.parts.append(crags)
    for i in range(orbiting_rocks):
        a=i*2.4;rock=Mesh('orbiting_fragment_'+str(i),materials=[slate],smooth=False,
            motion={'kind':'hero_orbit','radius':r*1.32,'phase':a})
        ellipsoid(rock,(0,0,-d*.35+math.sin(a)*d*.35),(r*.11,r*.085,r*.18),5,9,phase=a,displacement=.3)
        out.parts.append(rock)
    if waterfall:
        base=-d*1.6;location=(r*.12,-r*.79,base)
        out.parts.extend(falling_water(height=-base,width=r*.22,seed=seed).placed(location).parts)
        foam=Mesh('waterfall_foam',materials=[Material('foam',(.68,.85,.79),.7,emission=.08)],smooth=True,occludes=False)
        for j in range(9):
            ellipsoid(foam,(r*.12+random.uniform(-r*.14,r*.14),-r*.78,random.uniform(-.08,.03)),(r*.065,r*.06,.07),6,12)
        out.parts.append(foam)
        if mist:
            spray=Mesh('waterfall_mist',materials=[Material('spray_mist',(.61,.77,.77),1,shader='mist')],smooth=True,occludes=False,
                motion={'kind':'hero_swim','length':d,'amplitude':r*.04,'seed':seed})
            for j in range(13):
                ellipsoid(spray,add(location,(random.uniform(-r*.35,r*.35),random.uniform(-r*.18,r*.18),random.uniform(0,d*.2))),
                    (r*random.uniform(.15,.33),r*.22,d*.12),10,20,phase=j,displacement=.15)
            out.parts.append(spray)
    return out
