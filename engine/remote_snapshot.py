"""Bake the existing temporary look into a portable snapshot. No network/provider code.

Remote Blender needs only remote_worker.py and compose_subtitles.py. MPFB, addons,
and the char3d package are not imported by that worker.
"""
import json
import os

import bpy


def external_fingerprint():
    """Remote film cache includes bytes of external assets, not only saved .blend."""
    from hashlib import sha256
    found = {}
    for group in (bpy.data.images, bpy.data.sounds, bpy.data.fonts, bpy.data.movieclips):
        for item in group:
            raw = getattr(item, 'filepath', '')
            if not raw or raw == '<builtin>' or getattr(item, 'packed_file', None):
                continue
            path = bpy.path.abspath(raw, library=item.library)
            with open(path, 'rb') as stream:
                h = sha256()
                for block in iter(lambda: stream.read(1024*1024), b''):
                    h.update(block)
            found[item.name] = h.hexdigest()
    return found


def save(path, quality):
    from .commands.cinematic import applied_look, compositor_config
    from .commands.render_style import applied_style, get_config
    sc = bpy.context.scene
    changes = []
    assets = {}

    def collect(item, attr='filepath'):
        raw = getattr(item, attr)
        if not raw:
            return
        if getattr(item, 'packed_file', None) or getattr(item, 'packed_files', None):
            return
        if raw == '<builtin>':
            return
        source = os.path.realpath(bpy.path.abspath(raw, library=getattr(item, 'library', None)))
        if not os.path.isfile(source):
            raise ValueError(f'Remote snapshot has a missing/unsupported external asset: {source}')
        from hashlib import sha256
        with open(source, 'rb') as stream:
            h = sha256()
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
        rel = 'assets/' + h.hexdigest() + os.path.splitext(source)[1].lower()
        assets[rel] = source
        changes.append((item, attr, raw))
        setattr(item, attr, '//' + rel)

    try:
        # Linked libraries, simulation/volume/sequence caches need an explicit bake.
        if bpy.data.libraries or bpy.data.cache_files or bpy.data.volumes:
            raise ValueError('Remote renders require local data: make linked libraries local and bake caches/volumes first')
        for obj in sc.objects:
            if any(m.type in ('FLUID', 'CLOTH', 'SOFT_BODY', 'MESH_SEQUENCE_CACHE') for m in obj.modifiers):
                raise ValueError('Remote rendering of external simulation caches is not supported; bake to native animation')
        for image in bpy.data.images:
            if image.source in ('SEQUENCE', 'TILED', 'MOVIE'):
                raise ValueError('Remote snapshot does not support image sequences/UDIM/movie textures')
        # Resolve paths before save changes the blend anchor. Do not change the editor's assets.
        for group in (bpy.data.images, bpy.data.sounds, bpy.data.fonts, bpy.data.movieclips):
            for item in group:
                if getattr(item, 'filepath', ''):
                    collect(item)
        se = sc.sequence_editor
        for strip in (getattr(se, 'strips_all', []) if se else []):
            if strip.type == 'MOVIE':
                collect(strip)
            elif strip.type == 'IMAGE':
                raise ValueError('Bake VSE image sequences before remote rendering')
        if quality == 'draft':
            bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, relative_remap=False)
        else:
            with applied_look(sc), applied_style(sc) as effects:
                for im in effects:
                    if im.source == 'GENERATED' and not im.packed_file:
                        im.pack()
                # Generated grain images are native saved data. Worker updates pixels per frame.
                cfg = compositor_config(sc, get_config(sc))
                grain = next((im for im in effects if im.name.startswith('__c3d_style_grain')), None)
                if grain and cfg:
                    sc['char3d_remote_grain'] = json.dumps({'image': grain.name,
                        'amount': cfg.get('effects', {}).get('grain', .008 if cfg.get('style') == 'noir' else .004)})
                try:
                    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, relative_remap=False)
                finally:
                    if 'char3d_remote_grain' in sc:
                        del sc['char3d_remote_grain']
    finally:
        for item, attr, raw in reversed(changes):
            setattr(item, attr, raw)
    return assets


def serial_job(job):
    return {k: v for k, v in job.items() if k != 'proc'}
