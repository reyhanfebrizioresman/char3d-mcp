"""Standalone Blender entry point shipped with each job. No char3d or MPFB imports."""
import json
from pathlib import Path
import sys
import time

import bpy


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
    renderer = gpu.platform.renderer_get()
    if any(x in renderer.lower() for x in ('llvmpipe', 'softpipe', 'software', 'swrast')):
        raise RuntimeError('GPU target has a software OpenGL renderer; configure EGL/driver access')
    return {'device': device, 'gpu': renderer}


def main(path):
    spec = json.loads(Path(path).read_text())
    if list(bpy.app.version) != spec['blender_version']:
        raise RuntimeError('Blender version mismatch; install the exact local Blender version')
    sc = bpy.context.scene
    info = setup_device(spec['device'])
    Path('device.json').write_text(json.dumps(info))
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
        bpy.ops.render.render(animation=True)
        for marker in list(sc.timeline_markers):
            sc.timeline_markers.remove(marker)
        sc.render.ffmpeg.audio_codec = 'NONE'
        for handle in spec.get('handles', []):
            sc.frame_start, sc.frame_end = handle['frames']
            sc.camera = bpy.data.objects[handle['camera']]
            sc.render.filepath = str(Path(handle['path']).resolve())
            bpy.ops.render.render(animation=True)
    finally:
        bpy.app.handlers.render_pre.remove(grain)
    Path('timing.json').write_text(json.dumps({'render_s': time.monotonic()-started, **info}))


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--')+1])
