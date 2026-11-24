"""Trace visible outsole extremes to native weights; read cached v12 poses only."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mcp_server.blender_client import BlenderClient


def main():
    assert os.environ.get('CHAR3D_PORT')=='9977'
    c=BlenderClient();call=c.call;work=Path(c.workspace);r=json.loads((work/'walk_benchmark_v12.json').read_text());out={}
    try:
        call('scene_info')
        for body in ('male','female_short','male_tall_heavy'):
            case=r['cases'][body+'/straight_1.0'];call('open_project',path=case['project']);call('scene_info')
            extremes=[(f['mesh_low_m'],row['frame'],side) for row in case['rows'] for side,f in row['feet'].items() if 'mesh_low_m' in f]
            flat=[(f['mesh_low_m'],row['frame'],side) for row in case['rows'] for side,f in row['feet'].items() if f['support']=='flat' and 'mesh_low_m' in f]
            selections={'minimum_mesh':min(extremes),'maximum_flat_gap':max(flat),'minimum_flat':min(flat)}
            records={}
            for label,(low,frame,side) in selections.items():
                result=call('run_python',code=f'''
from engine.commands import anim
rig=bpy.data.objects['Gait_rig'];sm=anim.semantic_map(rig)
sc=bpy.context.scene;sc.frame_set({frame})
ankles={{s:(rig.matrix_world @ rig.pose.bones[sm['foot.'+s]].matrix).translation for s in 'LR'}}
records=[]
for shoe in [o for o in sc.objects if o.get('c3d_garment_category')=='shoes']:
 ev=shoe.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh()
 try:
  assert len(me.vertices)==len(shoe.data.vertices), 'Native vertex mapping changed'
  candidates=[(ev.matrix_world @ v.co,v.index) for v in me.vertices]
  point,index=min((v for v in candidates if min('LR',key=lambda s:(v[0]-ankles[s]).length_squared)=={side!r}),key=lambda v:v[0].z)
  native=shoe.data.vertices[index]
  records.append(dict(object=shoe.name,vertex=index,posed_world=list(point),rest_local=list(native.co),
      weights={{shoe.vertex_groups[g.group].name:g.weight for g in native.groups}},
      modifiers=[dict(type=m.type,preserve_volume=getattr(m,'use_deform_preserve_volume',None)) for m in shoe.modifiers]))
 finally:ev.to_mesh_clear()
result=dict(frame={frame},side={side!r},sole_clearance_m=rig.get('c3d_sole_clearance_m'),vertices=records)
''')['result']
                assert any(abs(v['posed_world'][2]-low)<1e-4 for v in result['vertices'])
                records[label]=result
            out[body]=records
        (work/'outsole_weight_diagnostics.json').write_text(json.dumps(out,indent=2)+'\n')
        print('OUTSOLE WEIGHT DIAGNOSTICS WRITTEN',flush=True)
    finally:c.stop()


if __name__=='__main__':main()
