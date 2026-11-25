"""Build-time identity/sole contracts across all MPFB skeletons and styles."""
import json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mcp_server.blender_client import BlenderClient
CAPTURE='''
from engine.commands import mpfb
import hashlib
original=mpfb._rigid_sole_weights
captured={}
def digest(parts,rig):
 data=[]
 for o in parts:
  data.append((o.name,[tuple(v.co) for v in o.data.vertices],[tuple(p.vertices) for p in o.data.polygons],
    [(k.name,[tuple(v.co) for v in k.data]) for k in o.data.shape_keys.key_blocks] if o.data.shape_keys else [],
    [[(o.vertex_groups[g.group].name,g.weight) for g in v.groups] for v in o.data.vertices] if o.get('c3d_garment_category')!='shoes' else None))
 data.append([(b.name,tuple(b.head_local),tuple(b.tail_local)) for b in rig.data.bones])
 return hashlib.sha256(repr(data).encode()).hexdigest()
def checked(parts,rig):
 before=digest(parts,rig)
 weights={o.name:[[(o.vertex_groups[g.group].name,g.weight) for g in v.groups] for v in o.data.vertices] for o in parts if o.get('c3d_garment_category')=='shoes'}
 result=original(parts,rig)
 captured[rig.name]=dict(native_unchanged=before==digest(parts,rig),original_weights=weights)
 return result
mpfb._rigid_sole_weights=checked
result=True
'''
VERIFY='''
from engine.commands import anim,mpfb
rig=bpy.data.objects['Build_rig'];sm=mpfb.RIGIFY_DEF if rig.get('c3d_rig_type')=='rigify' else anim.semantic_map(rig)
captured=mpfb._rigid_sole_weights.__globals__['captured']
errors=[];counts={'rigid':0,'collar':0,'shaft':0};original=captured[rig.name]['original_weights']
for o in rig.children_recursive:
 if o.name not in original:continue
 transform=rig.matrix_world.inverted() @ o.matrix_world
 for v in o.data.vertices:
  p=transform @ v.co;s=min('LR',key=lambda s:(p-rig.data.bones[sm['foot.'+s]].head_local).length_squared)
  foot=rig.data.bones[sm['foot.'+s]];toe=rig.data.bones.get(sm.get('toe.'+s,''));axis=(toe.head_local if toe else foot.tail_local)-foot.head_local;axis.z=0;length=axis.length
  deform={b.name for b in rig.data.bones if b.use_deform};w={o.vertex_groups[g.group].name:g.weight for g in v.groups if o.vertex_groups[g.group].name in deform}
  if p.z<foot.head_local.z+.1*length and abs(sum(w.values())-1)>1e-5:errors.append([o.name,v.index,'normalization'])
  if p.z<=foot.head_local.z-.2*length:
   counts['rigid']+=1
   allowed={sm['foot.'+s],sm.get('toe.'+s,sm['foot.'+s])}
   if any(n not in allowed and weight>1e-6 for n,weight in w.items()):errors.append([o.name,v.index,'non_distal_weight'])
  elif p.z>=foot.head_local.z+.1*length:
   counts['shaft']+=1
   old=dict(original[o.name][v.index]);now={o.vertex_groups[g.group].name:g.weight for g in v.groups}
   if old!=now:errors.append([o.name,v.index,'shaft_changed'])
  else:counts['collar']+=1
result=dict(native_unchanged=captured[rig.name]['native_unchanged'],errors=errors,counts=counts)
'''

def main():
 assert os.environ['CHAR3D_PORT']=='9977';c=BlenderClient();w=Path(c.workspace);report={};began=time.perf_counter()
 if '--resume-failed' in sys.argv:report=json.loads((w/'sole_build_checks.json').read_text())
 try:
  c.call('scene_info')
  environment=c.call('run_python',code="import os,sys\nsys.path.insert(0,os.environ['CHAR3D_QA_SCRIPTS'])\nimport env_report\nresult=env_report.run()\nresult.update(software_gl=os.environ.get('LIBGL_ALWAYS_SOFTWARE'),gallium=os.environ.get('GALLIUM_DRIVER'),threads=bpy.context.scene.render.threads)")['result']
  (w/'blender_environment_v16.json').write_text(json.dumps(environment,indent=2))
  c.call('run_python',code=CAPTURE)
  cases=[(r,'realistic') for r in ('game_engine','rigify','mixamo','default','cmu_mb','default_no_toes')]+[('game_engine',s) for s in ('anime','cartoon','chibi')]
  for rig,style in cases:
   key=rig+'/'+style
   if report.get(key,{}).get('pass'):continue
   try:
    c.call('new_scene');built=c.call('create_realistic_human',name='Build',rig=rig,style=style,gender=1,hair=None,outfit='casual',seed=3,face=False)
    v=c.call('run_python',code=VERIFY)['result'];v['sole_weights']=built['sole_weights'];v['pass']=v['native_unchanged'] and not v['errors'] and bool(v['sole_weights'])
   except Exception as e:v=dict(error=str(e),pass_=False)
   report[key]=v;(w/'sole_build_checks.json').write_text(json.dumps(report,indent=2));print(key,v,flush=True)
  assert all(v.get('pass') for v in report.values()),'See sole_build_checks.json'
  print('SOLE BUILD CONTRACTS OK',time.perf_counter()-began,flush=True)
 finally:c.stop()
if __name__=='__main__':main()
