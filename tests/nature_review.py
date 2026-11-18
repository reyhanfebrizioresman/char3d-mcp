"""Review evidence, isolated on port 9997, using preserved script_to_scene actors.

New outputs live under output/nature_review; the original sheets and CPU records
remain untouched. Rebuild after source changes; --reuse rejects stale fixtures.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from nature_visuals import connect,py,ROOT,WORK,sheet
from engine.nature.presets import COMPOSITIONS,UPGRADED,PRESETS

DEST=WORK/'nature_review'


def reference(c):
    result={}
    for name,project in (('legacy','nature_legacy_park.blend'),('previous_park','nature_park.blend')):
        c.call('scene_info');c.call('open_project',path=project)
        c.call('set_lighting',preset='overcast',subject=['Ana_rig','Budi_rig'])
        c.call('cinematic_look',preset='none')
        values=[render(c,'reference',name,str(i),32,w)[1] for i,w in enumerate((320,960,960))]
        result[name]=dict(samples=values,seconds_per_frame=sum(values[1:])/2)
        print('REVIEW REFERENCE',name,result[name],flush=True)
    (DEST/'reference.json').write_text(json.dumps(result,indent=2))


def signature():
    files=[*sorted((ROOT/'engine/nature').glob('*.py')),ROOT/'engine/commands/outdoor.py']
    # Render estimates do not change a built recipe. Geometry/shader/camera
    # changes do, and must force fresh fixtures before visual comparison.
    chunks=[p.read_bytes().split(b'def cost_factor')[0] if p.name=='presets.py' else p.read_bytes() for p in files]
    return hashlib.sha256(b''.join(chunks)).hexdigest()


def build(c,preset):
    c.call('scene_info');c.call('open_project',path=f'nature_{preset}.blend')
    matrix=py(c,"from engine.commands.outdoor import outdoor_root\nsc=bpy.context.scene;sc.frame_set(1)\nresult=[list(row) for row in outdoor_root().matrix_world]")
    c.call('clear_environment')
    for shot in c.call('list_shots')['shots']: c.call('delete_shot',name=shot['camera'])
    env=c.call('set_environment',preset=preset,subject=['Ana_rig','Budi_rig'],variant=14)
    py(c,f"from mathutils import Matrix\nbpy.data.objects[{env['root']!r}].matrix_world=Matrix({matrix!r})\nbpy.context.view_layer.update()\nresult=True")
    c.call('set_lighting',preset='overcast',subject=['Ana_rig','Budi_rig'])
    profile=COMPOSITIONS[preset];shots=[]
    for name,size,subjects,start,end,angle,elevation in [
        ('ReviewWide','wide',['Ana_rig','Budi_rig'],1,23,profile['wide_angle'],profile['elevation']),
        ('ReviewMedium','medium',['Ana_rig'],24,47,30,3),
        ('ReviewClose','close_up',['Budi_rig'],48,72,-30,3)]:
        shots.append(c.call('camera_shot',subject=subjects,shot=size,name=name,start_frame=start,end_frame=end,
            angle=angle,elevation=elevation,face_coverage=True,
            action_line=None if size=='wide' else ['Ana_rig','Budi_rig']))
    c.call('set_timeline',frame_start=1,frame_end=72);c.call('cinematic_look',preset='none')
    c.call('save_project',path=f'nature_review/{preset}.blend')
    stats=py(c,"result=dict(objects=len(bpy.context.scene.objects),vertices=sum(len(o.data.vertices) for o in bpy.context.scene.objects if o.type=='MESH'),raytracing=bpy.context.scene.eevee.use_raytracing)")
    return dict(signature=signature(),environment=env,shots=shots,scene=stats,composition=profile)


def render(c,preset,look,label,frame,width=512,engine='eevee'):
    begin=time.perf_counter()
    r=c.call('render_preview',camera='scene',engine=engine,frame=frame,width=width,
             height=round(width*9/16),filename=f'nature_review/{preset}_{look}_{label}.png')
    elapsed=time.perf_counter()-begin
    assert r.get('engine',engine)!='cycles',r
    print('REVIEW STILL',preset,look,label,round(elapsed,3),flush=True)
    return r['path'],elapsed


def main(args):
    DEST.mkdir(parents=True,exist_ok=True);(DEST/'sheets').mkdir(exist_ok=True)
    (WORK/'renders/nature_review').mkdir(parents=True,exist_ok=True)
    file=DEST/'visuals.json';records=json.loads(file.read_text()) if file.exists() else {}
    c=connect()
    try:
        if args.reference: reference(c)
        for preset in args.only or [*UPGRADED,*PRESETS]:
            if args.reuse:
                record=records[preset]
                assert record['build']['signature']==signature(),f'{preset} fixture is stale; rebuild first'
                c.call('scene_info');c.call('open_project',path=f'nature_review/{preset}.blend')
            else:
                record=dict(build=build(c,preset),images={},times={});records[preset]=record
                file.write_text(json.dumps(records,indent=2))
            if args.preview:
                c.call('cinematic_look',preset='none')
                render(c,preset,'preview','wide',12,engine='workbench' if args.workbench else 'eevee')
                if preset=='park':
                    render(c,preset,'preview','medium',32,engine='workbench' if args.workbench else 'eevee')
                    render(c,preset,'preview','close',56,engine='workbench' if args.workbench else 'eevee')
            if args.sheets:
                for look in args.looks or ['none','golden_hour','misty_morning']:
                    c.call('cinematic_look',preset=look)
                    record['images'][look]=[];record['times'][look]=[]
                    for frame,label in ((12,'wide'),(32,'medium'),(56,'close')):
                        path,elapsed=render(c,preset,look,label,frame)
                        record['images'][look].append(path);record['times'][look].append(elapsed)
                    sheet(record['images'],DEST/'sheets'/f'{preset}.png')
                    file.write_text(json.dumps(records,indent=2))
                    print('REVIEW SHEET',preset,look,flush=True)
            if args.bench:
                c.call('cinematic_look',preset='none')
                values=[render(c,preset,'bench',str(i),32,w)[1] for i,w in enumerate((320,960,960))]
                ref=DEST/'reference.json'
                baseline=(json.loads(ref.read_text())['legacy']['seconds_per_frame'] if ref.exists()
                          else json.loads((WORK/'nature_baseline.json').read_text())['seconds_per_frame'])
                old=json.loads((WORK/'nature_benchmark.json').read_text())[preset]['seconds_per_frame']
                result=dict(samples=values,seconds_per_frame=sum(values[1:])/2,
                            baseline=baseline,previous=old,resolution=[960,540],samples_per_pixel=16,
                            scene=record['build']['scene'],signature=signature())
                result.update(ratio_legacy=result['seconds_per_frame']/baseline,ratio_previous=result['seconds_per_frame']/old)
                path=DEST/'benchmark.json';data=json.loads(path.read_text()) if path.exists() else {}
                data[preset]=result;path.write_text(json.dumps(data,indent=2))
                print('REVIEW BENCH',preset,result,flush=True)
    finally:c.stop()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--only',nargs='+');p.add_argument('--preview',action='store_true')
    p.add_argument('--sheets',action='store_true');p.add_argument('--looks',nargs='+');p.add_argument('--reuse',action='store_true')
    p.add_argument('--workbench',action='store_true');p.add_argument('--bench',action='store_true')
    p.add_argument('--reference',action='store_true')
    main(p.parse_args())
