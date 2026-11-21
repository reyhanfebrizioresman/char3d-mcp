"""Collect live references; film collection snapshots and restores the editor."""
import json
import os
from pathlib import Path
import bpy
from . import command, dispatch
from .. import context
from ..credits import collect, text


def _json(owner, key, default=None):
    try:
        return json.loads(owner.get(key, 'null')) or default
    except (TypeError, ValueError):
        return default


def evidence(card=False):
    sc = bpy.context.scene
    result = dict(mpfb=[], vrm=[], soundfonts=[], voices=[], whisper=[], fonts=[], imports=[], procedural=[])
    for rig in sc.objects:
        if rig.type == 'ARMATURE' and not rig.hide_render and rig.get('c3d_rig_type') == 'vrm':
            result['vrm'].append(dict(_json(rig, 'c3d_vrm_meta', {}), path=rig.get('c3d_import_source')))
    bodies = [o for o in sc.objects if o.get('c3d_source') == 'mpfb' and not o.hide_render]
    if bodies:
        for body in bodies:
            used = _json(body, 'c3d_asset_provenance', {})
            records = {r['name']:r for r in used.get('records', [])}
            names = set(used.get('assets', [])) | {body.get('c3d_skin', '')}
            rig = bpy.data.objects.get(body.get('c3d_rig', ''))
            names |= {o.get('c3d_material_part', '').removeprefix('hair ') for o in (rig.children_recursive if rig else []) if o.type=='MESH'}
            for name in sorted(names- {''}):
                record = records.get(name, {})
                result['mpfb'].append(dict(name=name, pack=record.get('pack', 'system or legacy pack — inspect source'), path=record.get('path')))
        result['mpfb'].append(dict(name='MakeHuman base human, topology and rig', pack='system'))
    registry = Path(context.resolve('audio/asr_provenance.json','imports'))
    try:
        asr_sources=json.loads(registry.read_text())
    except (OSError,ValueError):
        asr_sources={}
    from .audio import _sound_strips
    for strip in _sound_strips(sc):
        if strip.mute or strip.frame_final_end <= sc.frame_start or strip.frame_final_start > sc.frame_end:
            continue
        path = bpy.path.abspath(strip.sound.filepath) if strip.sound else None
        tts = _json(strip, 'char3d_tts_provenance')
        if tts:
            result['voices'].append(dict(tts, path=path))
        elif path and not strip.get('char3d_auto_music') and not strip.get('char3d_auto_sfx'):
            # Current TTS cache includes a small sidecar; old caches remain explicitly unknown.
            sidecar = Path(path).with_suffix('.credits.json')
            if sidecar.is_file():
                result['voices'].append(dict(json.loads(sidecar.read_text()), path=path))
            else:
                result['imports'].append(path)
        if strip.get('char3d_auto_sfx'):
            result['procedural'].append('Contact Foley and location ambience')
        if strip.get('char3d_auto_music'):
            cfg = _json(sc, 'char3d_auto_music', {})
            renderer = cfg.get('renderer', {})
            result['procedural'].append('Offline composition')
            if renderer.get('backend') == 'soundfont':
                font = renderer.get('font', '')
                known=renderer.get('sha256')=='9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe'
                licence_file=Path(font).parent/'GeneralUser-GS-LICENSE.txt'
                result['soundfonts'].append(dict(path=font, sha256=renderer.get('sha256'),
                    name='GeneralUser GS' if known else Path(font).name,
                    licence='GeneralUser GS licence (see licence file)' if known else 'User-supplied SoundFont — check source licence',
                    licence_file=str(licence_file) if known and licence_file.is_file() else None))
            else:
                result['procedural'].append('Numpy instrument synthesis')
        if path and str(Path(path).resolve()) in asr_sources:
            result['whisper'].append(asr_sources[str(Path(path).resolve())])
        if path and Path(path).with_suffix('.asr.json').is_file():
            result['whisper'].append(json.loads(Path(path).with_suffix('.asr.json').read_text()).get('model', 'unknown'))
        if strip.get('char3d_whisper_model'):
            result['whisper'].append(str(strip['char3d_whisper_model']))
    from .subtitles import get_config, _font_path
    from .graphics import get_config as graphics
    configs = ([get_config(sc)] if get_config(sc) else []) + [g for g in graphics(sc) if g['type']=='title']
    if card:configs.append({})  # Film cards are composed outside the saved scene.
    for cfg in configs:
        font = _font_path(cfg)[0]
        if font:
            known = next((str(p) for p in (Path('/usr/share/doc/fonts-liberation2/copyright'),Path('/usr/share/doc/fonts-liberation/copyright')) if p.is_file()),None) if 'Liberation' in font else '/usr/share/doc/fonts-dejavu-core/copyright' if 'DejaVu' in font else None
            result['fonts'].append(dict(path=font, licence='SIL Open Font License 1.1' if 'Liberation' in font and known and os.path.isfile(known) else 'Bitstream Vera licence and DejaVu public-domain changes' if 'DejaVu' in font and known and os.path.isfile(known) else None, licence_file=known if known and os.path.isfile(known) else None))
    for obj in sc.objects:
        if obj.hide_render:
            continue
        if obj.animation_data and obj.animation_data.action:
            result['imports'].extend(_json(obj.animation_data.action, 'c3d_import_sources', []))
        if obj.get('c3d_import_source'):
            result['imports'].append(obj['c3d_import_source'])
        if obj.get('c3d_role') == 'environment' or obj.get('c3d_prop_kind') or obj.get('c3d_nature_kind') or obj.get('c3d_kind') == 'humanoid' and obj.get('c3d_source') not in ('mpfb', 'vrm'):
            result['procedural'].append('Characters, sets, props and nature geometry')
    # Follow visible material/world references, excluding orphan image datablocks.
    images=set();trees=set()
    def image_refs(tree):
        if tree is None or tree in trees:return
        trees.add(tree)
        for node in tree.nodes:
            image=getattr(node,'image',None)
            if image is not None:images.add(image)
            image_refs(getattr(node,'node_tree',None))
    for obj in sc.objects:
        if not obj.hide_render:
            for slot in getattr(obj,'material_slots',[]):
                if slot.material:image_refs(slot.material.node_tree)
    if sc.world:image_refs(sc.world.node_tree)
    for image in images:
        path=bpy.path.abspath(image.filepath) if image.filepath else ''
        if path and '/imports/' in path:
            result['imports'].append(path)
    return result


