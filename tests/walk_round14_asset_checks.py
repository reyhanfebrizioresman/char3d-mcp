"""R14 native identity gate: only footwear deform weights may change."""
import json, os, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient

AUDIT='''
import hashlib,json
rig=bpy.data.objects['Gait_rig'];records={}
def digest(x):return hashlib.sha256(repr(x).encode()).hexdigest()
for ob in rig.children_recursive:
 if ob.type!='MESH':continue
 me=ob.data;groups={g.index:g.name for g in ob.vertex_groups}
 native=[[(tuple(v.co)) for v in me.vertices],[tuple(p.vertices) for p in me.polygons],
         [(k.name,[tuple(v.co) for v in k.data]) for k in me.shape_keys.key_blocks] if me.shape_keys else [],
         [(b.name,tuple(b.head_local),tuple(b.tail_local)) for b in rig.data.bones],
         [m.name if m else None for m in me.materials],
         [[tuple(d.uv) for d in uv.data] for uv in me.uv_layers]]
 weights=[sorted((groups[g.group],g.weight) for g in v.groups) for v in me.vertices]
 deform={b.name for b in rig.data.bones if b.use_deform}
 nondeform=[[(n,w) for n,w in v if n not in deform] for v in weights]
 records[ob.name]=dict(native=digest(native),weights=digest(weights),nondeform=digest(nondeform),
    category=ob.get('c3d_garment_category'),sole=ob.get('c3d_rigid_sole'),
    vertices=len(me.vertices),triangles=sum(len(p.vertices)-2 for p in me.polygons))
result=records
'''
QA='''
import os,sys
sys.path.insert(0,os.environ['CHAR3D_QA_SCRIPTS'])
import qa_check
rig=bpy.data.objects['Gait_rig']
objects=[o.name for o in rig.children_recursive if o.type=='MESH' and not o.hide_render]
result=qa_check.run(objects=objects,profile='render')
'''

def main():
 assert os.environ['CHAR3D_PORT']=='9977'
 c=BlenderClient();w=Path(c.workspace);report={}
 candidate=os.environ.get('CHAR3D_WALK_LABEL','v16')
 try:
  c.call('scene_info')
  for body in ('male','female_short','male_tall_heavy'):
   records={};errors=[];qa={}
   for label,path in [('v13',w/'baseline/projects'/f'{body}_rest.blend'),(candidate,w/'projects'/f'{body}_rest.blend'),('walk',w/'projects'/f'{candidate}_{body}_straight_1.0.blend')]:
    c.call('open_project',path=str(path));c.call('scene_info')
    records[label]=c.call('run_python',code=AUDIT)['result']
   old,new=records['v13'],records[candidate]
   if set(old)!=set(new):errors.append('object_inventory')
   for name in old.keys() & new.keys():
    a,b=old[name],new[name]
    if a['native']!=b['native']:errors.append(name+':native_geometry_rest_uv_materials')
    if a['nondeform']!=b['nondeform']:errors.append(name+':nondeform_groups')
    if a['weights']!=b['weights'] and b['category']!='shoes':errors.append(name+':nonshoe_weights')
   if new!=records['walk']:errors.append('walk_mutated_native_data')
   case=json.loads((w/f'walk_benchmark_{candidate}.json').read_text())['cases'][body+'/straight_1.0']
   step=next(s for s in case['steps'] if s['complete_cycle'] and s['land']>20)
   for label in ('v13',candidate):
    path=(w/'baseline/projects' if label=='v13' else w/'projects')/f'{label}_{body}_straight_1.0.blend'
    c.call('open_project',path=str(path));c.call('scene_info');qa[label]={}
    for phase,f in [('heel_strike',step['land']),('mid_stance',step['phases']['mid_stance']['frame']),('toe_off',step['phases']['toe_off']['frame'])]:
     c.call('run_python',code=f'bpy.context.scene.frame_set({f})\nresult=True')
     qa[label][phase]=c.call('run_python',code=QA)['result']
   def categories(q):return {re.sub(r'\(\d+ overlapping coplanar tri pairs\)','(coplanar)',s) for s in q['errors']}
   added={p:sorted(categories(qa[candidate][p])-categories(qa['v13'][p])) for p in qa[candidate]}
   report[body]=dict(native=records,qa=qa,native_errors=errors,new_error_categories=added,
                      regression_pass=not errors and not any(added.values()))
   (w/f'asset_qa_{candidate}.json').write_text(json.dumps(report,indent=2))
   print(body,'NATIVE',errors,'QA',added,flush=True)
  assert all(v['regression_pass'] for v in report.values()),'See asset_qa_v16.json'
  print('R14 ASSET REGRESSION OK: footwear weights only',flush=True)
 finally:c.stop()

if __name__=='__main__':main()
