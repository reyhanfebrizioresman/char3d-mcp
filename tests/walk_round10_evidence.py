"""R10 telemetry comparison and matched, side-on cached-pose review sheets.

--report is offline; --render never rebakes either version. Owns only port 9977.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient
from walk_benchmark import summarize
from walk_round8_review import montage


def report(work, reports):
    comparison = {}
    lines = ['# Ronde 10 — seluruh kasus', '',
             'Sudut dalam derajat; panjang/gap dalam mm. Fase v11 dan v12 dianalisis ulang dengan interpolasi linier pada fase yang sama; '
             'JSON v11 asli dan fingerprint bake tetap utuh. Cruise mengecualikan 30 frame akselerasi (waktu akselerasi tetap, tidak dibagi speed), '
             'kedua footprint awal dan siklus yang mencapai dua langkah penutup. — berarti rute tidak menyediakan siklus cruise lengkap.', '',
             '| Kasus | Lutut maks v11 → v12 °/f | Clearance toe tengah swing v11 → v12 mm | Plafon swing L/R v11 → v12 % | Gap mesh v11 → v12 mm | Penetrasi mesh v11 → v12 mm | Kontrak kontak v12 |',
             '|---|---:|---:|---|---:|---:|---|']
    def fmt(x): return '—' if x is None else f'{x:.2f}'
    for key, new in reports['v12']['cases'].items():
        old = reports['v11']['cases'][key]
        assert old['fixture_sha256'] == new['fixture_sha256'], key
        assert old['parameters'] == new['parameters'], key
        pair = {}
        for label, c in [('v11',old),('v12',new)]:
            summary, steps = summarize(c['nav'],c,'/pivot_' in key,c['parameters'].get('speed',1.))
            # Occupancy always uses the cap actually used to author that version.
            if label == 'v11':
                for side in 'LR':
                    swing = [r['feet'][side] for r in c['rows'] if r['feet'][side]['support']=='swing']
                    metric=summary['swing_metrics'][side]
                    metric.update(knee_cap_deg_per_frame=14.,knee_cap_frames=sum(abs(f['knee_delta_deg']-14)<.05 for f in swing))
                    metric['knee_cap_percent']=100*metric['knee_cap_frames']/max(1,len(swing))
            pair[label] = summary
        targets=[]
        for side, metrics in pair['v12']['swing_metrics'].items():
            if metrics['mid_swing_min_toe_clearance_m'] is not None and metrics['mid_swing_min_toe_clearance_m'] < .01:
                targets.append(side+'_mid_swing_clearance')
        if 'straight' in key:
            for phase, metrics in pair['v12']['cruise_phase_asymmetry_deg'].items():
                for channel in ('knee_deg','ankle_plantarflexion_deg'):
                    value=metrics[channel]
                    if value is not None and value > 4: targets.append(phase+'_'+channel+'_asymmetry')
            delta=pair['v12']['asymmetry_absolute']['step_length_m']
            mean=pair['v12']['side_means']['L']['step_length_m']
            if delta is not None and delta > max(.02,.03*abs(mean)):
                targets.append('step_length_asymmetry')
            for side in 'LR':
                for phase, (low,high) in {'pre_swing':(30,40),'toe_off':(35,45)}.items():
                    value=pair['v12']['cruise_phase_means'][side][phase]['knee_deg']
                    if value is not None and not low <= value <= high:
                        targets.append(side+'_'+phase+'_envelope')
        if new['mesh_flat_gap_m'] > .003: targets.append('mesh_flat_gap_3mm')
        if new['mesh_penetration_m'] > .002: targets.append('mesh_penetration_2mm')
        pair['remaining_target_flags']=targets
        signed_mesh=[f['mesh_low_m'] for r in new['rows'] for f in r['feet'].values() if 'mesh_low_m' in f]
        minimum_mesh=min(signed_mesh,default=-new['mesh_penetration_m'])
        signed_flat=[f['mesh_low_m'] for r in new['rows'] for f in r['feet'].values()
                     if f['support']=='flat' and 'mesh_low_m' in f]
        if signed_flat:
            # A uniform margin must simultaneously satisfy delta >= -2mm-min
            # and delta <= 3mm-max. Empty interval proves a static offset cannot fit.
            pair['outsole_static_offset_feasibility_m']=dict(
                min_flat=min(signed_flat),max_flat=max(signed_flat),min_mesh=minimum_mesh,
                minimum_offset=-.002-minimum_mesh,
                maximum_offset=.003-max(signed_flat),
                feasible=-.002-minimum_mesh <= .003-max(signed_flat))
        comparison[key]=pair
        clearance=[]; occupancy=[]
        for label in ('v11','v12'):
            m=pair[label]['swing_metrics']
            values=[v['mid_swing_min_toe_clearance_m'] for v in m.values() if v['mid_swing_min_toe_clearance_m'] is not None]
            clearance.append(fmt(1000*min(values)) if values else '—')
            occupancy.append('/'.join(fmt(m[s]['knee_cap_percent']) for s in 'LR'))
        lines.append('| '+key+' | '+fmt(old['summary']['max_knee_delta_deg'])+' → '+fmt(new['summary']['max_knee_delta_deg'])+
                     ' | '+' → '.join(clearance)+' | '+' → '.join(occupancy)+
                     ' | '+fmt(old['mesh_flat_gap_m']*1000)+' → '+fmt(new['mesh_flat_gap_m']*1000)+
                     ' | '+fmt(old['mesh_penetration_m']*1000)+' → '+fmt(new['mesh_penetration_m']*1000)+
                     ' | '+(', '.join(new['summary']['failures']) or 'PASS')+' |')
    lines += ['', '## Sudut per tubuh/kasus/sisi/fase', '',
              '| Kasus | Sisi | Fase | Lutut v11 → v12 | Foot roll v11 → v12 | Ankle PF v11 → v12 | MTP v11 → v12 |',
              '|---|---|---|---:|---:|---:|---:|']
    for key,pair in comparison.items():
        for side in 'LR':
            for phase in pair['v12']['cruise_phase_means'][side]:
                values=[' → '.join(fmt(pair[label]['cruise_phase_means'][side][phase][channel]) for label in ('v11','v12'))
                        for channel in ('knee_deg','foot_roll_deg','ankle_plantarflexion_deg','mtp_extension_deg')]
                lines.append('| '+key+' | '+side+' | '+phase+' | '+' | '.join(values)+' |')
    lines += ['', '## Target yang belum terpenuhi', '']
    for key,pair in comparison.items():
        if pair['remaining_target_flags']: lines.append('- '+key+': '+', '.join(pair['remaining_target_flags']))
    (work/'walk_round10_comparison.md').write_text('\n'.join(lines)+'\n')
    (work/'walk_round10_contracts.json').write_text(json.dumps(comparison,indent=2)+'\n')
    print('COMPARISON',len(comparison),'matched cases',flush=True)


CAMERA = '''
from mathutils import Vector
sc=bpy.context.scene
cam=bpy.data.objects.new('R10Side',bpy.data.cameras.new('R10Side'));sc.collection.objects.link(cam)
cam.data.type='ORTHO';cam.data.ortho_scale=SCALE
cam.location=(CENTRE[0]+4,CENTRE[1],CENTRE[2])
cam.rotation_euler=Vector((-1,0,0)).to_track_quat('-Z','Y').to_euler();sc.camera=cam
sc.render.resolution_x=512;sc.render.resolution_y=512;sc.render.resolution_percentage=100
curve=bpy.data.curves.new('R10Floor','CURVE');curve.dimensions='3D';curve.bevel_depth=.0007
sp=curve.splines.new('POLY');sp.points.add(1)
sp.points[0].co=(CENTRE[0],-12,0,1);sp.points[1].co=(CENTRE[0],2,0,1)
sc.collection.objects.link(bpy.data.objects.new('R10Floor',curve))
result=True
'''


def render(work,reports):
    engine=BlenderClient();call=engine.call
    try:
        call('scene_info')
        environment=call('run_python',code="import sys\nsys.path.insert(0,'/home/reyhan/.codex/skills/blender-core/scripts')\nimport env_report\nresult=env_report.run()")['result']
        (work/'blender_environment.json').write_text(json.dumps(environment,indent=2)+'\n')
        paths=[];labels=[]
        for label in ('v11','v12'):
            c=reports[label]['cases']['male/straight_1.0']
            step=next(s for s in c['steps'] if s['side']=='L' and s['kind']=='cruise')
            ev=next(e for e in c['nav']['support_events'] if e['side']=='L' and e['land']==step['next_land'])
            frames=[ev['lift'],round((ev['lift']+ev['land'])/2),ev['land']]
            for phase,f in zip(('toe-off','mid-swing','heel strike'),frames):
                call('open_project',path=c['project']);call('scene_info')
                r=c['rows'][f-c['rows'][0]['frame']];foot=r['feet']['L']
                centre=[foot['ankle_m'][0],foot['ankle_m'][1],.55]
                code=CAMERA.replace('SCALE','1.25').replace('CENTRE',repr(centre))
                call('run_python',code=code)
                output=call('render_frames',frames=[f],camera='scene',objects=['Gait_rig'],size=512,engine='workbench',prefix=f'{label}_swing_{phase.replace(" ","_")}')
                paths.append(output['frames'][0]['path'])
                labels.append(f'{label} | L {phase} F{f}\nankle PF {foot["ankle_plantarflexion_deg"]:+.1f} deg | knee {foot["knee_deg"]:.1f} deg')
        montage(paths,labels,work/'walk_swing_v11_v12.png','3x2','512x512+5+10')
        paths=[];labels=[]
        for body in ('male','male_tall_heavy'):
            for label in ('v11','v12'):
                c=reports[label]['cases'][body+'/straight_1.0']
                # First full stable flat interval, shared normalized stance phase.
                interval=next((a,b) for a,b in c['nav']['foot_lock']['contacts']['L'] if a>30 and b-a>=2)
                f=interval[0]+1
                call('open_project',path=c['project']);call('scene_info')
                foot=c['rows'][f-c['rows'][0]['frame']]['feet']['L']
                centre=[foot['heel_m'][0],(foot['heel_m'][1]+foot['toe_m'][1])/2,.075]
                call('run_python',code=CAMERA.replace('SCALE',repr(max(.4,1.5*math.dist(foot['heel_m'],foot['toe_m'])))).replace('CENTRE',repr(centre)))
                output=call('render_frames',frames=[f],camera='scene',objects=['Gait_rig'],size=512,engine='workbench',prefix=f'{label}_contact_{body}')
                paths.append(output['frames'][0]['path'])
                labels.append(f'{body} | {label} flat L F{f}\nwhole-case max gap {1000*c["mesh_flat_gap_m"]:.2f} mm / penetration {1000*c["mesh_penetration_m"]:.2f} mm')
        montage(paths,labels,work/'walk_contact_v11_v12.png','2x2','512x512+5+10')
        qa_sheets={}
        for body in ('male','female_short','male_tall_heavy'):
            c=reports['v12']['cases'][body+'/straight_1.0']
            step=next(s for s in c['steps'] if s['complete_cycle'])
            frame=step['phases']['peak_swing']['frame']
            call('open_project',path=c['project']);call('scene_info')
            qa_sheets[body]={}
            for mode in ('random','wire'):
                destination=work/'renders'/f'qa_{body}_{mode}.png'
                qa_sheets[body][mode]=call('run_python',code=f"""
import sys
sys.path.insert(0,'/home/reyhan/.codex/skills/blender-asset-qa/scripts')
import review_shots
bpy.context.scene.frame_set({frame})
rig=bpy.data.objects['Gait_rig']
objects=[o.name for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render
         and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
result=review_shots.run(objects=objects,out={str(destination)!r},views=['front','right','back','three_quarter'],mode={mode!r},res=256)
""")['result']
        (work/'qa_visual_sheets.json').write_text(json.dumps(qa_sheets,indent=2)+'\n')
        print('MATCHED SIDE AND MULTI-ANGLE QA SHEETS WRITTEN',flush=True)
    finally:engine.stop()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',action='store_true');p.add_argument('--render',action='store_true');args=p.parse_args()
    assert os.environ.get('CHAR3D_PORT')=='9977'
    work=Path(os.environ['CHAR3D_WORKSPACE'])
    reports={label:json.loads((work/f'walk_benchmark_{label}.json').read_text()) for label in ('v11','v12')}
    if args.report:report(work,reports)
    if args.render:render(work,reports)


if __name__=='__main__':main()
