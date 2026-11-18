"""Run existing isolated sections on port 9997, with one Blender at a time.

The two video assertions use the same native settings/look contexts in-process.
They intentionally do not exercise the background worker lifecycle, which would
require a second concurrent Blender. All other calls/assertions are unchanged.
"""
import argparse
import asyncio
import os
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))


async def main(group):
    if os.environ.get('CHAR3D_PORT')!='9997': raise SystemExit('Use CHAR3D_PORT=9997')
    import e2e_smoke as suite
    env=dict(os.environ,CHAR3D_ALLOW_PYTHON='1',CHAR3D_WORKSPACE=str(ROOT/'output'),
             XDG_CACHE_HOME=str(ROOT/'output/cache'),LP_NUM_THREADS='8')
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=env)
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        async def call(tool,**args):
            if tool=='render_video':
                result=await session.call_tool('run_blender_python',dict(code=f'''
import glob,os,time
from engine import context
from engine.commands.video import _output_size,_apply_settings,QUALITY,ENGINE_KEY,_learn,_model_spf,_scene_weight,_effects_cost
from engine.commands.cinematic import applied_look
from engine.commands.render_style import applied_style
sc=bpy.context.scene;r=sc.render;a={args!r}
quality=a.get('quality','preview');start=a.get('frame_start',sc.frame_start);end=a.get('frame_end',sc.frame_end)
size=_output_size(sc,quality,a.get('width'),a.get('height'),a.get('resolution'),a.get('vertical',False))
path=context.resolve(a['path'],'renders');os.makedirs(os.path.dirname(path),exist_ok=True)
base=os.path.splitext(path)[0]+'_single_'
for stale in glob.glob(base+'*.mp4'): os.remove(stale)
saved=(r.engine,r.resolution_x,r.resolution_y,r.resolution_percentage,r.filepath,r.image_settings.file_format,
       getattr(r.image_settings,'media_type',None),r.fps,r.fps_base,sc.frame_start,sc.frame_end,sc.frame_current,sc.eevee.taa_render_samples)
try:
    _apply_settings(sc,quality,size,a.get('fps'),start,end,base)
    begin=time.perf_counter()
    with applied_look(sc),applied_style(sc): bpy.ops.render.render(animation=True)
    elapsed=time.perf_counter()-begin
    movies=glob.glob(base+'*.mp4')
    assert len(movies)==1,movies
    os.replace(movies[0],path)
    engine,_,samples=QUALITY[quality]
    predicted=_model_spf(engine,samples,round(size[0]*size[2]/100),round(size[1]*size[2]/100),_scene_weight(sc))*_effects_cost(sc,engine)
    learned=_learn(engine,elapsed/(end-start+1),predicted,'nature_single_process_regression',{{'frames':end-start+1}})
    result=dict(path=path,status='done',progress=f'{{end-start+1}}/{{end-start+1}}',bytes=os.path.getsize(path),
                learned_speed=dict(engine=ENGINE_KEY[engine],measurement=learned),single_process=True)
finally:
    r.engine,r.resolution_x,r.resolution_y,r.resolution_percentage,r.filepath=saved[:5]
    if saved[6]: r.image_settings.media_type=saved[6]
    r.image_settings.file_format=saved[5];r.fps,r.fps_base=saved[7:9]
    sc.frame_start,sc.frame_end=saved[9:11];sc.eevee.taa_render_samples=saved[12];sc.frame_set(saved[11])
'''))
                assert not result.isError,(tool,result)
                from mcp.types import CallToolResult,TextContent
                value=json.loads(suite.text_of(result)[0])['result']
                return CallToolResult(content=[TextContent(type='text',text=json.dumps(value))])
            result=await session.call_tool(tool,args)
            # Match the smoke suite's wrapper: expected failures are caught as
            # RuntimeError by its unreachable-goal/invalid-input assertions.
            if result.isError: raise RuntimeError('\n'.join(suite.text_of(result)))
            return result
        if group=='terrain':
            await suite.check_terrain(call,'basic')
            await suite.check_terrain_contact_detection(call)
        elif group=='navigation': await suite.check_obstacle_avoidance(call,'basic')
        elif group=='outdoor': await suite._outdoor_checks(call)
        elif group=='cinematic': await suite._cinematic_checks(call)
        elif group=='seating':
            await session.call_tool('scene_info',{})
            from nature_visuals import setup_code
            await call('run_blender_python',code=setup_code())
            # Enable MPFB before the preceding Rigify cases ask addon_utils to
            # scan/reload packages. A preferences-only import leaves MPFB half
            # initialized in Blender 5.2 when those two addons are interleaved.
            await call('create_realistic_human',name='NatureSeatWarmup',face=False,
                       hair=None,clothes=[])
            await suite._sitting_checks(call)
        await session.call_tool('engine_shutdown',{})
        print('NATURE REGRESSION OK:',group,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('group',choices=['terrain','navigation','outdoor','cinematic','seating'])
    asyncio.run(main(p.parse_args().group))