def write(path, inventories):
    combined = {}
    for source in inventories:
        for kind, values in source.items():
            combined.setdefault(kind, []).extend(values)
    report = collect(combined)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(text(report), encoding='utf-8')
    return dict(report, path=path)


def _end_card():
    sc=bpy.context.scene
    from .graphics import get_config
    fps=sc.render.fps/sc.render.fps_base
    old=next((g for g in get_config(sc) if g['name']=='__Credits'),None)
    start=old['start_s'] if old else (sc.frame_end-sc.frame_start+1)/fps
    end=sc.frame_start+round((start+3)*fps)-1
    dispatch('set_timeline',dict(frame_end=max(sc.frame_end,end)))
    return dispatch('add_title',dict(text='Credits',subtitle='Asset and licence details: CREDITS.txt',
        start_s=start,duration_s=3,style='center',name='__Credits'))


@command('credits')
def credits(path=None, card=False, name=None):
    inventories=[];card_info=None
    if name is not None:
        from .film import _read, _snapshot_editor, _restore_editor
        film,manifest=_read(name)
        origin=_snapshot_editor()
        try:
            for index,scene in enumerate(film['scenes']):
                dispatch('open_project',dict(path=scene['project']))
                if card and index==len(film['scenes'])-1:
                    card_info=_end_card()
                    dispatch('save_project',dict(path=scene['project']))
                inventories.append(evidence(card=bool(scene.get('card'))))
        finally:
            _restore_editor(origin)
        default=os.path.join(os.path.dirname(manifest),'CREDITS.txt')
    else:
        if card:card_info=_end_card()
        inventories.append(evidence())
        default=context.resolve('CREDITS.txt','renders')
    output=context.resolve(path,'renders') if path else default
    report=write(output,inventories)
    if card_info:report['card']=card_info
    return report
