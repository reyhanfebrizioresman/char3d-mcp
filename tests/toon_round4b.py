"""Scan-colour review through MCP, CPU only, offline, own port 9971."""
import argparse,asyncio,colorsys,json,os,sys
from pathlib import Path
import av
import numpy as np
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from e2e_smoke import text_of
from toon_polish import read,save,label,FONT
OUT=ROOT/'output/toon_round4b'
TONES=('light','medium','dark');LABELS=('realistic','anime','animated_film')


def metrics(phase='after',enforce=True):
    report=json.loads((OUT/phase/'matrix.json').read_text());records=[]
    for case in report['cases']:
        pixels=read(Path(case['path']))/255
        x,y=map(int,case['projection']['sites'][1]);patch=pixels[y-4:y+5,x-4:x+5]
        rgb=patch.mean((0,1));hsv=colorsys.rgb_to_hsv(*rgb)
        records.append(dict(tone=case['tone'],label=case['label'],rgb=rgb.tolist(),hsv=list(hsv),
                            Yprime=float(rgb@[.2126,.7152,.0722]),roi=[x-4,y-4,x+5,y+5],path=case['path']))
    checks=[]
    for tone in TONES:
        reference=next(r for r in records if (r['tone'],r['label'])==(tone,'realistic'))
        for style in LABELS[1:]:
            current=next(r for r in records if (r['tone'],r['label'])==(tone,style))
            delta=abs(current['hsv'][0]-reference['hsv'][0]);delta=min(delta,1-delta)
            saturation=current['hsv'][1]/reference['hsv'][1]
            check=dict(tone=tone,label=style,hue_error_turns=delta,saturation_ratio=saturation,
                       luminance_difference=current['Yprime']-reference['Yprime'])
            checks.append(check)
            if enforce:
                assert delta<=.04,check
                assert saturation>=.75,check
                assert current['Yprime']<=reference['Yprime']+.035,check
                if tone=='dark':assert current['Yprime']>=.33,check
                if tone=='light':assert current['Yprime']<.90,check
    for style in LABELS:
        values=[next(r['Yprime'] for r in records if (r['tone'],r['label'])==(t,style)) for t in TONES]
        if enforce:assert values[0]>values[1]+.02 and values[1]>values[2]+.02,(style,values)
    result=dict(records=records,checks=checks,limits=dict(hue=.04,saturation_ratio=.75,tone_gap=.02,
                luminance_lift_tolerance=.035,dark_floor=.33,light_ceiling=.90))
    (OUT/phase/'colour.json').write_text(json.dumps(result,indent=2))
    return result


def board(path,rows,cell=(384,384)):
    w,h=cell;canvas=np.full((len(rows)*(h+26),max(map(len,rows))*w,3),28,np.uint8)
    for row,items in enumerate(rows):
        for col,(title,file) in enumerate(items):
            pixels=read(Path(file));pixels=av.VideoFrame.from_ndarray(pixels,format='rgb24').reformat(width=w,height=h).to_ndarray(format='rgb24')
            canvas[row*(h+26)+26:(row+1)*(h+26),col*w:(col+1)*w]=pixels
            label(canvas,title[:w//12],col*w+5,row*(h+26)+5)
    save(path,canvas)


def sheets():
    board(OUT/'comparison.png',[[ (tone+' '+style,OUT/'after'/f'{tone}_{style}.png') for style in LABELS] for tone in TONES])
    board(OUT/'catalog_before_after.png',[[ (phase+' '+tone,OUT/phase/f'{tone}_anime.png') for tone in TONES] for phase in ('before','after')])
    board(OUT/'garments.png',[[('female '+s,OUT/f'garments/0_{s}.png') for s in ('realistic','anime','cartoon','chibi')],[('male '+s,OUT/f'garments/1_{s}.png') for s in ('realistic','anime')]])


def native_metrics(result):
    data=result[0]['result']
    expected=read(OUT/'after/medium_animated_film.png')/255
    reopened=read(Path(data['reopened']))/255
    error=float(abs(expected-reopened).mean());assert error<.01,error
    report=json.loads((OUT/'after/matrix.json').read_text())
    projection=next(c['projection'] for c in report['cases'] if (c['tone'],c['label'])==('medium','anime'))
    x,y=map(int,projection['sites'][1]);plain=read(Path(data['plain']))/255
    rgb=plain[y-4:y+5,x-4:x+5].mean((0,1));hsv=colorsys.rgb_to_hsv(*rgb)
    reference=next(c for c in metrics()['records'] if (c['tone'],c['label'])==('medium','realistic'))
    delta=abs(hsv[0]-reference['hsv'][0]);delta=min(delta,1-delta)
    assert delta<=.04,(hsv,reference)
    assert hsv[1]>=.75*reference['hsv'][1],(hsv,reference)
    luminance=float(rgb@[.2126,.7152,.0722]);assert luminance<=reference['Yprime']+.035,(luminance,reference)
    mono=read(Path(data['monochrome']))/255
    chroma=float(np.mean(mono.max(2)-mono.min(2)));assert chroma<.02,chroma
    record=dict(reopened_rgb_mae=error,plain_rgb=rgb.tolist(),plain_hsv=list(hsv),plain_Yprime=luminance,
                monochrome_mean_chroma=chroma,aovs_preserved=data['aovs_preserved'])
    (OUT/'native_checks.json').write_text(json.dumps(record,indent=2))
    print('TOON NATIVE COLOUR OK',flush=True)


async def run(case,tone=None):
    assert os.environ.get('CHAR3D_PORT')=='9971'
    OUT.mkdir(parents=True,exist_ok=True)
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        async def call(name,**args):
            print('ROUND4B',case,name,flush=True);response=await session.call_tool(name,args)
            assert not response.isError,text_of(response)
            return [json.loads(t) for t in text_of(response)]
        try:
            await call('scene_info')
            common=f"import sys\nsys.path.insert(0,{str(ROOT/'tests')!r})\nimport toon_round4b_fixture as fixture\n"
            if case=='garments':code=f'result=fixture.garments({str(OUT)!r})'
            elif case=='dark-refresh':code=f'result=fixture.refresh_dark({str(OUT)!r})'
            elif case=='native':code=f'result=fixture.native_check({str(OUT)!r})'
            else:code=f'result=fixture.matrix({str(OUT)!r},phase={case!r},tones={((tone,) if tone else TONES)!r})'
            result=await call('run_blender_python',code=common+code)
            if case=='native':native_metrics(result)
            (OUT/(case+('_'+tone if tone else '')+'_mcp.json')).write_text(json.dumps(result,indent=2))
            print('ROUND4B CASE OK',case,tone,flush=True)
        finally:await session.call_tool('engine_shutdown',{})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=('before','after','garments','check','dark-refresh','native'),default='check');parser.add_argument('--tone',choices=TONES)
    args=parser.parse_args()
    if args.case=='check':metrics();sheets();print('TOON SCAN COLOUR OK')
    else:asyncio.run(run(args.case,args.tone))
