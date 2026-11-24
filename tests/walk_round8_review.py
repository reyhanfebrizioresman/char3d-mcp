"""Prepare the matched v9 camera demo; render once after all numeric checks pass.

Use the same port/software-GL/workspace environment as walk_benchmark.py.
--prepare writes the timeline without rendering; --render writes draft movie,
keyframes and one labelled benchmark sheet using the existing saved cases.
"""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp_server.blender_client import BlenderClient


def montage(paths, labels, output, tile, geometry):
    command = ['montage','-font','DejaVu-Sans','-pointsize','13',
               '-background','#ededed','-fill','#222222']
    for path,label in zip(paths, labels):
        command += ['-label', label, str(path)]
    subprocess.run(command+['-geometry',geometry,'-tile',tile,str(output)],check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare', action='store_true'); p.add_argument('--render', action='store_true')
    args = p.parse_args()
    assert os.environ.get('CHAR3D_PORT') == '9977'
    engine = BlenderClient(); call = engine.call; work = Path(engine.workspace)
    try:
        call('scene_info')
        if args.prepare:
            call('open_project', path=str(work/'projects/male_rest.blend'))
            call('transform_object',name='Gait_rig',location=[-2,1,0],rotation_deg=[0,0,90])
            nav = call('walk_path',armature='Gait_rig',points=[[.4,1],[.4,-.9]],start_frame=1,avoid=False)
            turn = call('turn_to',armature='Gait_rig',target=[.4,3],avoid=False)
            call('set_timeline',frame_start=1,frame_end=turn['frames'][1]+4)
            call('auto_sfx',characters=['Gait_rig'],kinds=['footsteps'],footfalls=nav['footfalls']+turn['footfalls'],surface='wood')
            call('set_lighting',preset='studio',subject=['Gait_rig'])
            call('run_python',code='''
from mathutils import Vector
sc=bpy.context.scene
for m in list(sc.timeline_markers): sc.timeline_markers.remove(m)
for ob in [o for o in sc.objects if o.type=='CAMERA']: bpy.data.objects.remove(ob,do_unlink=True)
cam=bpy.data.objects.new('ReviewCam',bpy.data.cameras.new('ReviewCam')); sc.collection.objects.link(cam)
cam.data.lens=32; cam.location=Vector((1.5,-4.3,1.75)); target=Vector((-.75,.05,.85))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler(); sc.camera=cam
sc.render.resolution_x=640; sc.render.resolution_y=360; sc.render.resolution_percentage=100
result=True
''')
            call('save_project',path='walk_review_v10.blend')
            (work/'review_timeline.json').write_text(json.dumps(dict(walk=nav,turn=turn),indent=2))
            print('REVIEW PREPARED',flush=True)
        if args.render:
            import av
            info = json.loads((work/'review_timeline.json').read_text())
            nav, turn = info['walk'], info['turn']; end = turn['frames'][1]
            call('open_project',path='walk_review_v10.blend')
            sound = work/'renders/walk_review_v10_audio.wav'
            call('run_python',code=f"bpy.ops.sound.mixdown(filepath={str(sound)!r},container='WAV',codec='PCM',format='S16')\nresult=True")
            paths = []
            for first in range(1,end+5,8):
                frames = list(range(first,min(end+5,first+8)))
                result = call('render_frames',frames=frames,camera='scene',size=640,engine='workbench',prefix='v10_movie')
                paths += [x['path'] for x in result['frames']]
                print('REVIEW PNG',frames[-1],end+4,flush=True)
            with av.open(str(work/'walk_review_v10.mp4'),'w') as movie:
                video = movie.add_stream('libx264',rate=24)
                video.width=640; video.height=360; video.pix_fmt='yuv420p'
                video.options={'crf':'20','preset':'fast'}
                audio = movie.add_stream('aac',rate=48000); audio.layout='stereo'; audio.bit_rate=192000
                for i,path in enumerate(paths):
                    with av.open(path) as source: frame = next(source.decode(video=0))
                    frame.pts=i; frame.time_base=Fraction(1,24)
                    for packet in video.encode(frame): movie.mux(packet)
                for packet in video.encode(): movie.mux(packet)
                resampler=av.AudioResampler(format='fltp',layout='stereo',rate=48000); samples=0
                with av.open(str(sound)) as source:
                    for source_frame in source.decode(audio=0):
                        for frame in resampler.resample(source_frame):
                            frame.pts=samples; frame.time_base=Fraction(1,48000); samples+=frame.samples
                            for packet in audio.encode(frame): movie.mux(packet)
                for frame in resampler.resample(None):
                    frame.pts=samples; frame.time_base=Fraction(1,48000); samples+=frame.samples
                    for packet in audio.encode(frame): movie.mux(packet)
                for packet in audio.encode(): movie.mux(packet)
            frames=[20,nav['frames'][1]-30,nav['frames'][1],turn['frames'][0]+8,(turn['frames'][0]+end)//2,end]
            labels=['Jalan','Belok dan rem','Berhenti','Awal berbalik','Tengah berbalik','Akhir berbalik']
            montage([paths[f-1] for f in frames], [f'F{f} | {v}' for f,v in zip(frames,labels)],
                    work/'walk_review_v10_keyframes.png','3x2','480x270+6+10')
            benchmark=json.loads((work/'walk_benchmark_v10.json').read_text())
            selected=[f'{body}/straight_{speed}' for body in ('male','female_short','male_tall_heavy') for speed in (.6,1.,1.6)]
            selected += ['male/turn_90_left','male/turn_90_right','male/s_curve']
            sheet_paths=[]; sheet_labels=[]
            for i,key in enumerate(selected):
                case=benchmark['cases'][key]; n=case['nav']; is_turn='straight' not in key
                call('open_project',path=case['project']); call('scene_info')
                base=n['footfalls'][min(2,len(n['footfalls'])-1)]['frame']
                subjects=['Gait_rig']
                if is_turn:
                    corner=n['path_points'][1]
                    base=max(n['frames'][0],min(case['rows'],key=lambda r:
                        sum((r['pelvis_m'][k]-corner[k])**2 for k in (0,1)))['frame']-4)
                    trail=[[*r['pelvis_m'][:2],.012,1.] for r in case['rows']]
                    call('run_python',code=f'''
curve=bpy.data.curves.new('BenchmarkTrail','CURVE'); curve.dimensions='3D'; curve.bevel_depth=.012
spline=curve.splines.new('POLY'); spline.points.add({len(trail)-1})
for point,co in zip(spline.points,{trail!r}): point.co=co
ob=bpy.data.objects.new('BenchmarkTrail',curve); bpy.context.scene.collection.objects.link(ob)
mat=bpy.data.materials.new('TrailInk'); mat.diffuse_color=(.1,.16,.2,1); curve.materials.append(mat)
result=True
''')
                    subjects.append('BenchmarkTrail')
                frames=[min(n['frames'][1],base+k) for k in (0,4,8)]
                if not is_turn:
                    positions={f:case['rows'][f-n['frames'][0]]['pelvis_m'] for f in frames}
                    call('run_python',code=f'''
from mathutils import Vector
sc=bpy.context.scene
cam=bpy.data.objects.new('BenchmarkSide',bpy.data.cameras.new('BenchmarkSide')); sc.collection.objects.link(cam)
cam.data.type='ORTHO'; cam.data.ortho_scale=2.8; sc.camera=cam
cam.rotation_euler=Vector((-1,0,0)).to_track_quat('-Z','Y').to_euler()
for f,p in {positions!r}.items():
    cam.location=(p[0]+6,p[1],1.16); cam.keyframe_insert('location',frame=f)
sc.render.resolution_x=320; sc.render.resolution_y=320
curve=bpy.data.curves.new('GroundLine','CURVE'); curve.dimensions='3D'; curve.bevel_depth=.005
spline=curve.splines.new('POLY'); spline.points.add(1)
spline.points[0].co=(0,-10,0,1); spline.points[1].co=(0,2,0,1)
sc.collection.objects.link(bpy.data.objects.new('GroundLine',curve))
result=True
''')
                shots=call('render_frames',frames=frames,view='top' if is_turn else 'right',
                           size=320,engine='workbench',objects=subjects,
                           camera='auto' if is_turn else 'scene',prefix=f'benchmark_{i}')
                for shot,f in zip(shots['frames'],frames):
                    sheet_paths.append(shot['path']); sheet_labels.append(f'{key} | H {case["dimensions_m"][2]:.2f}m\nF{f} | +{(f-base)/24:.2f} s')
                print('BENCHMARK PANEL',key,flush=True)
            montage(sheet_paths,sheet_labels,work/'walk_benchmark_v10.png','3x12','320x320+4+8')
            print('ROUND8 REVIEW RENDERED',len(paths),'movie frames',flush=True)
    finally:
        engine.stop()


if __name__ == '__main__': main()
