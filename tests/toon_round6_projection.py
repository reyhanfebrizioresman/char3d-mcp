"""Read native neutral eye projections from saved Round 6 review scenes."""
from pathlib import Path
import json
import numpy as np


def collect(root_path,phase,name):
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.toon import LID_PAIRS
    root=Path(root_path);out=root/'projections';out.mkdir(exist_ok=True)
    rig,body,parts=_family('Review_rig')
    bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
    data=np.load(root/phase/f'{name}_mesh.npz');p=data['points'];h=float(data['head_height']);chin=float(data['chin']);eye=data['eyes'].mean(0)
    low=float(p[[520,540,521,538,7267,7282],2].mean()+.07*h);high=float(eye[2]-.075*h)
    cases=json.loads((root/phase/'matrix.json').read_text())['cases'];report={}
    for angle in (0,35,55):
        camera=camera_shot(subject=[bounds.name],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        def project(points):
            result=[]
            for point in points:
                v=world_to_camera_view(bpy.context.scene,bpy.data.objects[camera],body.matrix_world@Vector(point))
                result.append([float(v.x*256),float((1-v.y)*256)])
            return result
        polygon=project([(x,eye[1],z) for x,z in ((-.23*h,low),(.23*h,low),(.23*h,high),(-.23*h,high))])
        expected=next(c['face_polygon'] for c in cases if c['name']==name and c['angle']==angle)
        error=float(abs(np.asarray(polygon)-expected).max());assert error<.001,(phase,name,angle,error)
        report[str(angle)]=dict(eye_rims=[project(p[np.asarray(pairs).ravel()]) for pairs in LID_PAIRS.values()],nose=project([p[294]])[0],camera_replay_error_px=error)
    (out/f'{phase}_{name}.json').write_text(json.dumps(report,indent=2));return report


def hair_reference(root_path,names=None):
    """Compare pigment on the same installed hair asset, inside its crown."""
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from toon_round4_fixture import setup
    from toon_round6_fixture import CASES,write_json
    from engine.commands.materials import _family
    from engine.commands.camera import camera_shot
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render_style import render_style
    from engine.commands.render import render_preview
    from engine.commands.toon import neutral_coords,anatomy
    root=Path(root_path);out=root/'hair';out.mkdir(exist_ok=True)
    report=json.loads((out/'matrix.json').read_text())['cases'] if (out/'matrix.json').exists() else []
    cases=json.loads((root/'after/matrix.json').read_text())['cases']
    for name,tone,gender,_,requested in [c for c in CASES if c[0] in ('light_F','medium_F','dark_M')]:
        if names and name not in names:continue
        actual=next(c['build']['hair'] for c in cases if c['name']==name)
        setup(tone,'realistic',actual,gender);rig,body,parts=_family('Review_rig')
        # Generic bob requests retain their original pigment on the eye-safe
        # replacement. Match that explicit colour in the PBR control as well,
        # using the same flat-colour path as a numeric look recipe.
        pigment=None
        if actual!=requested:
            from engine.commands.mpfb import _catalog
            from engine.commands.toon import asset_hair_color
            from engine.commands.materials import _role,_trees,_put
            pigment=asset_hair_color(_catalog()['hair'][requested])
            for obj in parts:
                if _role(obj,body)!='hair':continue
                for slot in obj.material_slots:
                    if not slot.material or not slot.material.node_tree:continue
                    for tree in _trees(slot.material.node_tree):
                        for bsdf in tree.nodes:
                            if bsdf.type!='BSDF_PRINCIPLED':continue
                            _put(tree,bsdf.inputs['Base Color'],(*pigment,1.))
                            for field,value in (('Roughness',.75),('Specular IOR Level',.15),('Sheen Weight',.05),('Coat Weight',0.)):
                                if field in bsdf.inputs:_put(tree,bsdf.inputs[field],value)
        bounds=next(o for o in bpy.context.scene.objects if o.name.startswith('Round4Bounds'))
        camera=camera_shot(subject=[bounds.name],shot='full',angle=35,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        cinematic_look(preset='studio_film',dof='off');render_style(style='none')
        path=out/f'{name}_realistic.png';render_preview(camera=camera,engine='eevee',width=256,height=256,filename=str(path))
        p=neutral_coords(body);_,top,chin,eyes=anatomy(body,parts,p);eye=np.mean(eyes,0);h=top-chin
        site=world_to_camera_view(bpy.context.scene,bpy.data.objects[camera],body.matrix_world@Vector((.07*h,eye[1]+.10*h,chin+.94*h)))
        report=[r for r in report if r['name']!=name]
        report.append(dict(name=name,hair=actual,requested_hair=requested,pigment_override_linear=pigment,path=str(path),hair_site=[float(site.x*256),float((1-site.y)*256)],sampling='crown at chin + 0.94 head heights; same catalog asset and retained pigment'))
        write_json(out/'matrix.json',dict(cases=report))
    return dict(cases=len(report))
