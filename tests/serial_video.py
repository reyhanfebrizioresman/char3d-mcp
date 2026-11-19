"""Run the engine's actual movie/compose jobs with the editor stopped between.

Test-only adapter for RAM-constrained isolated e2e sections. Snapshot settings,
worker commands, compose specs, delivery and speed learning all come from video.py.
No render results or job statuses are fabricated.
"""
import asyncio
import json
from pathlib import Path
import textwrap


async def render(session, args):
    async def tool(name, **params):
        response = await session.call_tool(name, params)
        if response.isError:
            raise RuntimeError(str(response.content))
        return response

    async def python(code):
        response = await tool('run_blender_python', code=textwrap.dedent(code))
        return json.loads(next(c.text for c in response.content if c.type == 'text'))['result']

    options = dict(args, wait=False, _defer=True)
    prepared = await python(f'''
        import copy,json,os
        from unittest.mock import patch
        from engine.commands.video import render_video,JOBS,_start_compose
        r=render_video(**{options!r})
        job=JOBS[r['job_id']]
        live=os.path.join(os.path.dirname(job['blend']),job['id']+'_editor.blend')
        bpy.ops.wm.save_as_mainfile(filepath=live,copy=True)
        main=dict(job)
        compose=None
        if job.get('overlays') or job.get('transitions'):
            with patch('engine.commands.video.subprocess.Popen') as launch:
                _start_compose(job,job['base']+'pending.mp4')
                compose=dict(command=launch.call_args.args[0],log=job['subs_log'])
            job['proc']=None
        result=dict(live=live,job=main,compose=compose)
    ''')
    job = prepared['job']
    await tool('engine_shutdown')

    async def worker(command, log):
        with open(log, 'wb') as stream:
            proc = await asyncio.create_subprocess_exec(*command, stdout=stream, stderr=asyncio.subprocess.STDOUT)
            if await proc.wait():
                raise RuntimeError(Path(log).read_text()[-5000:])

    await worker(job['render_cmd'], job['log'])
    movie = sorted(Path(job['base']).parent.glob(Path(job['base']).name+'*.mp4'))[-1]
    compose = prepared['compose']
    if compose:
        spec_path = Path(compose['command'][-1])
        spec = json.loads(spec_path.read_text())
        spec['movie'] = str(movie)
        spec_path.write_text(json.dumps(spec))
        await worker(compose['command'], compose['log'])
        job.update(stage='compose',main_video=str(movie),subs_log=compose['log'])
    await tool('engine_status')
    await tool('open_project', path=prepared['live'])
    report = await python(f'''
        from types import SimpleNamespace
        from engine.commands.video import JOBS,_finalize,_report,_learn_from_job
        job={job!r}
        job['proc']=SimpleNamespace(poll=lambda:0)
        if job.get('stage')=='compose':
            with open(job['log'],errors='replace') as stream: _learn_from_job(job,stream.read())
        JOBS[job['id']]=job
        _finalize(job)
        result=_report(job)
    ''')
    Path(prepared['live']).unlink(missing_ok=True)
    from mcp.types import CallToolResult, TextContent
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(report))])
