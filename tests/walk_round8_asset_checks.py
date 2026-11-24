"""Check cached walk assets retain native geometry, weights, rests and materials."""
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mcp_server.blender_client import BlenderClient

AUDIT = '''
import hashlib
rig=bpy.data.objects['Gait_rig']
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
records={}
for ob in meshes:
    me=ob.data
    data=[[(tuple(v.co),[(g.group,g.weight) for g in v.groups]) for v in me.vertices],
          [tuple(p.vertices) for p in me.polygons],
          [(k.name,[tuple(v.co) for v in k.data]) for k in me.shape_keys.key_blocks] if me.shape_keys else [],
          [(b.name,tuple(b.head_local),tuple(b.tail_local)) for b in rig.data.bones],
          [m.name if m else None for m in me.materials]]
    records[ob.name]=dict(vertices=len(me.vertices),triangles=sum(len(p.vertices)-2 for p in me.polygons),
                          native_sha256=hashlib.sha256(repr(data).encode()).hexdigest())
result=records
'''

QA = '''
import sys
sys.path.insert(0,'/home/reyhan/.codex/skills/blender-asset-qa/scripts')
import qa_check
bpy.context.scene.frame_set(bpy.context.scene.frame_end)
rig=bpy.data.objects['Gait_rig']
objects=[o.name for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
result=qa_check.run(objects=objects,profile='render')
'''


def main():
    assert os.environ.get('CHAR3D_PORT') == '9977'
    engine=BlenderClient(); call=engine.call; work=Path(engine.workspace); report={}
    try:
        call('scene_info')
        environment=call('run_python',code="import os\nresult=dict(blender=bpy.app.version_string,software_gl=os.environ.get('LIBGL_ALWAYS_SOFTWARE'),gallium=os.environ.get('GALLIUM_DRIVER'))")['result']
        assert environment['software_gl']=='1' and environment['gallium']=='llvmpipe',environment
        for body in ('male','female_short','male_tall_heavy'):
            parts={}
            for label,project in [('rest',f'{body}_rest.blend'),
                                  ('baseline',f'v9_{body}_straight_1.0.blend'),
                                  ('walk',f'v10_{body}_straight_1.0.blend')]:
                call('open_project',path=project); call('scene_info')
                parts[label]=call('run_python',code=AUDIT)['result']
                if label != 'rest':
                    parts['baseline_qa' if label=='baseline' else 'qa']=call('run_python',code=QA)['result']
            assert parts['rest'] == parts['walk'], body
            assert parts['baseline'] == parts['walk'],body
            # Round 7 already records inherited native MPFB alpha/helper overlap
            # and a shared albedo/bump image. Preserve absolute QA verbatim,
            # and gate this motion change on new categories, not on relabelling
            # those existing findings as clean geometry. Counts remain visible.
            def categories(qa):
                return {re.sub(r'\(\d+ overlapping coplanar tri pairs\)', '(coplanar)',e) for e in qa['errors']}
            parts['new_error_categories']=sorted(categories(parts['qa'])-categories(parts['baseline_qa']))
            parts['regression_pass']=not parts['new_error_categories']
            report[body]=parts
            print('NATIVE DATA UNCHANGED',body,flush=True)
            print('QA',body,json.dumps({k:parts['qa'][k] for k in ('pass','errors','warnings')}),flush=True)
        (work/'asset_qa.json').write_text(json.dumps(dict(environment=environment,assets=report),indent=2))
        assert all(v['regression_pass'] for v in report.values())
        print('ROUND8 ASSET REGRESSION OK (absolute native QA findings retained)',flush=True)
    finally:
        engine.stop()


if __name__=='__main__': main()
