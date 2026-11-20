"""Round 4 visual acceptance over the real MCP interface; offline and port 9971."""
import argparse,asyncio,json,os,sys
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from e2e_smoke import text_of
OUT=ROOT/'output/toon_round4'
CASES=('catalog','details','tones','hair','hair-explicit','garments','podcast','podcast-extra','dark-preview')

def validate_garments():
 import colorsys
 import av,numpy as np
 records=[]
 def hsv(rgb):return np.array(colorsys.rgb_to_hsv(*rgb))
 def difference(a,b):
  a,b=hsv(a),hsv(b);h=abs(a[0]-b[0]);return min(h,1-h),abs(a[2]-b[2])
 for gender,styles in ((0,('anime','cartoon','chibi')),(1,('anime',))):
  reference=json.loads((OUT/'garments'/f'{gender}_realistic.json').read_text())
  for style in styles:
   styled=json.loads((OUT/'garments'/f'{gender}_{style}.json').read_text())
   for region in ('shirt','trousers'):
    albedo=difference(reference['regions'][region]['albedo_srgb'],styled['regions'][region]['albedo_srgb'])
    colors=[]
    for item in (reference,styled):
     with av.open(item['image']) as source:pixels=next(source.decode(video=0)).to_ndarray(format='rgb24')/255
     samples=[]
     for x,y in item['projection'][region]:
      x,y=int(x),int(y)
      if 2<=x<382 and 2<=y<382:samples.extend(pixels[y-1:y+2,x-1:x+2].reshape(-1,3))
     sample=np.array(samples);saturation=(sample.max(1)-sample.min(1))/np.maximum(.001,sample.max(1))
     selected=sample[(saturation>.18)&(sample.max(1)>.08)]
     assert len(selected)>20,(style,region)
     colors.append(np.median(selected,0))
    rendered=difference(*colors)
    record=dict(gender=gender,style=style,region=region,albedo_hue_value_error=albedo,rendered_hue_value_error=rendered,rendered_rgb=[c.tolist() for c in colors])
    records.append(record)
    assert albedo[0]<.02 and albedo[1]<.06,record
    assert rendered[0]<.05 and rendered[1]<.22,record
 (OUT/'garments/colour_checks.json').write_text(json.dumps(records,indent=2));print('TOON GARMENT HUE/VALUE OK',flush=True)

async def run(case):
 assert os.environ.get('CHAR3D_PORT')=='9971'
 params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
 async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
  await session.initialize()
  async def call(name,**kwargs):
   print('ROUND4',case,name,flush=True);value=await session.call_tool(name,kwargs)
   assert not value.isError,text_of(value);return [json.loads(t) for t in text_of(value)]
  try:
   await call('scene_info')
   common=f"import sys\nsys.path.insert(0,{str(ROOT/'tests')!r})\nimport toon_round4_fixture as fixture\n"
   if case=='catalog':code=f"result=[fixture.matrix('after',tone,{str(OUT)!r}) for tone in ('medium','dark')]"
   elif case=='details':code=f"result=fixture.details('after',{str(OUT)!r})"
   elif case=='tones':code=f"result=fixture.controlled_tones({str(OUT)!r})"
   elif case in ('hair','hair-explicit'):code=f"result=fixture.hair_views({str(OUT)!r},explicit={case=='hair-explicit'})"
   elif case=='garments':code=f"result=[fixture.garment_case(style,gender,{str(OUT)!r}) for gender in (0,1) for style in (('realistic','anime','cartoon','chibi') if gender==0 else ('realistic','anime'))]"
   elif case=='podcast':code=f"result=fixture.podcast({str(OUT)!r})"
   elif case=='podcast-extra':code=f"result=fixture.podcast_extra({str(OUT)!r})"
   elif case=='dark-preview':code=f"result=fixture.dark_preview({str(OUT)!r})"
   result=await call('run_blender_python',code=common+code)
   if case=='garments':validate_garments()
   (OUT/(case+'_mcp.json')).write_text(json.dumps(result,indent=2));print('ROUND4 CASE OK',case,flush=True)
  finally:await session.call_tool('engine_shutdown',{})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--case',choices=(*CASES,'all'),default='all');args=p.parse_args()
 for case in CASES if args.case=='all' else (args.case,):asyncio.run(run(case))
