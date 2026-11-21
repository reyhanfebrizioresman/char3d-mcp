"""Standalone Blender entry point shipped with each job. No char3d or MPFB imports."""
import json
from pathlib import Path
import sys
import time

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_compat import check_version, memory_warning
from remote_frames import read_index, write_index, sha256, plan, valid_png


def render_durable(sc,spec):
    import os
    root=Path.cwd();index=read_index(root)
    files=index['files'];source=spec.get('endpoint','unknown')
    r=sc.render
    if hasattr(r.image_settings,'media_type'):r.image_settings.media_type='IMAGE'
    r.image_settings.file_format='PNG';r.image_settings.color_mode='RGBA'
    r.image_settings.color_depth='8';r.use_file_extension=False
    base_camera=sc.camera
    markers=sorted((m for m in sc.timeline_markers if m.camera),key=lambda m:m.frame)
    rendered=[]
    for item in plan(spec):
        name=item['path'];dest=root/name;record=files.get(name)
        if dest.is_file() and ((record and sha256(dest)==record['sha256']) or
                               (record is None and valid_png(dest,spec['size']))):
            if record is None:
                files[name]={**item,'sha256':sha256(dest),'source':source,'recovered':True}
                write_index(root,index)
            continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        sc.frame_set(item['frame'])
        if item['camera']:sc.camera=bpy.data.objects[item['camera']]
        else:sc.camera=next((m.camera for m in reversed(markers) if m.frame<=item['frame']),base_camera)
        tmp=dest.with_suffix('.part.png');r.filepath=str(tmp)
        before=time.monotonic()
        bpy.ops.render.render(write_still=True)
        with open(tmp,'rb+') as stream:os.fsync(stream.fileno())
        os.replace(tmp,dest)
        seconds=time.monotonic()-before
        files[name]={**item,'sha256':sha256(dest),'source':source,'seconds':seconds}
        rendered.append(seconds);write_index(root,index)
        print('C3D durable frame',item['channel'],item['frame'],flush=True)
    if spec['audio'] and not ((root/'audio.wav').is_file() and files.get('audio.wav') and
                              sha256(root/'audio.wav')==files['audio.wav']['sha256']):
        sc.frame_start=spec['start'];sc.frame_end=spec['start']+spec['frames']-1
        tmp=root/'audio.part.wav'
        bpy.ops.sound.mixdown(filepath=str(tmp),container='WAV',codec='PCM',format='S16',mixrate=48000)
        os.replace(tmp,root/'audio.wav')
        files['audio.wav']={'sha256':sha256(root/'audio.wav'),'source':source}
        write_index(root,index)
    return rendered


def estimate_memory(scene, width, height, quality):
    """Conservative planning heuristic; does not evaluate modifiers or allocate a GPU."""
    geometry = sum(len(o.data.vertices)*64+len(o.data.loops)*32+len(o.data.polygons)*16
                   for o in scene.objects if o.type == 'MESH' and not o.hide_render)
    textures = sum(int(im.size[0])*int(im.size[1])*16*4//3 for im in bpy.data.images
                   if im.source not in ('VIEWER',) and im.users)
    buffers = int(width)*int(height)*(128 if quality == 'cycles' else 64)
    return {'estimated_vram_bytes': 512*2**20+geometry*(4 if quality == 'cycles' else 2)+textures+buffers,
            'geometry_bytes': geometry, 'texture_bytes': textures, 'render_buffer_bytes': buffers,
            'method': 'heuristic; evaluated modifiers, drivers and GPU allocations can differ'}


def setup_device(device):
    if device == 'cpu':
        if bpy.context.scene.render.engine == 'CYCLES':
            bpy.context.scene.cycles.device = 'CPU'
        return {'device': 'cpu', 'gpu': None}
    if bpy.context.scene.render.engine == 'CYCLES':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = device.upper()
        prefs.get_devices()
        enabled = []
        for dev in prefs.devices:
            dev.use = dev.type == device.upper()
            if dev.use:
                enabled.append(dev.name)
        if not enabled:
            raise RuntimeError('Requested Cycles GPU is unavailable: ' + device)
        bpy.context.scene.cycles.device = 'GPU'
        return {'device': device, 'gpu': ', '.join(enabled)}
    import gpu
    try:
        renderer = gpu.platform.renderer_get()
    except SystemError:
        # Background Blender on Windows initializes its GPU context only when the
        # first Eevee/workbench frame renders; the renderer is not queryable yet.
        return {'device': device, 'gpu': None,
                'gpu_note': 'GPU context initializes at the first rendered frame'}
    if any(x in renderer.lower() for x in ('llvmpipe', 'softpipe', 'software', 'swrast')):
        raise RuntimeError('GPU target has a software OpenGL renderer; configure EGL/driver access')
    return {'device': device, 'gpu': renderer}


def main(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    warnings = check_version(spec['blender_version'], bpy.app.version, spec.get('blender_version_policy', 'minor'))
    sc = bpy.context.scene
    info = setup_device(spec['device'])
    vram = spec.get('vram_bytes')
    if spec['device'] != 'cpu':
        warnings += memory_warning(spec.get('estimated_vram_bytes'), vram)
    info.update(gpus=spec.get('gpus', []), vram_bytes=vram, warnings=warnings,
                blender_remote_version=bpy.app.version_string)
    Path('device.json').write_text(json.dumps(info), encoding='utf-8')
    sc.render.filepath = str(Path('raw_').resolve())
    # Packed images and //assets/... are independent of the source workstation paths.
    grain_cfg = json.loads(sc.get('char3d_remote_grain', 'null'))

    def grain(scene):
        if grain_cfg:
            import numpy as np
            img = bpy.data.images[grain_cfg['image']]
            w, h = img.size
            pixels = np.ones((h, w, 4), dtype=np.float32)
            pixels[:, :, :3] = np.random.default_rng(733+scene.frame_current).normal(
                0, grain_cfg['amount'], (h, w, 1))
            img.pixels.foreach_set(pixels.ravel())
            img.update()

    bpy.app.handlers.render_pre.append(grain)
    started = time.monotonic()
    try:
        if spec.get('durable'):
            measured=render_durable(sc,spec)
        else:
            measured=[]
            bpy.ops.render.render(animation=True)
        for marker in list(sc.timeline_markers):
            sc.timeline_markers.remove(marker)
        sc.render.ffmpeg.audio_codec = 'NONE'
        for handle in ([] if spec.get('durable') else spec.get('handles', [])):
            sc.frame_start, sc.frame_end = handle['frames']
            sc.camera = bpy.data.objects[handle['camera']]
            sc.render.filepath = str(Path(handle['path']).resolve())
            bpy.ops.render.render(animation=True)
    finally:
        bpy.app.handlers.render_pre.remove(grain)
    Path('timing.json').write_text(json.dumps({'render_s': time.monotonic()-started,'frame_seconds':measured, **info}), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--')+1])
