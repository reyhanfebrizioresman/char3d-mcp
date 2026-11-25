"""Whole-body kinematic COM estimate, using de Leva (1996) male fractions.

Joint endpoints approximate anatomical segment boundaries. This is not a force,
COP, or dynamic stability calculation; clothing mass is not modeled. The same
reference table is deliberately used on all proportions for paired comparisons.
"""
from mathutils import Vector

# mass fraction and COM fraction from proximal endpoint, Table 4.
SEGMENTS = [('thigh', 'shin', .1416, .4095),
            ('shin', 'foot', .0433, .4459),
            ('upper_arm', 'forearm', .0271, .5772),
            ('forearm', 'hand', .0162, .4574)]


def estimate(rig, sm):
    mw = rig.matrix_world
    def head(k): return (mw @ rig.pose.bones[sm[k]].matrix).translation
    def tail(k): return mw @ rig.pose.bones[sm[k]].tail
    total = Vector(); mass = 0.
    def add(a,b,m,t):
        nonlocal total, mass
        total += a.lerp(b,t)*m
        mass += m
    # Pelvis-to-shoulder trunk and head/neck are anatomical approximations.
    shoulders = (head('upper_arm.L')+head('upper_arm.R'))*.5
    add(shoulders,head('hips'),.4346,.4486)
    add(head('neck') if 'neck' in sm else shoulders,tail('head'),.0694,.5976)
    for s in 'LR':
        for a,b,m,t in SEGMENTS: add(head(a+'.'+s),head(b+'.'+s),m,t)
        add(head('hand.'+s),tail('hand.'+s),.0061,.79)
        add(head('foot.'+s),tail('toe.'+s) if 'toe.'+s in sm else tail('foot.'+s),.0137,.4415)
    return total/mass
