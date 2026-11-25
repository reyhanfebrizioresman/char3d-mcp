"""Offline stance feasibility and v11/v12 deformation provenance diagnostics."""
import json
import os
from pathlib import Path


def main():
    work=Path(os.environ['CHAR3D_WORKSPACE'])
    reports={label:json.loads((work/f'walk_benchmark_{label}.json').read_text()) for label in ('v12','v13','v13_symmetric')}
    result={}
    for label in reports:
        result[label]={}
        for key,c in reports[label]['cases'].items():
            records=[]
            for side in 'LR':
                for a,b in c['nav']['foot_lock']['contacts'][side]:
                    feet=[c['rows'][f-c['rows'][0]['frame']]['feet'][side] for f in range(a,b+1)]
                    if not feet: continue
                    minimum=min(f['contact_regions_m']['mesh'] for f in feet)
                    maximum=max(f['contact_regions_m'][region] for f in feet for region in ('heel','ball'))
                    # A fixed contact translation must meet both constraints
                    # throughout the contact, and for BOTH required patches.
                    lower=-.002-minimum;upper=.002-maximum
                    records.append(dict(side=side,contact=[a,b],mesh_low_m=minimum,
                        highest_active_patch_minimum_m=maximum,
                        required_offset_interval_m=[lower,upper],constant_z_feasible=lower<=upper,
                        irreducible_vertical_interval_m=maximum-minimum))
            result[label][key]=dict(contacts=records, infeasible=sum(not r['constant_z_feasible'] for r in records),
                caveat='Fixed current contact orientation and observed skin deformation only; not a proof that every alternative pose/footwear design is impossible.')
    prior=Path('/home/reyhan/projects/char3d-engine/output/codex_evidence/walk_round10/worktree_output/walk_round10/walk_benchmark_v11.json')
    if prior.exists():
        old=json.loads(prior.read_text());trace={}
        for key in ('male/straight_1.0','male/turn_45_left','male/cruise_stop','male_tall_heavy/straight_1.0'):
            trace[key]={}
            for label,c in (('v11',old['cases'][key]),('v12',reports['v12']['cases'][key])):
                samples=[(r,s) for r in c['rows'] for s in 'LR' if 'mesh_low_m' in r['feet'][s]]
                if not samples:
                    trace[key][label]=dict(mesh_penetration_m=c['mesh_penetration_m'],frame=None,side=None,
                        caveat='Archived v11 contains aggregate mesh penetration only; no extreme frame is inferred.')
                    continue
                row,side=min(samples,key=lambda rs:rs[0]['feet'][rs[1]]['mesh_low_m'])
                trace[key][label]=dict(frame=row['frame'],side=side,mesh_low_m=row['feet'][side]['mesh_low_m'],
                    support=row['feet'][side]['support'],knee_deg=row['feet'][side]['knee_deg'],
                    foot_roll_deg=row['feet'][side]['foot_roll_deg'],mtp_deg=row['feet'][side]['mtp_extension_deg'],
                    pelvis_z_m=row['pelvis_m'][2],ankle_m=row['feet'][side]['ankle_m'],
                    caveat='Different route/phase samples; this is provenance, not a controlled one-line ablation. v11 mesh lows retain historical nearest-ankle classification.')
        result['v11_v12_skin_provenance']=trace
    (work/'walk_round11_contact_feasibility.json').write_text(json.dumps(result,indent=2)+'\n')
    print('CONTACT FEASIBILITY WRITTEN')


if __name__=='__main__':main()
