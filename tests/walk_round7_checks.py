"""Matched v8/v9 per-frame locomotion telemetry (one owned engine, port 9977).

Run with --baseline for pinned 7f5ff90, then without it for the candidate.
No video render here; the final demo reuses the saved candidate project.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('CHAR3D_PORT','9977')
os.environ.setdefault('CHAR3D_WORKSPACE',str(ROOT/'output/walk_round7/telemetry'))
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient
from walk_gait_checks import check

CAPTURE = '''
from engine.commands import walk, anim
walk._telemetry = {}
walk._original_lock = walk.foot_lock
def capture(rig, start, end, **kw):
    sm = anim.semantic_map(rig)
    rows = {}
    for f in range(start, end+1):
        bpy.context.scene.frame_set(f)
        rows[f] = {s: list((rig.matrix_world@rig.pose.bones[sm['foot.'+s]].matrix).translation) for s in 'LR'}
    result = walk._original_lock(rig, start, end, **kw)
    walk._telemetry = rows
    return result
walk.foot_lock = capture
result = True
'''


def telemetry(call, rig, nav):
    return call('run_python', code=f'''
import math
from mathutils import Vector
from engine.commands import anim,walk
from engine.walk_gait import contact_phase
rig=bpy.data.objects[{rig!r}]; mw=rig.matrix_world; sm=anim.semantic_map(rig)
nav={nav!r}; sc=bpy.context.scene; rows=[]; previous=None
lands={{s:[e['frame'] for e in nav['footfalls'] if e['side']==s] for s in 'LR'}}
for f in range(nav['frames'][0],nav['frames'][1]+1):
 sc.frame_set(f)
 yaw=walk._anatomical_yaw(rig); hip=(mw@rig.pose.bones[sm['hips']].matrix).translation
 rate=0 if previous is None else math.degrees(walk._angle(previous,yaw))*sc.render.fps/sc.render.fps_base
 previous=yaw; forward=Vector((math.sin(yaw),-math.cos(yaw),0)); left=Vector((math.cos(yaw),math.sin(yaw),0))
 row={{'frame':f,'root_yaw_deg':math.degrees(yaw),'root_angular_velocity_deg_s':rate,'pelvis_m':list(hip),'feet':{{}}}}
 for s in 'LR':
  a=max([v for v in lands[s] if v<=f],default=nav['frames'][0])
  b=min([v for v in lands[s] if v>a],default=a+max(1,2*(a-max([v for v in lands['R' if s=='L' else 'L'] if v<a],default=a-12))))
  cycle=(f-a)/max(1,b-a)
  H=(mw@rig.pose.bones[sm['thigh.'+s]].matrix).translation
  K=(mw@rig.pose.bones[sm['shin.'+s]].matrix).translation
  M=mw@rig.pose.bones[sm['foot.'+s]].matrix; A=M.translation
  rest=mw@rig.data.bones[sm['foot.'+s]].matrix_local
  fw=M.to_quaternion()@rest.to_quaternion().inverted()@walk._terrain_forward(rig,sm)
  flat=any(a<=f<=b for a,b in nav['foot_lock']['contacts'][s])
  airborne=any(e['side']==s and e['lift']<f<e['land'] for e in nav['support_events'])
  before=walk._telemetry.get(f,{{}}).get(s)
  row['feet'][s]={{'cycle':cycle,'phase':contact_phase(cycle),'support':'swing' if airborne else 'flat' if flat else 'rolling',
   'knee_flexion_deg':math.degrees((K-H).angle(A-K)),
   'plantarflexion_deg':-math.degrees(math.atan2(fw.z,math.hypot(fw.x,fw.y))),
   'ankle_m':list(A),'pelvis_forward_m':(hip-A).dot(forward),'pelvis_lateral_m':(hip-A).dot(left),
   'ik_correction_m':None if before is None else (A-Vector(before)).length}}
 rows.append(row)
result=rows
''')['result']


def run():
    label = 'v8' if '--baseline' in sys.argv else 'v9'
    engine = BlenderClient(); call = engine.call
    work = Path(engine.workspace); work.mkdir(parents=True, exist_ok=True)
    try:
        print('SCENE', call('scene_info'), flush=True)
        if label == 'v8':
            source = subprocess.check_output(['git','show','7f5ff90:engine/commands/walk.py'],cwd=ROOT,text=True)
            call('run_python',code='from engine.commands import walk\nexec(compile('+repr(source)+",'walk_v8.py','exec'),vars(walk))\nresult=True")
        call('run_python',code=CAPTURE)
        report = {}
        for kind in ('straight','demo'):
            call('new_scene',fps=24)
            h=call('create_realistic_human',name='Gait' if kind=='straight' else 'Budi',gender=1,age=32,hair='short02',outfit='casual',seed=3)
            rig=h['armature']
            call('save_project',path=f'{label}_{kind}_rest.blend')
            if kind == 'demo':
                call('transform_object',name=rig,location=[-2,1,0],rotation_deg=[0,0,90])
            nav=call('walk_path',armature=rig,points=[[0,-5]] if kind=='straight' else [[.4,1],[.4,-.9]],start_frame=1,avoid=False)
            rows=telemetry(call,rig,nav)
            measured=check(call,rig,nav)
            report[kind]={'walk':nav,'rows':rows,'measured':measured}
            if kind=='demo':
                turn=call('turn_to',armature=rig,target=[.4,3],avoid=False)
                report[kind]['turn']=turn
                report[kind]['turn_rows']=telemetry(call,rig,turn)
                report[kind]['turn_measured']=check(call,rig,turn)
            call('save_project',path=f'{label}_{kind}.blend')
            print(kind,json.dumps(measured),flush=True)
        (work/f'{label}_telemetry.json').write_text(json.dumps(report,indent=2))
        if label=='v9':
            for kind,item in report.items():
                for action in ('walk','turn') if kind=='demo' else ('walk',):
                    m=item['measured' if action=='walk' else 'turn_measured']
                    rows=item['rows' if action=='walk' else 'turn_rows']
                    assert m['flat_drift_m']<.005 and m['toe_support_drift_m']<.005,m
                    assert m['penetration_m']<.002 and m['mesh_penetration_m']<.002,m
                    assert m['knee_step_deg']<25,m
                    assert m['joint_hold_m']<.001 and m['joint_hold_rotation_rad']<.002,m
                    assert max(abs(r['root_angular_velocity_deg_s']) for r in rows)<(200 if action=='turn' else 100.1)
            print('ROUND7 TELEMETRY CONTRACT OK',flush=True)
    finally:
        engine.stop()


if __name__=='__main__':
    run()
