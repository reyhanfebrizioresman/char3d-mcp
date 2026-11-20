"""Low-memory, one-engine visual review of saved collision milestones on 9970.

Run after e2e_smoke.py --collide-only. Opening native projects avoids loading
MPFB's authoring addon into the render session. No second Blender worker.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/collide'


def sheet(items,path,size=384):
    # Use the installed image tool without adding packages to the shared venv.
    args=['magick','montage','-background','#181a1e','-fill','white',
          '-font','DejaVu-Sans','-pointsize','14']
    for item in items:args+=['-label',item['label'],item['path']]
    subprocess.run(args+['-tile','2x','-geometry',f'{size}x{size}+0+4',str(path)],check=True)


async def main(args):
    if os.environ.get('CHAR3D_PORT')!='9970':
        raise RuntimeError('Use only CHAR3D_PORT=9970')
    if Path(os.environ.get('CHAR3D_WORKSPACE','')).resolve()!=ROOT/'output':
        raise RuntimeError('Use this worktree output workspace')
    if (OUT/'images.json').exists():
        images=json.loads((OUT/'images.json').read_text())
        sheet(images,OUT/'contact_sheet.png')
    if args.sheet_only:return
    os.environ.setdefault('MESA_SHADER_CACHE_DIR',str(ROOT/'output/mesa_collide'))
    cases={'energetic':('DeskActor_rig',55,'medium',40),
           'drink':('Action_rig',27,'close_up',-35),
           'hug':(['Short_rig','Tall_rig'],15,'medium',90),
           'skirt_seat':('Skirt_rig',40,'medium_full',90)}
    records=json.loads((OUT/'visuals.json').read_text()) if (OUT/'visuals.json').exists() else []
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ,CHAR3D_ALLOW_PYTHON='1'))
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        async def call(tool,**kwargs):
            result=await session.call_tool(tool,kwargs)
            text=[c.text for c in result.content if c.type=='text']
            if result.isError:raise RuntimeError(tool+': '+str(text))
            return json.loads(text[0])
        try:
            await call('scene_info')
            for name,(rig,frame,shot,angle) in cases.items():
                if args.case and args.case!=name:continue
                for suffix in ('before','after'):
                    project=name+('_before' if suffix=='before' else '')
                    await call('open_project',path='collide/'+project+'.blend')
                    await call('scene_info')
                    await call('run_blender_python',code="""
sc=bpy.context.scene
sc.render.resolution_x=sc.render.resolution_y=448
sc.render.resolution_percentage=100
sc.render.threads_mode='FIXED';sc.render.threads=2
sc.eevee.taa_render_samples=4
sc.eevee.shadow_pool_size='64'
sc.eevee.use_raytracing=False
sc.render.use_simplify=True
sc.render.simplify_subdivision_render=0
result=True
""")
                    subjects=rig if isinstance(rig,list) else [rig]
                    await call('set_lighting',preset='studio',subject=subjects,follow=False)
                    await call('camera_shot',subject=subjects,shot=shot,angle=angle,
                               start_frame=frame,end_frame=frame+1,avoid_occlusion=False,name='CollisionEvidence')
                    started=time.perf_counter()
                    item=await call('render_frames',frames=[frame],camera='scene',engine_name='eevee',size=448,
                                    subtitles=False,graphics=False)
                    target=OUT/(name+'_'+suffix+'_eevee.png')
                    shutil.copy2(item['path'],target)
                    record=dict(label=name+' '+suffix,path=str(target),seconds=round(time.perf_counter()-started,3),frame=frame)
                    records=[p for p in records if p['label']!=record['label']]+[record]
                    (OUT/'visuals.json').write_text(json.dumps(records,indent=2))
                    print('COLLIDE EEVEE',record,flush=True)
                    sheet(records,OUT/'eevee_contact_sheet.png',448)
        finally:
            await session.call_tool('engine_shutdown',{})
    print('COLLIDE VISUALS OK',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=['energetic','drink','hug','skirt_seat'])
    parser.add_argument('--sheet-only',action='store_true')
    asyncio.run(main(parser.parse_args()))
