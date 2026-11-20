"""Owner SSH test, or offline loopback with actual standalone Blender workers.

  .venv/bin/python tests/remote_ssh_smoke.py devodo
  .venv/bin/python tests/remote_ssh_smoke.py --loopback

Uses only port 9969, stops its editor between workers on loopback, never rents GPUs.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(args):
    from mcp_server import server as api
    from providers.remote.config import targets, write_json
    from providers.remote.supervisor import verify
    from providers.remote.transport import SSH
    cfg = targets()[args.target]
    if cfg['kind'] != 'ssh':
        raise RuntimeError('This smoke test accepts only an owner-configured SSH target, never paid instances')
    records = []

    async def tool(tool_name, **kwargs):
        return await getattr(api, tool_name)(**kwargs)

    if args.calibration_only:
        import threading
        try:
            await tool('scene_info')
            await tool('open_project',path='remote_smoke_editor.blend')
            reports=[]
            for method,extra in [('render_options',{}),('film_render_options',{'name':'remote_smoke'})]:
                queued=threading.Event()
                if args.loopback:
                    with patch.object(api.remote,'_launch',side_effect=lambda *a: queued.set()):
                        task=asyncio.create_task(tool(method,quality='draft',target=args.target,
                                                     calibrate=True,consent_upload=True,**extra))
                        assert await asyncio.to_thread(queued.wait,60), 'Calibration not queued'
                        await tool('engine_shutdown')
                    measured=await task
                else:
                    measured=await tool(method,quality='draft',target=args.target,
                                        calibrate=True,consent_upload=True,**extra)
                assert measured['test_frame']['verified']['frames']==1 and measured['machine_speed']['measurements']>0
                reports.append(measured)
            write_json(ROOT/'output/remote_calibration_result.json',reports)
            print('REMOTE CALIBRATION OK: video + film, one 480p frame each; isolated target speed learned',flush=True)
        finally:
            await tool('engine_shutdown')
        return

    async def render(tool_name, **kwargs):
        # The actual MCP tool's remote code runs. Only defer the supervisor launch
        # until the test editor exits, to keep this laptop to one owned Blender.
        live = await tool('save_project', path='remote_smoke_editor.blend')
        if args.loopback:
            with patch.object(api.remote, '_launch'):
                started = await tool(tool_name, target=args.target, consent_upload=True, **kwargs)
            await tool('engine_shutdown')
        else:
            started = await tool(tool_name, target=args.target, consent_upload=True, **kwargs)
        assert started.get('job_id'), started
        ident = started['job_id']
        # New manager instance proves persistent reattachment instead of in-memory jobs.
        from providers.remote import RemoteRenders
        manager = RemoteRenders(api.engine)
        if args.loopback:
            os.environ['CHAR3D_LOOPBACK_HIDE'] = json.dumps([str(audio), str(texture)])
        try:
            done = await asyncio.to_thread(manager.wait, ident)
        finally:
            if args.loopback:
                for path in (audio, texture):
                    hidden = Path(str(path)+'.hidden')
                    if hidden.exists():
                        hidden.rename(path)
        assert done['status'] == 'done' and done.get('verified'), done
        assert not done.get('cleanup_pending'), done
        records.append(done)
        print(tool_name, done['status'], done['verified'], flush=True)
        if args.loopback:
            await tool('open_project', path=live['path'])
        return done

    try:
        await tool('scene_info')
        await tool('new_scene', frame_end=24)
        await tool('add_primitive', kind='cube', name='RemoteCube', location=[0,0,.5])
        await tool('camera_shot', subject=['RemoteCube'], shot='full', start_frame=1, end_frame=24)
        await tool('set_lighting', preset='studio', subject=['RemoteCube'])
        await tool('add_subtitles', lines=[{'text':'Remote render test', 'start':0, 'end':1}])
        await tool('add_title', text='SSH', style='corner', duration_s=.5)
        audio = ROOT/'output/imports/remote_smoke.wav'
        audio.parent.mkdir(parents=True, exist_ok=True)
        import math
        import struct
        with wave.open(str(audio), 'wb') as stream:
            stream.setparams((1,2,24000,0,'NONE','not compressed'))
            stream.writeframes(b''.join(struct.pack('<h', int(3000*math.sin(i*440*2*math.pi/24000))) for i in range(24000)))
        await tool('add_audio', path=str(audio))
        # A real external image demonstrates hash collection and path relocation.
        texture = ROOT/'output/imports/remote_smoke.png'
        import av
        import numpy as np
        with av.open(str(texture), 'w', format='image2') as out:
            stream = out.add_stream('png', rate=1)
            stream.width,stream.height,stream.pix_fmt=8,8,'rgb24'
            for packet in stream.encode(av.VideoFrame.from_ndarray(np.full((8,8,3),[30,120,220],dtype=np.uint8),format='rgb24')):
                out.mux(packet)
            for packet in stream.encode(): out.mux(packet)
        await tool('run_blender_python', code=f'''
im=bpy.data.images.load({str(texture)!r})
mat=bpy.data.materials.new('RemoteTexture');mat.use_nodes=True
node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=im
mat.node_tree.links.new(node.outputs['Color'],mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
bpy.data.objects['RemoteCube'].data.materials.append(mat)
result=True
''')
        preview = await tool('render_preview', camera='scene', width=320, height=180)
        preview_info = next(json.loads(x) for x in preview if isinstance(x, str))
        print('preview', preview_info['path'], flush=True)
        draft = await render('render_video', path='remote_smoke_draft.mp4', quality='draft', width=640, height=360,
                             frame_start=1, frame_end=24)
        verify(draft['path'],24,[320,180],True)
        assert Path(draft['subtitles']['srt']).is_file() and draft['credits']
        # Bake a saved film look into the snapshot; the worker imports no engine package.
        await tool('render_style', style='film')
        lit = await render('render_video', path='remote_smoke_eevee.mp4', quality='preview', width=640, height=360,
                           frame_start=1, frame_end=2)
        verify(lit['path'],2,[320,180],True)
        with av.open(lit['path']) as source:
            image = next(source.decode(video=0))
            with av.open(str(ROOT/'output/remote_eevee.png'), 'w', format='image2') as output:
                png = output.add_stream('png', rate=1)
                png.width, png.height, png.pix_fmt = image.width, image.height, 'rgb24'
                for packet in png.encode(image.reformat(format='rgb24')): output.mux(packet)
                for packet in png.encode(): output.mux(packet)
        await tool('render_style', style='none')
        await tool('remove_subtitles')
        await tool('remove_graphics', all=True)
        # Build two tiny saved scenes through existing commands, then write a minimal
        # canonical manifest. No MPFB/TTS downloads or character build is needed.
        scenes = []
        for i in (1,2):
            await tool('set_timeline', frame_start=1, frame_end=4)
            project = await tool('save_project', path=f'remote_smoke/scene_{i:02d}.blend')
            scenes.append(dict(index=i,name=f'Scene {i}',project=project['path'],frames=[1,4],
                transition_in={'kind':'cut','duration_s':0},card=None))
        from engine.film_plan import layout
        frames = layout(scenes,24)
        manifest = dict(name='remote_smoke',built=True,fps=24,scenes=scenes,frames=frames,duration_s=frames[1]/24)
        write_json(ROOT/'output/projects/remote_smoke/film.json',manifest)
        film = await render('render_film', name='remote_smoke', path='remote_smoke_film.mp4', quality='draft',
                            width=640,height=360,resume=False)
        verify(film['path'],8,[320,180],True)
        cached = await render('render_film', name='remote_smoke', path='remote_smoke_cached.mp4', quality='draft',
                              width=640,height=360,resume=True)
        assert all(s['reused'] for s in cached['scenes']), cached
        if args.loopback:
            remote_root = Path(os.environ.get('CHAR3D_WINDOWS_ROOT',cfg['remote_dir']))
            assert not any(p for job in records for p in remote_root.glob('jobs/'+job['job_id']+'_*/scene.blend')), 'Remote temporary snapshots not cleaned'
            events=[json.loads(line) for line in Path(os.environ['CHAR3D_LOOPBACK_RECORD']).read_text().splitlines()]
            assert any(e.get('blobs') for e in events)
            sent=[h for event in events for h in event.get('blobs',[])]
            assert len(sent)==len(set(sent)), 'Already cached blobs were sent twice'
            assert Path(os.environ['CHAR3D_LOOPBACK_DROP']).exists(), 'Disconnect injection was not exercised'
            if args.windows_loopback:
                assert any(e['tool']=='scp' for e in events) and not any(e['tool']=='rsync' for e in events)
                assert any('patch differs' in warning for job in records for warning in job.get('warnings',[]))
        write_json(ROOT/'output/remote_smoke_results.json', records)
        print('REMOTE SSH SMOKE OK: 24 draft + 2 Eevee frames, AAC, graphics/SRT/credits, 2-scene film/cache, reattach',flush=True)
    finally:
        await tool('engine_shutdown')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',nargs='?',default='loopback')
    parser.add_argument('--loopback',action='store_true')
    parser.add_argument('--windows-loopback',action='store_true',help='Emulate cmd/PowerShell, Windows paths and SCP around real Linux Blender')
    parser.add_argument('--calibration-only',action='store_true',help='Measure one frame from the prior smoke editor snapshot')
    args=parser.parse_args()
    args.loopback = args.loopback or args.windows_loopback
    os.environ['CHAR3D_PORT']='9969'
    os.environ['CHAR3D_WORKSPACE']=str(ROOT/'output')
    os.environ['CHAR3D_ALLOW_PYTHON']='1'
    os.environ['CHAR3D_RENDER_CALIB']=str(ROOT/'output/remote_local_speed.json')
    if args.loopback:
        args.target='loopback'
        directory=ROOT/'output/remote_loopback'
        directory.mkdir(parents=True,exist_ok=True)
        config=directory/'config'
        config.mkdir(exist_ok=True)
        os.environ['CHAR3D_REMOTE_CONFIG']=str(config)
        os.environ['CHAR3D_LOOPBACK_RECORD']=str(directory/'transfers.jsonl')
        os.environ['CHAR3D_LOOPBACK_DROP']=str(directory/'dropped_once')
        for p in (directory/'transfers.jsonl',directory/'dropped_once'): p.unlink(missing_ok=True)
        shim=directory/'bin'
        shim.mkdir(exist_ok=True)
        source=ROOT/'tests/remote_loopback.py'
        source.chmod(0o755)
        for name in ('ssh','rsync','scp'):
            p=shim/name
            p.unlink(missing_ok=True)
            p.symlink_to(source)
        os.environ['PATH']=str(shim)+os.pathsep+os.environ['PATH']
        from mcp_server.blender_client import _find_blender
        from providers.remote.config import write_json
        cfg=dict(kind='ssh',host='loopback',device='cpu',blender=_find_blender(),
            remote_dir=str(directory/'worker'),threads=4,startup_seconds=10,idle_timeout_s=300)
        if args.windows_loopback:
            os.environ['CHAR3D_WINDOWS_ROOT']=str(directory/'Windows worker ü')
            os.environ['CHAR3D_LOOPBACK_BLENDER']=_find_blender()
            cfg.update(os='auto',user='reyhan febrizio r',shell='cmd',blender_version='minor',
                python=r'C:\Users\Reyhan Febrizio R\Python312\python.exe',
                blender=r'C:\Users\Reyhan Febrizio R\Blender\blender.exe',
                remote_dir=r'D:\char3d\Remote render',vram_gb=4)
        write_json(config/'targets.json', {'loopback':cfg})
    asyncio.run(main(args))
