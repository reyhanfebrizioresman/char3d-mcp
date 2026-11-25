"""Mesh contact contracts, measured independently from the IK solver."""
import math
import statistics


def metrics(nav, measured):
    result={'sides':{},'pelvis':{},'contract':'native active patches; arch excluded from gap, whole shoe included in penetration'}
    for side in 'LR':
        anchors={};maximum=0.;per_area={};episodes=[]
        for row in measured['rows']:
            p=row['feet'][side]
            points=p.get('contact_mesh_points_m',{})
            anchors={k:v for k,v in anchors.items() if k in points}
            for area,point in points.items():
                identity=p['contact_mesh_vertex_ids'][area]
                if area not in anchors or anchors[area][0]!=identity:
                    anchors[area]=(identity,point,row['frame'])
                anchor=anchors[area][1]
                drift=math.dist(point[:2],anchor[:2])
                maximum=max(maximum,drift);region=area.split(':',1)[0]
                per_area[region]=max(per_area.get(region,0.),drift)
                if drift>.006:episodes.append({'frame':row['frame'],'area':area,'drift_m':drift,'vertex':identity,'anchor_frame':anchors[area][2]})
        result['sides'][side]={'mesh_contact_drift_xy_m':maximum,'by_area_m':per_area,'violations':episodes}
    guard=nav.get('shoe_guard') or {}
    result['pelvis']={k:guard.get(k) for k in ('pelvis_delta_mean_m','pelvis_delta_max_m','pelvis_correction_step_max_m')}
    for side in 'LR':
        gaps=[max(0.,r['feet'][side]['contact_regions_m'][area]) for r in measured['rows'] for area in r['feet'][side].get('active_contact_regions',[]) if area in r['feet'][side].get('contact_regions_m',{})]
        strikes=[dict(frame=e['frame'],heel_gap_m=measured['rows'][e['frame']-nav['frames'][0]]['feet'][side]['contact_regions_m'].get('heel')) for e in nav['footfalls'] if e['side']==side]
        result['sides'][side].update(active_gap_mean_m=statistics.mean(gaps) if gaps else None,active_gap_p95_m=sorted(gaps)[min(len(gaps)-1,int(.95*len(gaps)))] if gaps else None,heel_strikes=strikes)
    result['contact_transitions']=guard.get('contact_transitions',[])
    result['max_transition_ankle_height_delta_m']=max((abs(v['ankle_height_delta_m']) for v in result['contact_transitions']),default=0.)
    result['max_transition_pelvis_height_delta_m']=max((abs(v['pelvis_height_delta_m']) for v in result['contact_transitions']),default=0.)
    result['failures']=[s+'_mesh_contact_drift_6mm' for s,m in result['sides'].items() if m['mesh_contact_drift_xy_m']>.006]
    if guard.get('pelvis_correction_step_max_m',0)>.003:result['failures'].append('pelvis_correction_step_3mm')
    return result
