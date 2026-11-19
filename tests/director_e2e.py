"""Offline idea → real MCP build → two Eevee dialogue stills + voiced draft MP4.

CHAR3D_PORT=9973 CHAR3D_WORKSPACE=$PWD/output .venv/bin/python tests/director_e2e.py --serial-video
The review matrix uses --reviews-only. All evidence is gitignored under output/.
"""
import asyncio
import argparse
import json
import os
from pathlib import Path
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('CHAR3D_PORT') not in ('9989', '9973'):
    raise SystemExit('Set CHAR3D_PORT=9989 or 9973; never use 9876.')


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial-video', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Reuse saved verified build after an interrupted render')
    parser.add_argument('--review-case', choices=['reunion3','reunion7','confession2'])
    parser.add_argument('--reviews-only', action='store_true', help='Build and review three 30-second offline scenarios')
    args = parser.parse_args()
    work = Path(os.environ.get('CHAR3D_WORKSPACE', ROOT / 'output'))
    report = json.loads((work / 'director_e2e.json').read_text()) if args.resume else {}
    env = dict(os.environ, CHAR3D_ALLOW_PYTHON='1', CHAR3D_RENDER_CALIB=str(work / 'director_render_speed.json'))
    params = StdioServerParameters(command=sys.executable, args=['-m', 'mcp_server.server'], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        async def call(name, args=None, label=None):
            start = time.monotonic()
            if name == 'render_video' and '--serial-video' in sys.argv:
                from serial_video import render
                result = await render(session, args or {})
            else:
                result = await session.call_tool(name, args or {})
            assert not result.isError, result
            data = []
            for block in result.content:
                if block.type == 'text':
                    try: data.append(json.loads(block.text))
                    except ValueError: data.append(block.text)
            value = data[0] if len(data) == 1 else data
            report[label or name] = value
            (work / 'director_e2e.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(f'PASS {label or name}: {time.monotonic()-start:.1f}s', flush=True)
            return value
        try:
            await call('scene_info')
            if args.resume:
                await call('open_project', {'path':'director-reuni.blend'})
                draft, built = report['direct_scene'], report['build']
            else:
                await call('new_scene', {'frame_end':48})
                from director_review_checks import setup
                await setup(call,work)
                if args.reviews_only or args.review_case:
                    from director_review_checks import run
                    await run(call,work,args.review_case)
                    return
                draft = await call('direct_scene', {'idea':'Dua sahabat bertemu lagi di taman saat senja setelah 10 tahun, haru.',
                                               'generator':'offline', 'duration_s':15, 'characters':2, 'seed':7})
                await call('script_to_scene', {'script':draft['script'], 'build':False, **draft['build_options']}, 'plan')
                built = await call('script_to_scene', {'script':draft['script'], 'voice':True, 'sound':True,
                                                 'subtitles':True, **draft['build_options']}, 'build')
            assert len(built['characters']) == 2
            assert all(c['realistic'] for c in built['characters'].values()), built['warnings']
            assert built['generated_files'] or built['cache_hits']
            reviewed = await call('review_scene',dict(level='standard',size=384),'delivery_review')
            assert reviewed['score']>=90,reviewed['issues']
            assert not [i for i in reviewed['issues'] if i['category'] in ('rhythm','camera') and i['severity'] in ('warn','error')],reviewed['issues']
            frames = [line['start'] + min(8, (line['end']-line['start']) // 2) for line in built['lines'][:2]]
            await call('render_frames', {'frames':frames, 'camera':'scene', 'engine_name':'workbench', 'size':384}, 'workbench')
            await call('render_frames', {'frames':frames, 'camera':'scene', 'engine_name':'eevee', 'size':512}, 'eevee')
            await call('save_project', {'path':'director-reuni.blend'})
            # A portable asset is a milestone deliverable as in the agent guide.
            if not args.resume:
                await call('export_asset', {'path':'director-reuni.glb', 'objects':[c['rig'] for c in built['characters'].values()], 'max_influences':4})
            await call('list_audio')
            await call('render_video', {'path':'director-reuni-draft.mp4', 'quality':'draft', 'width':512, 'height':288,
                                        'frame_start':built['frames'][0], 'frame_end':built['lines'][1]['end'], 'wait':True})
            import av
            import numpy as np
            movie = work / 'renders/director-reuni-draft.mp4'
            with av.open(str(movie)) as container:
                assert any(s.type == 'video' and s.codec_context.name == 'h264' for s in container.streams)
                assert any(s.type == 'audio' and s.codec_context.name == 'aac' for s in container.streams)
                arrays = [frame.to_ndarray() for frame in container.decode(audio=0)]
                samples = np.concatenate(arrays, axis=-1)
                rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                assert rms > .001, 'Voices must be audible, not an empty AAC track'
                report['movie_check'] = {'path':str(movie), 'duration_s':container.duration / av.time_base,
                                         'video':'h264', 'audio':'aac', 'audio_rms':rms}
            (work / 'director_e2e.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print('DIRECTOR E2E OK', flush=True)
        finally:
            # If another local adapter started it, engine_shutdown only stops owned
            # processes. The outer UI test process is shut down by the test runner.
            await call('engine_shutdown')


if __name__ == '__main__':
    asyncio.run(main())
