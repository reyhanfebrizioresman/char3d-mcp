# Pinned from 4c2935f for matched footwear QA only; not runtime code.
def _rigid_sole_weights(parts, rig):
    """Fit lower footwear to the two distal deform bones, once at build time.

    Rest vertices, morphs and non-deform groups are untouched. The ankle collar
    fades back to the authored weights; a boot shaft above it is unchanged.
    Use the existing semantic maps, including Rigify's DEF rather than controls.
    """
    from .anim import semantic_map
    smap = RIGIFY_DEF if rig.get('c3d_rig_type') == 'rigify' else semantic_map(rig)
    deform = {b.name for b in rig.data.bones if b.use_deform}
    joints = {}
    for side in 'LR':
        foot = rig.data.bones.get(smap.get('foot.'+side, ''))
        toe = rig.data.bones.get(smap.get('toe.'+side, ''))
        if foot is None or foot.name not in deform:
            raise ValueError(f'Missing deform foot mapping on {rig.name}: {side}')
        ankle = foot.head_local.copy()
        ball = toe.head_local.copy() if toe else foot.tail_local.copy()
        axis = ball-ankle; axis.z = 0
        length = max(axis.length, 1e-6)
        joints[side] = (foot.name, toe.name if toe and toe.name in deform else foot.name,
                        ankle, ball, axis.normalized(), length)

    def smooth(x):
        x = max(0., min(1., x))
        return x*x*(3-2*x)

    report = {}
    for obj in parts:
        if obj.type != 'MESH' or obj.get('c3d_garment_category') != 'shoes':
            continue
        transform = rig.matrix_world.inverted() @ obj.matrix_world
        groups = {g.index: g for g in obj.vertex_groups if g.name in deform}
        changed = rigid = blended = 0
        for v in obj.data.vertices:
            point = transform @ v.co
            side = min(joints, key=lambda s: (point-joints[s][2]).length_squared)
            foot, toe, ankle, ball, axis, length = joints[side]
            # The collar band is 30% of ankle-to-ball length high, centered
            # just below the ankle. Long boot shafts keep their original skin.
            amount = 1-smooth((point.z-(ankle.z-.20*length))/(.30*length))
            if amount <= 1e-8:
                continue
            toe_weight = smooth(((point-ball).dot(axis)+.10*length)/(.20*length))
            old = {groups[g.group].name:g.weight for g in v.groups if g.group in groups}
            weights = {name:weight*(1-amount) for name,weight in old.items()}
            weights[foot] = weights.get(foot, 0.)+amount*(1-toe_weight)
            weights[toe] = weights.get(toe, 0.)+amount*toe_weight
            total = sum(weights.values())
            weights = {name:w/total for name,w in weights.items() if w > 1e-8}
            if all(abs(old.get(n,0.)-weights.get(n,0.)) < 1e-7 for n in old.keys() | weights.keys()):
                continue
            for g in list(v.groups):
                if g.group in groups:
                    groups[g.group].remove([v.index])
            for name, weight in weights.items():
                group = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                group.add([v.index], weight, 'REPLACE')
                groups[group.index] = group
            changed += 1
            if amount >= 1-1e-8: rigid += 1
            else: blended += 1
        record = dict(version=1, changed_vertices=changed, rigid_vertices=rigid,
                      collar_vertices=blended, vertices=len(obj.data.vertices),
                      method='semantic foot/toe; smooth toe break and ankle collar')
        obj['c3d_rigid_sole'] = json.dumps(record)
        report[obj.name] = record
    return report
