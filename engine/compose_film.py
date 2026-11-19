"""Compose independently rendered scenes in Blender VSE; no external ffmpeg."""
import json
import os
import sys
import wave

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.compose_subtitles import linear_keys, opacity_keys


def keys(strip, prop, values):
    for frame, value in values:
        setattr(strip, prop, value)
        strip.keyframe_insert(prop, frame=frame)


def main(path):
    with open(path) as stream:
        spec = json.load(stream)
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = spec['width'], spec['height']
    r.resolution_percentage = 100
    r.fps = round(spec['fps'])
    r.fps_base = r.fps/spec['fps']
    sc.frame_start, sc.frame_end = 1, spec['frames']
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    r.use_sequencer, r.use_compositing = True, False
    strips = sc.sequence_editor_create().strips
    # A quiet base guarantees a continuous encoded audio timeline, including cards
    # and completely silent scenes. Scene audio is mixed from the MP4 sound strips.
    silence = os.path.join(os.path.dirname(path), 'silence.wav')
    samples = round(spec['frames']/spec['fps']*48000)
    with wave.open(silence, 'wb') as wav:
        wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        while samples:
            n = min(samples, 48000)
            wav.writeframesraw(bytes(n*2))
            samples -= n
    strips.new_sound('Continuous audio', silence, channel=1, frame_start=1)
    if spec.get('music'):
        strips.new_sound('Film score', spec['music']['path'], channel=7, frame_start=1)
    pictures, sounds = [], []
    for i, scene in enumerate(spec['scenes']):
        # Adjacent scenes alternate channels; transition windows cannot overlap.
        channel = 2+i%2*3
        a, b = scene['film_frames']
        mov = strips.new_movie(f'Scene {i+1}', scene['movie'], channel=channel+1, frame_start=a)
        mov.frame_final_duration = b-a+1
        mov.blend_type = 'ALPHA_OVER'
        segment = [mov]
        if scene['card_frames']:
            card = strips.new_effect(f'Card background {i+1}', type='COLOR', channel=channel,
                frame_start=scene['segment_start'], length=scene['card_frames'])
            card.color = (.025, .035, .055)
            card.blend_type = 'ALPHA_OVER'
            title = strips.new_image(f'Card {i+1}', scene['card_png'], channel=channel+1,
                frame_start=scene['segment_start'])
            title.frame_final_duration = scene['card_frames']
            title.blend_type = 'ALPHA_OVER'
            segment.extend([card, title])
        pictures.append(segment)
        try:
            sound = strips.new_sound(f'Audio {i+1}', scene['movie'], channel=8+i%2, frame_start=a)
            sound.frame_final_duration = b-a+1
        except RuntimeError:
            sound = None  # A scene without sound is intentional silence.
        sounds.append(sound)
    for i, scene in enumerate(spec['scenes']):
        n, start = scene['transition_frames'], scene['segment_start']
        if not n:
            continue
        kind = scene['transition_in']['kind']
        if kind == 'crossfade':
            end = start+n-1
            # Apply complementary alpha to the strip on the higher channel. The
            # bottom movie stays opaque, avoiding a dark double-alpha blend.
            high = i if i%2 else i-1
            values = [(start, 0), (end, 1)] if high == i else [(start, 1), (end, 0)]
            for pic in pictures[high]:
                keys(pic, 'blend_alpha', values)
            if sounds[i-1]:
                keys(sounds[i-1], 'volume', [(start, 1), (end, 0)])
            if sounds[i]:
                keys(sounds[i], 'volume', [(start, 0), (end, 1)])
        else:
            lo, hi = start-n//2, start-n//2+n-1
            fade = strips.new_effect(f'Dip {i}', type='COLOR', channel=100,
                                     frame_start=lo, length=n)
            fade.color = (1, 1, 1) if kind == 'fade_white' else (0, 0, 0)
            fade.blend_type = 'ALPHA_OVER'
            opacity_keys(fade, [[lo, 0], [start, 1], [hi, 0]])
            if sounds[i-1]:
                keys(sounds[i-1], 'volume', [(lo, 1), (start, 0)])
            if sounds[i]:
                keys(sounds[i], 'volume', [(start, 0), (hi, 1)])
    placed = []
    for i, ov in enumerate(spec['overlays']):
        ch = max([10]+[c for a, b, c in placed if a <= ov['end'] and b >= ov['start']])+1
        if ch >= 100:
            raise ValueError('Too many simultaneous subtitle overlays')
        placed.append((ov['start'], ov['end'], ch))
        st = strips.new_image(f'Caption {i}', ov['path'], channel=ch, frame_start=ov['start'])
        st.frame_final_duration = ov['end']-ov['start']+1
        st.blend_type = 'ALPHA_OVER'
        if any(other.get('scene_index') != ov.get('scene_index') and
               other['start'] <= ov['end'] and other['end'] >= ov['start']
               for other in spec['overlays'][:i]):
            st.transform.offset_y = spec['height']*.12
        if ov.get('keys'):
            opacity_keys(st, ov['keys'])
        if ov.get('pop'):
            st.transform.origin = ov.get('origin', [.5, .5])
            for df, scale in ((0, .88), (2, 1.05), (4, 1)):
                keys(st.transform, 'scale_x', [(ov['start']+df, scale)])
                keys(st.transform, 'scale_y', [(ov['start']+df, scale)])
    linear_keys(sc)
    if hasattr(r.image_settings, 'media_type'):
        r.image_settings.media_type = 'VIDEO'
    r.image_settings.file_format = 'FFMPEG'
    r.ffmpeg.format, r.ffmpeg.codec = 'MPEG4', 'H264'
    r.ffmpeg.audio_codec, r.ffmpeg.audio_bitrate = 'AAC', 192
    r.ffmpeg.constant_rate_factor = 'HIGH'
    r.ffmpeg.ffmpeg_preset = 'GOOD'
    r.use_file_extension = True
    r.filepath = spec['out_base']
    bpy.ops.render.render(animation=True)


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--')+1])
