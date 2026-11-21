"""Encode durable PNG frames + native Blender mixdown to H.264/AAC, without FFmpeg CLI."""
import json
from pathlib import Path
import sys
import bpy


def main(path):
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    root=Path(path).parent
    tasks=[('main',spec['start'],spec['start']+spec['frames']-1,'raw_')]+[
        ('handle_'+str(i),h['frames'][0],h['frames'][1],h['path']) for i,h in enumerate(spec.get('handles',[]))]
    for channel,start,end,output in tasks:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sc=bpy.context.scene;r=sc.render
        r.resolution_x,r.resolution_y=spec['size'];r.resolution_percentage=100
        r.fps=round(spec['fps']);r.fps_base=r.fps/spec['fps']
        sc.frame_start,sc.frame_end=1,end-start+1
        sc.view_settings.view_transform='Standard';sc.view_settings.look='None'
        sc.view_settings.exposure=0;sc.view_settings.gamma=1
        r.use_sequencer=True;r.use_compositing=False
        strips=sc.sequence_editor_create().strips
        files=[root/f'frames/{channel}/{frame:08d}.png' for frame in range(start,end+1)]
        if any(not p.is_file() for p in files):raise RuntimeError('Cannot encode: missing durable frames')
        strip=strips.new_image('Frames',str(files[0]),channel=1,frame_start=1)
        for p in files[1:]:strip.elements.append(p.name)
        strip.frame_final_duration=len(files)
        audio=channel=='main' and spec['audio']
        if audio:
            sound=strips.new_sound('Audio',str(root/'audio.wav'),channel=2,frame_start=1)
            sound.frame_final_duration=len(files)
        if hasattr(r.image_settings,'media_type'):r.image_settings.media_type='VIDEO'
        r.image_settings.file_format='FFMPEG'
        r.ffmpeg.format='MPEG4';r.ffmpeg.codec='H264'
        r.ffmpeg.constant_rate_factor=spec.get('crf','MEDIUM');r.ffmpeg.ffmpeg_preset='GOOD'
        r.ffmpeg.audio_codec='AAC' if audio else 'NONE'
        if audio:r.ffmpeg.audio_bitrate=192
        r.filepath=str(root/output);r.use_file_extension=True
        bpy.ops.render.render(animation=True)


if __name__=='__main__':main(sys.argv[sys.argv.index('--')+1])
