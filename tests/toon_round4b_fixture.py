"""Local Eevee scan-colour contract, called only through MCP on port 9971."""
from pathlib import Path
import json
import numpy as np

TONES=('light','medium','dark')


def pigment_probe(body):
    from engine.commands.materials import _image,_pixels
    from engine.commands.toon import sampled_skin
    material=body.material_slots[0].material
    image=_image(material)
    bsdf=material.node_tree.nodes.get('Principled BSDF')
    return dict(material=material.name,sampled=sampled_skin(body),
                profile=json.loads(material.get('c3d_material_profile','{}')),
                flat=list(material.get('c3d_toon_flat_color',[])),
                image=dict(name=image.name,space=image.colorspace_settings.name,
                           corner=_pixels(image)[:4].tolist()) if image else None,
                emission=float(bsdf.inputs['Emission Strength'].default_value) if bsdf else None)


def matrix(root_path,phase='after',tones=TONES):
    from toon_round4_fixture import setup,projection
    from engine.commands.materials import _family
    from engine.commands.render import render_preview
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.io import save_project
    out=Path(root_path)/phase;out.mkdir(parents=True,exist_ok=True)
    report_path=out/'matrix.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else dict(cases=[])
    for tone in tones:
        for body_style,styles in (('realistic',('none',)),('anime',('anime','animated_film'))):
            build,camera=setup(tone=tone,style=body_style,hair='short02')
            rig,body,parts=_family('Review_rig')
            projected=projection(camera);probe=pigment_probe(body)
            cinematic_look(preset='studio_film',dof='off')
            for style in styles:
                render_style(style=style)
                label='realistic' if body_style=='realistic' else style
                path=out/f'{tone}_{label}.png'
                import bpy
                def aov_state():
                    return [(layer.name,[(a.name,a.type) for a in layer.aovs],getattr(layer,'active_aov_index',None)) for layer in bpy.context.scene.view_layers]
                before=aov_state()
                render_preview(camera=camera,engine='eevee',width=384,height=384,filename=str(path))
                assert aov_state()==before,'Skin render passes leaked into scene'
                record=dict(tone=tone,label=label,body_style=body_style,render_style=style,
                            build=build,projection=projected,pigment=probe,path=str(path))
                report['cases']=[c for c in report['cases'] if (c['tone'],c['label'])!=(tone,label)]
                report['cases'].append(record)
                report_path.write_text(json.dumps(report,indent=2))
            save_project(path=f'round4b/{phase}_{tone}_{body_style}.blend')
    return report


def garments(root_path):
    from toon_round4_fixture import garment_case
    return [garment_case(style,gender,root_path) for gender in (0,1)
            for style in (('realistic','anime','cartoon','chibi') if gender==0 else ('realistic','anime'))]


def refresh_dark(root_path):
    from engine.commands.io import open_project
    from engine.commands.render import render_preview
    from engine.commands.render_style import render_style
    from engine.commands.materials import _family
    out=Path(root_path)/'after';path=out/'matrix.json';report=json.loads(path.read_text())
    open_project(path='round4b/after_dark_anime.blend')
    for style in ('anime','animated_film'):
        render_style(style=style)
        render_preview(camera='Shot1',engine='eevee',width=384,height=384,filename=str(out/f'dark_{style}.png'))
    return report


def native_check(root_path):
    import bpy
    from engine.commands.io import open_project
    from engine.commands.render import render_preview
    from engine.commands.render_style import render_style
    out=Path(root_path)
    open_project(path='round4b/after_medium_anime.blend')
    layer=bpy.context.view_layer
    user=layer.aovs.add();user.name='__c3d_skin_pigment';user.type='COLOR'
    before=[(a.name,a.type) for a in layer.aovs]
    render_style(style='animated_film')
    reopened=out/'medium_reopened.png'
    render_preview(camera='Shot1',engine='eevee',width=384,height=384,filename=str(reopened))
    assert [(a.name,a.type) for a in layer.aovs]==before,'User AOV was modified'
    render_style(style='none')
    plain=out/'medium_unstyled.png'
    render_preview(camera='Shot1',engine='eevee',width=384,height=384,filename=str(plain))
    render_style(style='anime',grade={'saturation':0.,'temperature':0.,'tint':0.})
    mono=out/'monochrome.png'
    render_preview(camera='Shot1',engine='eevee',width=256,height=256,filename=str(mono))
    assert [(a.name,a.type) for a in layer.aovs]==before
    layer.aovs.remove(user)
    return dict(reopened=str(reopened),plain=str(plain),monochrome=str(mono),aovs_preserved=before)
