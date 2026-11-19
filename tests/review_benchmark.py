"""Time the current reviewer against the saved two-MPFB fault fixture at exactly 30 s."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]


async def main():
    if os.environ.get('CHAR3D_PORT')!='9973':raise SystemExit('Use isolated port 9973')
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ,CHAR3D_ALLOW_PYTHON='1'))
    report={}
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        async def call(tool,**args):
            if tool=='render_video':
                from serial_video import render
                response=await render(session,args)
            else:
                response=await session.call_tool(tool,args)
            if response.isError:raise RuntimeError(str(response.content))
            return json.loads(next(c.text for c in response.content if c.type=='text'))
        try:
            await call('scene_info');await call('open_project',path='review_fault.blend')
            await call('set_timeline',frame_end=720)
            for level in ('quick','standard'):
                report[level]=await call('review_scene',level=level,size=384)
                assert report[level]['duration_s']==30
                print(level,report[level]['timings'],flush=True)
            report['fix']=await call('review_scene',level='standard',size=384,fix=True)
            prop=await call('add_prop',kind='book')
            await call('hold_prop',character='Ana_rig',prop=prop['root'],start_frame=300)
            await call('camera_shot',subject=['Ana_rig'],shot='full',start_frame=280,end_frame=330,name='ActionCheck')
            report['action']=await call('review_scene',level='standard',size=256,frames=[300])
            assert report['action']['strips']
            report['credits_card']=await call('credits',path='review_card/CREDITS.txt',card=True)
            card_end=(await call('scene_info'))['frame_range'][1]
            await call('credits',path='review_card/CREDITS.txt',card=True)
            assert (await call('scene_info'))['frame_range'][1]==card_end
            report['card_still']=await call('render_frames',frames=[card_end-36],camera='scene',size=256)
            report['optout_video']=await call('render_video',path='review_optout/draft.mp4',quality='draft',width=320,height=180,frame_start=1,frame_end=24,wait=True,credits=False)
            assert not (ROOT/'output/renders/review_optout/CREDITS.txt').exists()
            (ROOT/'output/review_benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print('REVIEW BENCHMARK OK',flush=True)
        finally:await session.call_tool('engine_shutdown',{})


if __name__=='__main__':asyncio.run(main())
