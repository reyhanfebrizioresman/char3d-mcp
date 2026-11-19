"""Test adapter: execute native film snapshots/compose with only one Blender alive."""
import asyncio
import json
import os
from pathlib import Path
import textwrap

PENDING={}


def response(value):
    from mcp.types import CallToolResult,TextContent
    return CallToolResult(content=[TextContent(type='text',text=json.dumps(value))])


async def python(session,code):
    result=await session.call_tool('run_blender_python',dict(code=textwrap.dedent(code)))
    if result.isError:raise RuntimeError(str(result.content))
    return json.loads(next(c.text for c in result.content if c.type=='text'))['result']


async def prepare(session,args):
    args=dict(args,wait=False)
    value=await python(session,f'''
        import os,copy
        from unittest.mock import patch
        from engine.commands import film,video
        with patch.object(film,'_advance'):
            report=film.render_film(**{args!r})
        job=video.JOBS.pop(report['job_id'])
        live=os.path.join(job['directory'],'serial_editor.blend')
        bpy.ops.wm.save_as_mainfile(filepath=live,copy=True)
        children=[]
        for entry in job['scenes']:
            if entry.get('job_id'):
                child=copy.deepcopy(video.JOBS[entry['job_id']])
                composed=None
                if child.get('overlays') or child.get('transitions'):
                    with patch.object(video.subprocess,'Popen') as launch:
                        video._start_compose(child,child['base']+'pending.mp4')
                        composed=dict(command=launch.call_args.args[0],log=child['subs_log'])
                    child['proc']=None;child.pop('stage',None)
                children.append(dict(job=child,compose=composed))
        original_stage=job['stage']
        with patch.object(film.subprocess,'Popen') as launch:
            film._compose(job)
            composition=dict(command=launch.call_args.args[0],log=job['log'])
        job['stage']=original_stage;job['proc']=None
        result=dict(report=report,job=job,children=children,compose=composition,live=live)
    ''')
    PENDING[value['report']['job_id']]=value
    return value['report']


async def execute(session,ident):
    prepared=PENDING.pop(ident);job=prepared['job']
    await session.call_tool('engine_shutdown',{})
    async def worker(command,log):
        with open(log,'wb') as stream:
            proc=await asyncio.create_subprocess_exec(*command,stdout=stream,stderr=asyncio.subprocess.STDOUT)
            if await proc.wait():raise RuntimeError(Path(log).read_text()[-4000:])
    for child in prepared['children']:
        c=child['job'];await worker(c['render_cmd'],c['log'])
        paths=sorted(Path(c['base']).parent.glob(Path(c['base']).name+'*.mp4'))
        source=paths[-1]
        if child['compose']:
            specpath=Path(child['compose']['command'][-1]);spec=json.loads(specpath.read_text());spec['movie']=str(source)
            specpath.write_text(json.dumps(spec));await worker(child['compose']['command'],child['compose']['log'])
            source=sorted(Path(c['base']).parent.glob(Path(c['base']).name+'subs_*.mp4'))[-1]
        os.replace(source,c['path'])
        for entry in job['scenes']:
            if entry.get('job_id')==c['id']:entry['status']='done'
    await worker(prepared['compose']['command'],prepared['compose']['log'])
    await session.call_tool('engine_status',{})
    opened=await session.call_tool('open_project',dict(path=prepared['live']))
    if opened.isError:raise RuntimeError(str(opened.content))
    # Re-establish the isolated MPFB preference before a later partial rebuild.
    # The production queue keeps its editor alive; only this RAM test adapter restarts it.
    await python(session, f"""
        import addon_utils,importlib,os,shutil
        module='bl_ext.user_default.mpfb'
        if any(m.__name__==module for m in addon_utils.modules()):
            source=os.path.join(bpy.utils.extension_path_user(module),'data')
            home={str(Path(__file__).resolve().parents[1]/'output/mpfb_test')!r}
            os.makedirs(home,exist_ok=True)
            if os.path.isdir(source) and not os.path.isdir(os.path.join(home,'data')):
                shutil.copytree(source,os.path.join(home,'data'))
            cls=importlib.import_module(module+'._preferences').MpfbPreferences
            if 'bl_rna' not in cls.__dict__:bpy.utils.register_class(cls)
            addon=bpy.context.preferences.addons.get(module)
            if addon is None:
                addon=bpy.context.preferences.addons.new();addon.module=module
            addon.preferences.mpfb_user_data=home
            from engine.commands import dispatch
            dispatch('mpfb_assets',{{}})
    """)
    job.update(stage='compose',log=prepared['compose']['log'])
    value=await python(session,f'''
        from types import SimpleNamespace
        from engine.commands import film,video
        job={job!r}
        job['proc']=SimpleNamespace(poll=lambda:0)
        video.JOBS[job['id']]=job
        result=film.report(job)
    ''')
    Path(prepared['live']).unlink(missing_ok=True)
    return value


async def render(session,args):
    value=await prepare(session,args)
    if args.get('wait'):value=await execute(session,value['job_id'])
    return response(value)


async def status(session,ident):
    return response(await execute(session,ident))


async def cancel(session,ident):
    prepared=PENDING.pop(ident)
    job=prepared['job']
    value=await python(session,f'''
        from engine.commands import film,video
        job={job!r}
        video.JOBS[job['id']]=job
        result=film.cancel(job)
    ''')
    Path(prepared['live']).unlink(missing_ok=True)
    return response(value)
