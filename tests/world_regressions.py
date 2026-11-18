"""Isolated nature/outdoor/cinematic/script sections on 9998, one Blender only.

Video assertions use actual in-process renders + PyAV instead of spawning the
normal background Blender worker. Pixel/codec/frame checks remain meaningful;
this harness does not test background worker startup or render-speed persistence.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))


def environment():
 if os.environ.get('CHAR3D_PORT')!='9998':raise SystemExit('Use isolated port 9998')
 os.environ['CHAR3D_ALLOW_PYTHON']='1';os.environ['CHAR3D_WORKSPACE']=str(ROOT/'output')
 os.environ['XDG_CACHE_HOME']=str(ROOT/'output/cache');os.environ['MESA_SHADER_CACHE_DIR']=str(ROOT/'output/cache/mesa');os.environ['LP_NUM_THREADS']='8'
 os.environ['CHAR3D_RENDER_CALIB']=str(ROOT/'output/world_render_speed.json')


async def section(name):
 import av
 from mcp import ClientSession,StdioServerParameters
 from mcp.client.stdio import stdio_client
 from mcp.types import CallToolResult,TextContent
 from e2e_smoke import _cinematic_checks,_outdoor_checks,_script_scene_checks,isolate_mpfb,text_of
 params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
 async with stdio_client(params) as (reader,writer),ClientSession(reader,writer) as session:
  await session.initialize()
  async def raw(tool,**args):
   result=await session.call_tool(tool,args)
   if result.isError:raise RuntimeError(f'{tool}: {text_of(result)}')
   if tool=='new_scene':
    await isolate_mpfb(session)
    await session.call_tool('run_blender_python',{'code':"bpy.context.scene.render.threads_mode='FIXED'\nbpy.context.scene.render.threads=8\nresult=True"})
   return result
  async def call(tool,**args):
   print('REGRESSION',name,tool,flush=True)
   if tool!='render_video':return await raw(tool,**args)
   start=args.get('frame_start',1);end=args.get('frame_end',24)
   engine='eevee' if args.get('quality')!='draft' else 'workbench';path=ROOT/'output/renders'/args['path'];path.parent.mkdir(exist_ok=True)
   elapsed=time.perf_counter()
   with av.open(str(path),'w') as movie:
    stream=movie.add_stream('libx264',rate=24);stream.width=256;stream.height=144;stream.pix_fmt='yuv420p'
    for index,frame in enumerate(range(start,end+1)):
     result=await raw('render_preview',camera='scene',engine_name=engine,frame=frame,width=256,height=144)
     image_path=json.loads(text_of(result)[0])['path']
     with av.open(image_path) as image:video=next(image.decode(video=0)).reformat(width=256,height=144,format='yuv420p')
     video.pts=index;video.time_base=Fraction(1,24)
     for packet in stream.encode(video):movie.mux(packet)
     print('REGRESSION VIDEO',frame,end,flush=True)
    for packet in stream.encode():movie.mux(packet)
   info={'status':'done','path':str(path),'progress':f'{end-start+1}/{end-start+1}','single_engine':True,
       'learned_speed':{'engine':engine,'seconds_per_frame':(time.perf_counter()-elapsed)/(end-start+1)}}
   return CallToolResult(content=[TextContent(type='text',text=json.dumps(info))])
  try:
   await raw('scene_info')
   if name=='cinematic':await _cinematic_checks(call)
   elif name=='outdoor':await _outdoor_checks(call)
   else:await _script_scene_checks(call,single_engine=True)
   print(name.upper()+' ISOLATED OK (single Blender)',flush=True)
  finally:await raw('engine_shutdown')


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('section',choices=['nature','outdoor','cinematic','script']);args=p.parse_args();environment()
 if args.section=='nature':
  from mcp_server.blender_client import BlenderClient
  from nature_e2e import _nature_checks
  c=BlenderClient()
  try:_nature_checks(c.call);print('NATURE ISOLATED OK',flush=True)
  finally:c.stop()
 else:asyncio.run(section(args.section))
