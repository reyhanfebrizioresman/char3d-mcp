"""MCP-only fixture support. Own engine 9972, never the user's 9876."""
import json
import os
from pathlib import Path
import sys
import textwrap
from contextlib import asynccontextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@asynccontextmanager
async def connection():
    if os.environ.get('CHAR3D_PORT') != '9972':
        raise SystemExit('Use CHAR3D_PORT=9972')
    env = dict(os.environ, CHAR3D_ALLOW_PYTHON='1', CHAR3D_WORKSPACE=str(ROOT/'output'),
               XDG_CACHE_HOME=str(ROOT/'output/cache'), LP_NUM_THREADS='8',
               MESA_SHADER_CACHE_DIR=str(ROOT/'output/cache/mesa'))
    params = StdioServerParameters(command=sys.executable, args=['-m', 'mcp_server.server'],
                                   cwd=str(ROOT), env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        async def call(tool, **args):
            print('MCP', tool, flush=True)
            result = await session.call_tool(tool, args)
            if result.isError:
                raise RuntimeError((tool, [c.text for c in result.content if c.type == 'text']))
            if tool == 'new_scene':
                from e2e_smoke import isolate_mpfb
                await isolate_mpfb(session)
                await session.call_tool('run_blender_python', dict(code="bpy.context.scene.render.threads_mode='FIXED'\nbpy.context.scene.render.threads=8\nresult=True"))
            return result
        call.session=session
        async def data(tool, **args):
            result = await call(tool, **args)
            return json.loads([c.text for c in result.content if c.type == 'text'][-1])
        async def python(code):
            return (await data('run_blender_python', code=textwrap.dedent(code)))['result']
        try:
            yield call, data, python
        finally:
            import subprocess
            before=subprocess.check_output(['ss','-ltnp'],text=True)
            before=[line for line in before.splitlines() if ':9972 ' in line]
            await session.call_tool('engine_shutdown', {})
            after=subprocess.check_output(['ss','-ltnp'],text=True)
            after=[line for line in after.splitlines() if ':9972 ' in line]
            folder=ROOT/'output/filmstyle';folder.mkdir(parents=True,exist_ok=True)
            path=folder/'engine_sessions.json'
            sessions=json.loads(path.read_text()) if path.exists() else []
            sessions.append(dict(command=sys.argv,port=9972,before=before,after=after))
            path.write_text(json.dumps(sessions,indent=2))
            assert not after,after


async def snapshot_video(python, args):
    """Exercise the real video snapshot/movie/composition code in one Blender.

    The snapshot is reopened, rendered with render_movie.main, then the live
    scene is reopened in finally. No worker is spawned and no test claims parallel
    background execution. This honors the experiment's one-Blender requirement.
    """
    return await python(f'''
        import copy, glob, json, os, time
        from engine.commands import video
        from engine.render_movie import main as render_movie
        from engine.compose_subtitles import main as compose
        from engine import context
        live=os.path.join(context.WORKSPACE,'jobs','filmstyle_live.blend')
        os.makedirs(os.path.dirname(live),exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=live,copy=True)
        job=None
        try:
            args={args!r}
            args.pop('wait',None)
            report=video.render_video(**args,_defer=True)
            job=video.JOBS[report['job_id']]
            bpy.ops.wm.open_mainfile(filepath=job['blend'])
            spec=os.path.join(job['subs_dir'],'handles.json')
            if not os.path.exists(spec):
                os.makedirs(job['subs_dir'],exist_ok=True)
                with open(spec,'w') as f:json.dump(dict(handles=[]),f)
            t=time.perf_counter()
            render_movie(spec)
            elapsed=time.perf_counter()-t
            movies=sorted(glob.glob(glob.escape(job['base'])+'*.mp4'),key=os.path.getmtime)
            assert movies,job
            movie=movies[-1]
            engine=video.QUALITY[job['quality']][0]
            learned=video._learn(engine,elapsed/max(1,job['frames'][1]-job['frames'][0]+1),
                                 job['model_spf'],'serial_snapshot_test')
            if job['overlays'] or job['transitions']:
                spec=os.path.join(job['subs_dir'],'serial_compose.json')
                payload=dict(movie=movie,out_base=job['base']+'subs_',width=job['size'][0],
                    height=job['size'][1],fps=job['fps'],frames=job['frames'][1]-job['frames'][0]+1,
                    audio=job['audio'],overlays=job['overlays'],transitions=job['transitions'])
                with open(spec,'w') as f:json.dump(payload,f)
                bpy.ops.wm.read_factory_settings(use_empty=True)
                compose(spec)
                movie=sorted(glob.glob(glob.escape(job['base']+'subs_')+'*.mp4'),key=os.path.getmtime)[-1]
            video._deliver(job,movie)
            if learned:
                job['learned_speed']=dict(engine=video.ENGINE_KEY[engine],factor=learned['factor'],
                    measured_s_per_frame=round(elapsed/max(1,job['frames'][1]-job['frames'][0]+1),2),
                    source='serial_snapshot_test')
            job['finished']=time.time()
            result=video._report(job)
            result['single_engine_snapshot']=True
        finally:
            bpy.ops.wm.open_mainfile(filepath=live)
            if os.path.exists(live):os.remove(live)
    ''')
