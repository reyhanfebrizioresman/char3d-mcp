"""Independent per-region, mesh-swing, kinematic COM and joint continuity report."""
import math


def extrema(values):
    return dict(min=min(values),max=max(values)) if values else None


def metrics(nav, measured, fps=24):
    rows = measured['rows']; first = rows[0]['frame']
    result = dict(sides={}, com_model=measured.get('com_model'),
                  com_trace=[dict(frame=r['frame'],com_m=r.get('com_m'),
                    relative_support_m=r.get('com_relative_support_m'),
                    support_segment_xy_m=r.get('support_segment_xy_m'),
                    support_area_xy_m=r.get('support_area_xy_m'),
                    relative_support_area_center_m=r.get('com_relative_support_area_center_m'),
                    support_feet=r.get('support_feet'),yaw_rate_deg_s=r['yaw_rate_deg_s'],
                    pelvis_lateral_m=r.get('pelvis_lateral_m')) for r in rows])
    for side in 'LR':
        def foot(f): return rows[f-first]['feet'][side]
        active = {k:[] for k in ('heel','ball','toe')}
        all_regions = {k:[] for k in ('heel','ball','toe','arch')}
        arch_stance=[]; airborne=[]; middle=[]; swing_traces=[]; stance_knees=[]
        for row in rows:
            f = row['frame']; p = row['feet'][side]
            regions = p.get('contact_regions_m',{})
            for k in all_regions:
                if k in regions: all_regions[k].append(regions[k])
            if p['support'] != 'swing':
                if 'arch' in regions: arch_stance.append(regions['arch'])
                roll = p['foot_roll_deg']
                areas = p.get('active_contact_regions',
                              ('heel',) if roll < -1 else ('ball','toe') if roll > 1 else ('heel','ball'))
                p['active_contact_regions'] = list(areas)
                for k in areas:
                    if k in regions: active[k].append((f,regions[k]))
                if abs(row['yaw_rate_deg_s'])>10: stance_knees.append(p['knee_deg'])
        for e in nav['support_events']:
            if e['side']!=side: continue
            trace=[]
            for f in range(e['lift']+1,e['land']):
                if not first <= f <= rows[-1]['frame']: continue
                u=(f-e['lift'])/(e['land']-e['lift'])
                low=foot(f).get('mesh_low_m')
                if low is None:continue
                trace.append(dict(frame=f,phase=u,mesh_clearance_m=low))
                if e['lift']+2 < f < e['land']-2: airborne.append(low)
                if .35<=u<=.65:middle.append(low)
            swing_traces.append(dict(lift=e['lift'],land=e['land'],trace=trace))
        joints={}
        for channel in ('knee_deg','ankle_plantarflexion_deg'):
            vals=[r['feet'][side][channel] for r in rows]
            derivatives=[]
            for order in range(3):
                vals=[(b-a)*fps for a,b in zip(vals,vals[1:])]
                derivatives.append(max(map(abs,vals),default=0.))
            joints[channel]=dict(zip(('max_velocity_deg_s','max_acceleration_deg_s2','max_jerk_deg_s3'),derivatives))
        cap=min(21.,17.*max(1.,nav.get('rhythm_speed',1.)))
        limited=[r['frame'] for r in rows if abs(r['feet'][side]['knee_delta_deg']-cap)<.05]
        episodes=[]
        for f in limited:
            if episodes and f==episodes[-1][-1]+1:episodes[-1].append(f)
            else:episodes.append([f])
        result['sides'][side]=dict(
            active_contact_regions={k:dict(samples=len(v),max_gap_m=max((max(0.,z) for _,z in v),default=0.),
                max_penetration_m=max((max(0.,-z) for _,z in v),default=0.),
                worst_gap_frame=max(v,key=lambda x:x[1])[0] if v else None) for k,v in active.items()},
            contact_region_height_ranges_m={k:extrema(v) for k,v in all_regions.items()},
            arch_clearance_m=extrema(arch_stance),
            swing_min_mesh_clearance_m=min(airborne,default=None),
            mid_swing_min_mesh_clearance_m=min(middle,default=None),swing_traces=swing_traces,
            turning_support_knee_deg=extrema(stance_knees),joint_continuity=joints,
            knee_limiter=dict(active_frames=len(limited),duration_s=len(limited)/fps,
                activations=len(episodes),longest_s=max(map(len,episodes),default=0)/fps,
                episodes=episodes,definition='baked angular rate within 0.05 degrees/frame of engineering cap'))
    result['target_failures']=[]
    if measured['mesh_penetration_m']>.002: result['target_failures'].append('mesh_penetration_2mm')
    for s,m in result['sides'].items():
        for k,r in m['active_contact_regions'].items():
            if r['max_gap_m']>.002:result['target_failures'].append(s+'_'+k+'_active_gap_2mm')
        if m['swing_min_mesh_clearance_m'] is not None and m['swing_min_mesh_clearance_m']<0:
            result['target_failures'].append(s+'_swing_mesh_penetration')
        if m['mid_swing_min_mesh_clearance_m'] is not None and m['mid_swing_min_mesh_clearance_m']<.008:
            result['target_failures'].append(s+'_mid_swing_mesh_clearance_8mm')
    return result
