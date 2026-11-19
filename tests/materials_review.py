"""Material review evidence through MCP, exclusively engine 9971.

--stills --cast Lina --looks studio --shots close_up --qualities enhanced
is the small tuning loop. Final evidence uses both qualities, seven people,
five lights and close/extreme close. All image measurements use original PNGs.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append('/usr/lib/python3/dist-packages')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CAST = ('Lina', 'Nia', 'Arman', 'Elder', 'Child', 'Mei', 'Sari')
LOOKS = ('studio', 'soft', 'golden_hour', 'night', 'misty_morning')
SHOTS = ('close_up', 'extreme_close_up')
# Normalized image coordinates, top-left origin. The annotated Lina image
# documents that these cover skin, excluding brows, eyes, nose and mouth.
ROIS = dict(forehead=(.46, .23, .54, .29),
            cheek_left=(.36, .44, .43, .50),
            cheek_right=(.56, .44, .63, .50))
REVISION = hashlib.sha256((ROOT/'engine/materials.py').read_bytes() +
                          (ROOT/'engine/commands/materials.py').read_bytes()).hexdigest()


def measure(path):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert('RGB'), dtype=float)/255
    h, w = a.shape[:2]
    stats = {}
    totals = []
    for name, (x0, y0, x1, y1) in ROIS.items():
        roi = a[int(y0*h):int(y1*h), int(x0*w):int(x1*w)]
        yp = roi @ np.array((.2126, .7152, .0722))
        linear = np.where(roi <= .04045, roi/12.92, ((roi+.055)/1.055)**2.4)
        stats[name] = dict(mean_srgb=roi.mean(axis=(0, 1)).tolist(),
                           srgb_luma=float(yp.mean()),
                           linear_luminance=float((linear @ [.2126, .7152, .0722]).mean()),
                           luma_std=float(yp.std()), near_white_fraction=float((yp > .85).mean()))
        stats[name]['pixels'] = int(yp.size)
        totals.append((float(yp.sum()), int(yp.size)))
    stats['mean_srgb_luma'] = sum(v for v,n in totals)/sum(n for v,n in totals)
    return stats


def sheet(records, reference, dest, name, shot):
    from PIL import Image, ImageDraw
    looks = [look for look in LOOKS if f'{name}/{look}/{shot}/enhanced' in records]
    tile = 256
    qualities = ['mpfb', 'prior', 'enhanced'] if any(k.startswith(name+'/') and k.endswith('/prior') for k in records) else ['mpfb', 'enhanced']
    labels = dict(mpfb='MPFB', prior='prior enhanced', enhanced='revised enhanced')
    image = Image.new('RGB', (tile*len(qualities), 28+len(looks)*(tile+24)), '#20252b')
    draw = ImageDraw.Draw(image)
    for col, quality in enumerate(qualities):
        draw.text((col*tile+8, 7), f'{name} | {labels[quality]}', fill='white')
    for row, look in enumerate(looks):
        items = [records.get(f'{name}/{look}/{shot}/{q}') for q in qualities]
        for col, item in enumerate(items):
            if item is None:
                continue
            y = 28+row*(tile+24)
            im = Image.open(item['path']).convert('RGB').resize((tile, tile))
            image.paste(im, (col*tile, y))
            label = look
            if shot == 'close_up' and name == 'Lina':
                label += f" | Y' {measure(item['path'])['mean_srgb_luma']:.3f}"
            draw.text((col*tile+7, y+tile+5), label, fill='white')
    path = dest/'sheets'/f'{name}_{shot}.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print('SHEET', path, flush=True)


class Review:
    def __init__(self, session, dest):
        self.session, self.dest = session, dest
        self.film = False

    async def call(self, tool, **args):
        response = await self.session.call_tool(tool, args)
        if response.isError:
            raise RuntimeError(str(response.content))
        text = [c.text for c in response.content if c.type == 'text'][-1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def python(self, code):
        return (await self.call('run_blender_python', code=code))['result']

    async def render(self, name, size=256, frame=1, square=True, engine='eevee'):
        start = time.perf_counter()
        # render_frames preserves the scene aspect through the native engine.
        # The preview MCP wrapper currently drops height=None and falls back
        # to the engine's 512px default height, distorting small comparisons.
        result = await self.call('render_frames', camera='scene', engine_name=engine,
                                  size=size, frames=[frame], subtitles=False, graphics=False)
        path = self.dest/'renders'/f'{name}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result['path'], path)
        assert result['size'][0] == size and (not square or result['size'][1] == size), result
        return dict(path=str(path), size=result['size'], seconds=time.perf_counter()-start,
                    revision=REVISION, engine=engine)

    async def setup(self, name, look, prior=False):
        await self.call('scene_info')
        await self.call('open_project', path=f'materials_{name}{"_enhanced" if prior else ""}.blend')
        await self.python("sc=bpy.context.scene\nsc.render.threads_mode='FIXED'\nsc.render.threads=4\nsc.render.resolution_x=512\nsc.render.resolution_y=512\nresult=True")
        await self.call('cinematic_look', clear=True)
        await self.call('render_style', style='film' if self.film else 'none')
        await self.call('set_lighting', preset=look if look in ('studio', 'soft') else 'studio', subject=[name+'_rig'])
        if look not in ('studio', 'soft'):
            await self.call('cinematic_look', preset=look)

    async def stills(self, args):
        path = self.dest/'stills.json'
        records = json.loads(path.read_text()) if path.exists() else {}
        reference = json.loads((ROOT/'output/materials_visuals.json').read_text())
        for name in args.cast:
            for look in args.looks:
                for quality in args.qualities:
                    await self.setup(name, look, prior=quality == 'prior')
                    upgraded = await self.call('upgrade_materials', character=name+'_rig', quality=quality) if quality != 'prior' else {}
                    probe = {k: v for k, v in (('specular', args.probe_specular), ('sss', args.probe_sss),
                                               ('gain', args.probe_gain), ('energy', args.probe_energy),
                                               ('coat', args.probe_coat)) if v is not None}
                    if args.probe_unlinked:
                        probe['unlinked'] = True
                    if probe and quality == 'enhanced':
                        await self.python(f'''from engine.commands.materials import _trees,_set
mat=bpy.data.objects[{name!r}].material_slots[0].material
params={probe!r}
for obj in bpy.context.scene.objects:
 if obj.get('c3d_material_catchlight_owner'):
  if 'energy' in params:obj.data.energy=params['energy']
  if params.get('unlinked'):obj.light_linking.receiver_collection=None
 if obj.type=='MESH' and 'coat' in params:
  for slot in obj.material_slots:
   if slot.material and slot.material.get('c3d_material_role')=='eyes':
    for tree in _trees(slot.material.node_tree):
     for n in tree.nodes:
      if n.type=='BSDF_PRINCIPLED':_set(tree,n,'Coat Weight',params['coat'])
for tree in _trees(mat.node_tree):
 for n in tree.nodes:
  if n.type=='BSDF_PRINCIPLED':
   for k,s in [('specular','Specular IOR Level'),('sss','Subsurface Weight')]:
    if k in params:n.inputs[s].default_value=params[k]
  if n.name=='c3d skin reflectance' and 'gain' in params:n.inputs[2].default_value=(params['gain'],)*3+(1.,)
result=True
''')
                    for shot in args.shots:
                        key = f'{name}/{look}/{shot}/{quality}'
                        if args.reuse and key in records and (quality != 'enhanced' or records[key].get('revision') == REVISION) and Path(records[key]['path']).is_file():
                            continue
                        await self.call('camera_shot', subject=[name+'_rig'], shot=shot, name='MaterialPortrait',
                                        start_frame=1, end_frame=72, angle=8, elevation=0, avoid_occlusion=False,
                                        depth_of_field=True if self.film else None if look not in ('studio', 'soft') else False,
                                        f_stop=8. if self.film else 2.8)
                        if self.film:
                            await self.python(f'''from mathutils import Vector
from engine.commands.materials import _family,_eye_frame
root,body,meshes=_family({name+'_rig'!r})
z,y,_=_eye_frame(meshes,body)
focus=bpy.data.objects.new('MaterialEyeFocus',None)
bpy.context.scene.collection.objects.link(focus)
focus.location=body.matrix_world @ Vector((0,y,z))
bpy.context.scene.camera.data.dof.focus_object=focus
result=True
''')
                        item = await self.render(key.replace('/', '_'), args.size, engine=args.engine)
                        if shot == 'close_up' and name == 'Lina':
                            item['measurements'] = measure(item['path'])
                        item['skin_profile'] = upgraded.get('skin_profile')
                        item['probe'] = probe
                        records[key] = item
                        path.write_text(json.dumps(records, indent=2))
                        print('RENDER', key, round(item['seconds'], 2),
                              round(item.get('measurements', {}).get('mean_srgb_luma', 0), 3), flush=True)
                for shot in args.shots:
                    sheet(records, reference, self.dest, name, shot)
            await self.call('upgrade_materials', character=name+'_rig')
            await self.call('cinematic_look', clear=True)
            project = ROOT/'output/projects/material_review_v2'/f'{name}_{args.tag}.blend'
            project.parent.mkdir(parents=True, exist_ok=True)
            await self.call('save_project', path=str(project))

    async def bench(self, args):
        await self.call('scene_info')
        await self.call('open_project', path='materials_Lina_pair.blend')
        await self.call('render_style', style='none')
        await self.call('cinematic_look', clear=True)
        await self.python("sc=bpy.context.scene\nsc.render.resolution_x=512\nsc.render.resolution_y=288\nsc.render.threads_mode='FIXED'\nsc.render.threads=4\nresult=True")
        await self.call('set_lighting', preset='studio', subject=['Lina_rig'])
        path = self.dest/'benchmark.json'
        records = json.loads(path.read_text()) if path.exists() else {}
        for shot in args.bench_shots:
            await self.call('camera_shot', subject=['Lina_rig'] if shot == 'close_up' else ['Lina_rig', 'Partner_rig'],
                            shot=shot, start_frame=1, end_frame=72, name='MaterialPortrait', angle=8,
                            elevation=0, avoid_occlusion=False, depth_of_field=False)
            data = {}
            for step, quality in enumerate(('mpfb', 'enhanced', 'enhanced', 'mpfb')):
                for name in ('Lina', 'Partner'):
                    await self.call('upgrade_materials', character=name+'_rig', quality=quality)
                warm = await self.render(f'bench_{shot}_{step}_warm', size=320, square=False)
                timed = await self.render(f'bench_{shot}_{step}', size=512, square=False)
                assert timed['size'] == [512, 288]
                data.setdefault(quality, []).append(dict(seconds=timed['seconds'], warm=warm['seconds'], path=timed['path']))
                records[shot] = data
                path.write_text(json.dumps(records, indent=2))
                print('BENCH FRAME', shot, step, quality, round(timed['seconds'], 3), flush=True)
            for quality in ('mpfb', 'enhanced'):
                data[quality+'_mean'] = sum(v['seconds'] for v in data[quality])/2
            data['ratio'] = data['enhanced_mean']/data['mpfb_mean']
            path.write_text(json.dumps(records, indent=2))
            print('BENCH RESULT', shot, data['ratio'], flush=True)

    async def clip(self):
        import numpy as np
        from PIL import Image, ImageDraw
        await self.setup('Lina', 'studio')
        await self.call('upgrade_materials', character='Lina_rig')
        await self.call('set_timeline', frame_start=1, frame_end=36, fps=12)
        await self.call('camera_shot', subject=['Lina_rig'], shot='extreme_close_up', name='MaterialPortrait',
                        start_frame=1, end_frame=36, angle=8, elevation=0, avoid_occlusion=False, depth_of_field=False)
        await self.call('cinematic_look', preset='studio_film', grade={'grain': 0})
        a, b = [await self.render(f'static_{frame}', frame=frame) for frame in (8, 9)]
        delta = np.abs(np.asarray(Image.open(a['path'])).astype(float)-np.asarray(Image.open(b['path'])).astype(float))
        stability = dict(full=float(delta.mean()), hair=float(delta[:64, :, :3].mean()),
                         skin=float(delta[80:210, 70:200, :3].mean()))
        assert max(stability.values()) < 2., stability
        print('STATIC FRAME MAE', stability, flush=True)
        await self.call('animate', armature='Lina_rig', clip='idle', start_frame=1)
        await self.call('set_expression', character='Lina_rig', expression='smile', strength=.4, frame=1, keyframe=True)
        await self.call('lip_sync', character='Lina_rig', text='Halo, senang sekali bertemu kalian!', start_frame=1, language='id')
        await self.call('set_timeline', frame_start=1, frame_end=36, fps=12)
        await self.call('auto_blink', character='Lina_rig', frame_start=1, frame_end=36, seed=14)
        await self.call('talk_motion', character='Lina_rig', frame_start=1, frame_end=36)
        project = ROOT/'output/projects/material_review_v2/talking.blend'
        project.parent.mkdir(parents=True, exist_ok=True)
        await self.call('save_project', path=str(project))
        await self.call('render_options', quality='preview')
        movie_path = self.dest/'talking_3s.mp4'
        job = await self.python(f'''from engine.commands.video import render_video,JOBS
r=render_video(path={str(movie_path)!r},quality='preview',width=512,height=512,frame_start=1,frame_end=36,_defer=True,subtitles=False)
j=JOBS[r['job_id']]
result=dict(command=j['render_cmd'],base=j['base'],path=j['path'])
''')
        await self.call('engine_shutdown')
        log_path = self.dest/'movie_worker.log'
        with log_path.open('wb') as log:
            process = await asyncio.create_subprocess_exec(*job['command'], stdout=log, stderr=asyncio.subprocess.STDOUT)
            waiting = asyncio.create_task(process.wait())
            while not waiting.done():
                await asyncio.wait([waiting], timeout=25)
                matches = re.findall(r'Video append frame\s+(\d+)', log_path.read_text(errors='replace'))
                print('MOVIE FRAME', matches[-1] if matches else 'starting', '/ 36', flush=True)
            assert waiting.result() == 0, log_path.read_text(errors='replace')[-5000:]
        movies = list(Path(job['base']).parent.glob(Path(job['base']).name+'*.mp4'))
        max(movies, key=lambda p: p.stat().st_mtime).replace(job['path'])
        import av
        with av.open(job['path']) as movie:
            frames = [f.to_ndarray(format='rgb24') for f in movie.decode(video=0)]
        assert len(frames) == 36 and frames[0].shape[:2] == (256, 256)
        adjacent = [float(np.abs(a.astype(float)-b.astype(float)).mean()) for a,b in zip(frames,frames[1:])]
        sheet = Image.new('RGB', (256*6, 280), '#20252b')
        draw = ImageDraw.Draw(sheet)
        for col, index in enumerate((0, 6, 12, 18, 24, 35)):
            sheet.paste(Image.fromarray(frames[index]), (256*col, 24))
            draw.text((256*col+8, 7), f'frame {index+1}', fill='white')
        sheet.save(self.dest/'talking_frames.png')
        (self.dest/'clip.json').write_text(json.dumps(dict(path=job['path'],frames=36,fps=12,duration_s=3,
                    stability=stability,adjacent_mae=adjacent,revision=REVISION), indent=2))
        print('MATERIAL REVIEW CLIP OK', job['path'], flush=True)


async def run(args):
    if os.environ.get('CHAR3D_PORT') != '9971':
        raise SystemExit('Material review requires CHAR3D_PORT=9971')
    workspace = ROOT/'output'
    os.environ.update(CHAR3D_WORKSPACE=str(workspace), CHAR3D_ALLOW_PYTHON='1')
    os.environ.setdefault('LP_NUM_THREADS', '4')
    os.environ.setdefault('MESA_SHADER_CACHE_DIR', str(workspace/'mesa_cache'))
    os.environ['CHAR3D_RENDER_CALIB'] = str(workspace/'material_review_v2/render_speed.json')
    dest = workspace/'material_review_v2'
    if args.tag != 'final':
        dest /= args.tag
    dest.mkdir(parents=True, exist_ok=True)
    params = StdioServerParameters(command=sys.executable, args=['-m', 'mcp_server.server'],
                                   cwd=str(ROOT), env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        review = Review(session, dest)
        review.film = args.film
        try:
            if args.stills:
                await review.stills(args)
            if args.bench:
                await review.bench(args)
            if args.clip:
                await review.clip()
        finally:
            await review.call('engine_shutdown')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stills', action='store_true')
    p.add_argument('--bench', action='store_true')
    p.add_argument('--bench-shots', nargs='+', choices=('close_up','medium','wide'), default=['close_up','medium','wide'])
    p.add_argument('--clip', action='store_true')
    p.add_argument('--film', action='store_true', help='film style with f/8 eye-plane DOF')
    p.add_argument('--engine', choices=('eevee','cycles'), default='eevee')
    p.add_argument('--cast', nargs='+', choices=CAST, default=list(CAST))
    p.add_argument('--looks', nargs='+', choices=LOOKS, default=list(LOOKS))
    p.add_argument('--shots', nargs='+', choices=SHOTS, default=list(SHOTS))
    p.add_argument('--qualities', nargs='+', choices=('mpfb', 'prior', 'enhanced'), default=['mpfb', 'enhanced'])
    p.add_argument('--tag', default='final')
    p.add_argument('--size', type=int, choices=(256, 384, 512), default=256)
    p.add_argument('--reuse', action='store_true')
    p.add_argument('--probe-specular', type=float)
    p.add_argument('--probe-sss', type=float)
    p.add_argument('--probe-gain', type=float)
    p.add_argument('--probe-energy', type=float)
    p.add_argument('--probe-coat', type=float)
    p.add_argument('--probe-unlinked', action='store_true')
    asyncio.run(run(p.parse_args()))


if __name__ == '__main__':
    main()
