"""Offline Round 7 review, through one owned char3d MCP server on 9971."""
import argparse,asyncio,hashlib,importlib,json,os,subprocess,sys
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from e2e_smoke import text_of
from toon_round7_geometry import valid_png
OUT=ROOT/'output/toon_round7'
MODULES=('engine.toon_refine','engine.commands.toon','engine.commands.toon_refine',
         'engine.commands.render_style','engine.commands.toon_render','engine.commands.mpfb')


def pinned_sources():
    folder=OUT/'baseline_code';folder.mkdir(parents=True,exist_ok=True);record={}
    for module in MODULES:
        source=module.replace('.','/')+'.py'
        blob=subprocess.run(['git','show','d92d70d:'+source],cwd=ROOT,capture_output=True,check=True).stdout
        file=folder/(module+'.py')
        if file.exists():assert file.read_bytes()==blob,file
        else:file.write_bytes(blob)
        record[source]=hashlib.sha256(blob).hexdigest()
    (folder/'provenance.json').write_text(json.dumps(dict(commit='d92d70d',sha256=record),indent=2))


def complete(name,phase):
    path=OUT/phase/'matrix.json'
    if not path.exists():return False
    rows=[c for c in json.loads(path.read_text())['cases'] if c['name']==name]
    from toon_round7_fixture import signature
    source='d92d70d' if phase=='before' else signature()
    return len(rows)==12 and all(c['signature']==source and valid_png(c['path']) for c in rows) and (OUT/phase/f'{name}_mesh.npz').exists()


async def run(args):
    assert os.environ.get('CHAR3D_PORT')=='9971'
    if args.phase=='before':pinned_sources()
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (reader,writer),ClientSession(reader,writer) as session:
        await session.initialize()
        try:
            result=await session.call_tool('scene_info',{});assert not result.isError,text_of(result)
            prefix=f'import sys,importlib\nfrom pathlib import Path\nsys.path.insert(0,{str(ROOT/"tests")!r})\n'
            if args.phase=='before':
                for module in MODULES:
                    prefix+=f'm=importlib.import_module({module!r})\nexec(Path({str(OUT/"baseline_code"/(module+".py"))!r}).read_text(),m.__dict__)\n'
            prefix+='import toon_round7_fixture as fixture\n'
            if args.case=='capture':
                refresh=args.phase=='after' and not (args.resume or args.quick or args.build_only) and (OUT/'colour_complete.json').is_file()
                if refresh:
                    from toon_round7_metrics import refresh_snapshot
                    refresh_snapshot(OUT)
                names=args.names or ['light_F','light_M','medium_F','medium_M','dark_F','dark_M']
                for name in names:
                    if args.resume and not args.quick and not args.build_only and complete(name,args.phase):
                        print('ROUND7 REUSE VALID',args.phase,name,flush=True);continue
                    code=prefix+f'result=fixture.capture({str(OUT)!r},{args.phase!r},{name!r},build_only={args.build_only!r},quick={args.quick!r},resume={args.resume!r})'
                    result=await session.call_tool('run_blender_python',{'code':code});assert not result.isError,text_of(result)
                    print('ROUND7 CAPTURE OK',args.phase,name,flush=True)
                if refresh:refresh_snapshot(OUT,compare=True)
            elif args.case in ('expressions','beauty_refresh','articulation','qa','projection','look_rows'):
                for name in args.names or ['light_F','light_M','medium_F','medium_M','dark_F','dark_M']:
                    code=prefix+f'result=fixture.{args.case}({str(OUT)!r},phase={args.phase!r},names={[name]!r})'
                    result=await session.call_tool('run_blender_python',{'code':code});assert not result.isError,text_of(result)
                    print('ROUND7',args.case.upper(),'OK',args.phase,name,flush=True)
            else:
                extra=f',masks_only={args.masks_only!r}' if args.case=='probe' else ''
                code=prefix+f'result=fixture.{args.case}({str(OUT)!r},phase={args.phase!r},names={args.names!r}{extra})'
                result=await session.call_tool('run_blender_python',{'code':code});assert not result.isError,text_of(result)
                print('ROUND7',args.case.upper(),'OK',text_of(result),flush=True)
        finally:await session.call_tool('engine_shutdown',{})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=('capture','probe','expressions','beauty_refresh','articulation','colour','hair','qa','projection','look_rows','chibi','hair_ref','check'),default='capture')
    parser.add_argument('--phase',choices=('before','after'),default='after');parser.add_argument('--names',nargs='+')
    parser.add_argument('--build-only',action='store_true');parser.add_argument('--quick',action='store_true');parser.add_argument('--resume',action='store_true')
    parser.add_argument('--masks-only',action='store_true')
    args=parser.parse_args()
    if args.case=='check':
        from toon_round7_metrics import check
        check(OUT)
    else:
        asyncio.run(run(args))
        if args.case=='colour':
            from toon_round7_metrics import colour_contract
            colour_contract(OUT)
            # Publish the hand-off only after SDK shutdown has waited for the
            # owned Blender process to exit, including its final cleanup.
            from toon_round7_fixture import signature
            (OUT/'colour_complete.json').write_text(json.dumps(dict(source=signature(),complete=True,engine_stopped=True),indent=2))
