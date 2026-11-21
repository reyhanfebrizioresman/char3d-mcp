"""Offline owner-audit reproduction; owns one MCP engine on 9971."""
import argparse,asyncio,json,os,sys,struct,zlib,hashlib,subprocess
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from e2e_smoke import text_of
OUT=ROOT/'output/toon_round6'


def baseline_sources():
    """Read pinned git blobs; never rewrite the working tree or git metadata."""
    out=OUT/'baseline_code';out.mkdir(parents=True,exist_ok=True);report={}
    for filename,source in [('toon_commands.py','engine/commands/toon.py'),('render_style.py','engine/commands/render_style.py')]:
        blob=subprocess.run(['git','show','c7720c9:'+source],cwd=ROOT,capture_output=True,check=True).stdout
        path=out/filename
        if path.exists():assert path.read_bytes()==blob,('Baseline source differs from c7720c9',path)
        else:path.write_bytes(blob)
        report[source]=hashlib.sha256(blob).hexdigest()
    (out/'provenance.json').write_text(json.dumps(dict(commit='c7720c9',sha256=report),indent=2))


def reusable_cells(phase):
    from toon_polish import read
    from toon_round6_fixture import CASES,source_signature
    path=OUT/phase/'matrix.json'
    if not path.exists():return []
    expected={c[0]:c for c in CASES};valid=[]
    for c in json.loads(path.read_text())['cases']:
        name=c['name'];spec=expected.get(name)
        if not spec or (c['body_style'],c['hair'])!=(spec[3],spec[4]):continue
        if phase=='after' and c.get('source_signature')!=source_signature():continue
        try:
            raw=Path(c['path']).read_bytes();assert raw[-12:]==b'\x00\x00\x00\x00IEND\xaeB`\x82'
            offset=8
            while offset<len(raw):
                size=struct.unpack_from('>I',raw,offset)[0];chunk=raw[offset+4:offset+8+size]
                assert zlib.crc32(chunk)&0xffffffff==struct.unpack_from('>I',raw,offset+8+size)[0]
                offset+=12+size
            assert read(Path(c['path'])).shape==(256,256,3)
            valid.append([name,c['angle'],c['look'],c['style']])
        except Exception:pass
    return valid

async def run(args):
    assert os.environ.get('CHAR3D_PORT')=='9971'
    if args.case=='before' or args.phase=='before':baseline_sources()
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (r,w),ClientSession(r,w) as s:
        await s.initialize()
        try:
            r=await s.call_tool('scene_info',{});assert not r.isError,text_of(r)
            names=[args.name or 'dark_M'] if args.case in ('diagnostic','articulation','colour','mouth_diagnostic','ray_probe','pilot','looks','hair','shade_probe') else [args.name] if args.name else [f'{t}_{g}' for t in ('light','medium','dark') for g in ('F','M')]
            if args.case=='articulation' and args.all_characters:
                from toon_round6_fixture import CASES
                names=[c[0] for c in CASES]
            skip=reusable_cells(args.case) if args.resume else []
            for name in names:
                data=json.loads((OUT/args.case/'matrix.json').read_text()) if (OUT/args.case/'matrix.json').exists() else {'cases':[]}
                annotated=all('face_polygon' in c for c in data['cases'] if c['name']==name)
                if annotated and sum(k[0]==name for k in skip)==12 and (ROOT/'output/projects/round6'/f'{args.case}_{name}.blend').exists():
                    print('ROUND6 REUSE',args.case,name,flush=True);continue
                code=f'import sys\nfrom pathlib import Path\nsys.path.insert(0,{str(ROOT/"tests")!r})\nimport toon_round6_fixture as fixture\n'
                if args.case=='before' or (args.case in ('articulation','looks') and args.phase=='before'):
                    code+=f'import engine.commands.toon as toon\nimport engine.commands.render_style as style\nexec(Path({str(OUT/"baseline_code/toon_commands.py")!r}).read_text(),toon.__dict__)\nexec(Path({str(OUT/"baseline_code/render_style.py")!r}).read_text(),style.__dict__)\n'
                if args.case=='shade_probe':code+=f'result=fixture.sampled(fixture.shade_probe,{str(OUT)!r})'
                elif args.case=='looks':code+=f'result=fixture.sampled(fixture.all_looks,{str(OUT)!r},phase={args.phase!r})'
                elif args.case=='hair':code+=f'import toon_round6_projection\nresult=fixture.sampled(toon_round6_projection.hair_reference,{str(OUT)!r},names={[args.name] if args.name else None!r})'
                elif args.case=='pilot':code+=f'fixture.capture({str(OUT)!r},phase="after",names=["dark_M"],quick=True)\nresult=fixture.sampled(fixture.articulation,{str(OUT)!r},phase="after",labels=["smile","A","O"])'
                elif args.case=='ray_probe':code+=f'result=fixture.ray_probe({str(OUT)!r})'
                elif args.case=='mouth_diagnostic':code+=f'result=fixture.mouth_diagnostic({str(OUT)!r})'
                elif args.case=='colour':code+=f'result=fixture.colour({str(OUT)!r})'
                elif args.case=='articulation':code+=f'result=fixture.sampled(fixture.articulation,{str(OUT)!r},phase={args.phase!r},name={name!r},render={not args.measure_only!r},labels={args.labels!r})'
                elif args.case=='diagnostic':code+=f'result=fixture.diagnostic({str(OUT)!r},labels={args.labels!r})'
                else:code+=f'result=fixture.capture({str(OUT)!r},phase={args.case!r},names={[name]!r},quick={args.quick!r},skip_keys={skip!r})'
                if args.case=='articulation':code+=f'\nimport toon_round6_projection\ntoon_round6_projection.collect({str(OUT)!r},{args.phase!r},{name!r})'
                r=await s.call_tool('run_blender_python',{'code':code});assert not r.isError,text_of(r)
                if args.case=='colour':
                    from toon_round6_metrics import check_colour
                    check_colour(OUT)
                print('ROUND6 CASE OK',args.case,name,flush=True)
        finally:await s.call_tool('engine_shutdown',{})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',choices=('before','after','diagnostic','articulation','colour','mouth_diagnostic','ray_probe','pilot','looks','hair','shade_probe','check'),default='before');p.add_argument('--name');p.add_argument('--phase',choices=('before','after'),default='after');p.add_argument('--measure-only',action='store_true');p.add_argument('--all-characters',action='store_true');p.add_argument('--labels',nargs='+');p.add_argument('--quick',action='store_true');p.add_argument('--resume',action='store_true');args=p.parse_args()
    if args.case=='check':
        from toon_round6_metrics import check,articulation_checks,eye_checks,hair_checks,look_checks,check_colour
        check(OUT);articulation_checks(OUT);eye_checks(OUT);hair_checks(OUT);look_checks(OUT);check_colour(OUT);print('TOON ROUND6 VISUAL CONTRACT OK')
    else:asyncio.run(run(args))
