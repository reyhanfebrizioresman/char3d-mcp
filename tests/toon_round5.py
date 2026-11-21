"""Matched midface diagnostics and contracts. Offline; owned engine 9971 only."""
import argparse,asyncio,json,os,sys
from pathlib import Path
import numpy as np
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from e2e_smoke import text_of
from toon_polish import read
from toon_round4b import board
OUT=ROOT/'output/toon_round5'

async def run(args):
    assert os.environ.get('CHAR3D_PORT')=='9971'
    OUT.mkdir(parents=True,exist_ok=True)
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        try:
            response=await session.call_tool('scene_info',{});assert not response.isError,text_of(response)
            common=f'import sys\nsys.path.insert(0,{str(ROOT/"tests")!r})\nimport toon_round5_fixture as fixture\n'
            if args.case=='polish':code=f'result=fixture.run({str(OUT)!r},phase="after",tones=("light",),genders=(0,),angles=(0,))\nfixture.articulation({str(OUT)!r},only="smile")'
            elif args.case=='pilot':code=f'result=fixture.run({str(OUT)!r},phase="after",tones=("dark",),genders=(0,),pilot=True)\nfixture.ablation({str(OUT)!r})\nfixture.refresh_geometry({str(OUT)!r})'
            elif args.case=='colour':code=f'fixture.style_identity({str(OUT)!r})\nimport toon_round4b_fixture\nresult=toon_round4b_fixture.matrix({str(OUT/"colour")!r},project_prefix="round5/colour")'
            elif args.case in ('ablation','articulation','refresh_geometry'):code=f'result=fixture.{args.case}({str(OUT)!r})'
            else:code=f'result=fixture.run({str(OUT)!r},phase={args.case!r},tones={((args.tone,) if args.tone else ("light","medium","dark"))!r},genders={((args.gender,) if args.gender is not None else (0,1))!r},pilot={args.pilot!r})'
            response=await session.call_tool('run_blender_python',{'code':common+code});assert not response.isError,text_of(response)
            (OUT/f'{args.case}_mcp.json').write_text(json.dumps(text_of(response),indent=2));print('ROUND5 CASE OK',args.case,flush=True)
        finally:await session.call_tool('engine_shutdown',{})


def shadow(case,reference=None):
    data=np.load((reference or case)['surface']);pixels=read(Path(case['path']))/255;y=pixels@[.2126,.7152,.0722]
    # Gaussian local contrast detects narrow dark valleys, independently of overall pigment.
    kernel=np.exp(-.5*(np.arange(-9,10)/3.)**2);kernel/=kernel.sum()
    blur=y.copy()
    for axis in (0,1):blur=np.apply_along_axis(lambda v:np.convolve(np.pad(v,9,mode='reflect'),kernel,mode='valid'),axis,blur)
    report={}
    for name in ('groove','cheek','nose','bridge'):
        uv=np.rint(data['pixels'][data[name]]).astype(int);uv=uv[(uv[:,0]>9)&(uv[:,0]<502)&(uv[:,1]>9)&(uv[:,1]<502)]
        # Cover between-vertex pixels and a three-pixel feature displacement;
        # a shadow cannot pass merely by moving off the original vertex sample.
        mask=np.zeros(y.shape,bool)
        for dx in range(-3,4):
            for dz in range(-3,4):
                if dx*dx+dz*dz<=9:mask[uv[:,1]+dz,uv[:,0]+dx]=True
        z,x=np.nonzero(mask);val=np.maximum(0,blur[z,x]-y[z,x])/np.maximum(.05,blur[z,x])
        report[name]=dict(local_shadow_mean=float(val.mean()),local_shadow_p90=float(np.percentile(val,90)),Yprime=float(y[z,x].mean()),sample_pixels=int(mask.sum()))
    return report


def check(enforce=True):
    records={phase:json.loads((OUT/phase/'matrix.json').read_text())['cases'] for phase in ('before','after')};metrics=[]
    assert all(len(cases)==12 for cases in records.values())
    for before in records['before']:
        key=lambda c:(c['tone'],c['gender'],c['view'])
        after=next(c for c in records['after'] if key(c)==key(before))
        a,b=shadow(before),shadow(after,reference=before)
        # Main acceptance is the nose/lower-face ROI requested for this round.
        # The separate bridge diagnostic extends above the eyes into glabella/
        # brow shading and is reported independently, rather than hidden.
        crease=lambda values:np.mean([values[n]['local_shadow_p90'] for n in ('groove','nose')])
        reduction=1-float(crease(b)/crease(a))
        old=np.load(before['surface']);new=np.load(after['surface'])
        from engine.toon import LID_PAIRS
        rims=sorted({i for pairs in LID_PAIRS.values() for pair in pairs for i in pair})
        rim_error=float(abs(new['points'][rims]-old['points'][rims]).max())
        xz_error=float(abs(new['points'][:,[0,2]]-old['points'][:,[0,2]]).max())
        p=new['points'];h=float(new['head_height']);tip_z=p[294,2]
        tip=new['nose']&(abs(p[:,0])<.025*h)&(abs(p[:,2]-tip_z)<.03*h)
        flank=new['groove']&(abs(p[:,0])>.08*h)&(abs(p[:,0])<.16*h)&(abs(p[:,2]-tip_z)<.03*h)
        prominence=float((np.median(p[flank,1])-p[tip,1].min())/h)
        def bridge_lead(data):
            q=data['points'];head=float(data['head_height']);eye=q[[24,66,6808,6850]].mean(0)
            region=data['nose']&(q[:,2]>q[294,2]+.045*head)&(q[:,2]<eye[2]-.02*head)
            return float((q[294,1]-q[region,1].min())*1000)
        bridge_before,bridge_after=bridge_lead(old),bridge_lead(new)
        record=dict(tone=before['tone'],gender=before['gender'],view=before['view'],before=a,after=b,
                    crease_reduction=reduction,lid_rim_error_m=rim_error,lip_and_body_XZ_error_m=xz_error,
                    nose_tip_prominence_head=prominence,
                    bridge_ahead_tip_mm_before=bridge_before,bridge_ahead_tip_mm_after=bridge_after,
                    geometry_before=before['geometry'],geometry_after=after['geometry'])
        metrics.append(record)
        if enforce:
            assert reduction>=.25,record
            assert rim_error<1e-7 and xz_error<1e-7,record
            assert after['correction']==dict(rest=2,motion=2),after['correction']
            assert prominence>.006 and b['nose']['local_shadow_p90']>.005,record
            assert bridge_after<0,record
    if enforce:assert np.mean([c['crease_reduction'] for c in metrics])>=.40
    (OUT/'metrics.json').write_text(json.dumps(metrics,indent=2))
    probe=next(c for c in records['before'] if (c['tone'],c['gender'],c['view'])==('dark',0,'three_quarter'))
    baseline=read(OUT/'diagnosis/default.png').astype(float)/255
    ablations=[]
    for name in ('default','no_AO','no_form','no_AO_form','anime'):
        path=OUT/'diagnosis'/f'{name}.png';pixels=read(path).astype(float)/255
        ablations.append(dict(case=name,shadow=shadow({**probe,'path':str(path)},reference=probe),
                              face_rgb_mae=float(abs(pixels[205:410,125:300]-baseline[205:410,125:300]).mean())))
    (OUT/'diagnosis/metrics.json').write_text(json.dumps(ablations,indent=2))
    for view in ('front','three_quarter'):
        rows=[]
        for tone in ('light','medium','dark'):
            for gender in (0,1):
                rows.append([(f'{phase} {tone} {"F" if gender==0 else "M"} {view}',next(c['path'] for c in records[phase] if (c['tone'],c['gender'],c['view'])==(tone,gender,view))) for phase in ('before','after')])
        board(OUT/f'{view}.png',rows,cell=(512,512))
    rows=[]
    for tone in ('light','medium','dark'):
        for gender in (0,1):
            actor=[]
            for view in ('front','three_quarter'):
                actor.append([(f'{phase} {tone} {"F" if gender==0 else "M"} {view}',
                    next(c['path'] for c in records[phase] if (c['tone'],c['gender'],c['view'])==(tone,gender,view))) for phase in ('before','after')])
            rows.append(actor[0]+actor[1]);board(OUT/f'{tone}_{gender}_comparison.png',actor,cell=(512,512))
    board(OUT/'comparison.png',rows,cell=(512,512))
    articulation=json.loads((OUT/'articulation/metrics.json').read_text())
    board(OUT/'expressions.png',[[(c['name'],c['path']) for c in articulation['states'] if c['name'] in ('neutral','smile','A','O','M')]],cell=(512,512))
    import toon_round4b as colour
    previous=colour.OUT
    try:
        colour.OUT=OUT/'colour';colours=colour.metrics()
    finally:colour.OUT=previous
    board(OUT/'colour.png',[[(tone+' '+s,OUT/'colour/after'/f'{tone}_{s}.png') for s in ('realistic','anime','animated_film')] for tone in ('light','medium','dark')])
    identity=[]
    for tone in ('light','medium','dark'):
        old=read(ROOT/'output/toon_round4b/after'/f'{tone}_realistic.png')
        new=read(OUT/'colour/after'/f'{tone}_realistic.png')
        error=float(abs(old.astype(float)-new.astype(float)).mean())
        identity.append(dict(tone=tone,rgb_byte_mae=error,pixel_identical=bool(np.array_equal(old,new))))
        if enforce:assert np.array_equal(old,new),identity[-1]
    (OUT/'realistic_identity.json').write_text(json.dumps(identity,indent=2))
    print('TOON ROUND5 FACE OK',len(metrics),'cases; mean crease reduction',np.mean([c['crease_reduction'] for c in metrics]))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=('before','after','check','ablation','articulation','refresh_geometry','colour','pilot','polish'),default='check');parser.add_argument('--tone',choices=('light','medium','dark'));parser.add_argument('--gender',type=int,choices=(0,1));parser.add_argument('--pilot',action='store_true');args=parser.parse_args()
    check() if args.case=='check' else asyncio.run(run(args))
