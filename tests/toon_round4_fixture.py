"""Engine-side, offline visual fixtures; called through the isolated MCP harness."""
from pathlib import Path
import json
import numpy as np


def isolate_assets():
    """Factory scene reset clears add-on preferences; keep MPFB writes local."""
    import bpy,addon_utils,importlib
    module='bl_ext.user_default.mpfb'
    if any(m.__name__==module for m in addon_utils.modules()):
        cls=importlib.import_module(module+'._preferences').MpfbPreferences
        if 'bl_rna' not in cls.__dict__:bpy.utils.register_class(cls)
        addon=bpy.context.preferences.addons.get(module)
        if addon is None:addon=bpy.context.preferences.addons.new();addon.module=module
        addon.preferences.mpfb_user_data=str(Path(__file__).resolve().parents[1]/'output/mpfb_test')


def portrait_bounds(body, meshes):
    import bpy
    from engine.commands.toon import anatomy,neutral_coords
    p=neutral_coords(body);_,top,chin,eyes=anatomy(body,meshes,p);h=top-chin
    head=p[:13380][(p[:13380,2]>=chin)&(p[:13380,2]<=top)]
    lo=head.min(0);hi=head.max(0);lo[2]-=.12*h;hi[2]+=.14*h
    me=bpy.data.meshes.new('Round4Bounds')
    me.from_pydata([(x,y,z) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])],[],[])
    obj=bpy.data.objects.new(me.name,me);bpy.context.collection.objects.link(obj);obj.hide_render=True
    return obj


def setup(tone='medium',style='anime',hair='bob01',gender=0):
    import bpy
    from engine.commands.scene import new_scene,scene_info
    from engine.commands.mpfb import create_realistic_human
    from engine.commands.materials import _family
    from engine.commands.render import render_preview
    from engine.commands.lighting import set_lighting
    from engine.commands.camera import camera_shot
    scene_info();new_scene(frame_end=144);isolate_assets()
    bpy.context.scene.render.resolution_x=bpy.context.scene.render.resolution_y=384
    bpy.context.scene.render.threads_mode='FIXED';bpy.context.scene.render.threads=4
    bpy.context.scene.eevee.taa_render_samples=16  # render_preview's fixed Eevee preview setting
    race={'light':{'caucasian':1},'medium':{'asian':1},'dark':{'african':1}}[tone]
    built=create_realistic_human(name='Review',style=style,gender=gender,race=race,hair=hair,
        clothes=[('female' if gender==0 else 'male')+'_casualsuit01','shoes01'])
    root,body,meshes=_family('Review_rig')
    bounds=portrait_bounds(body,meshes)
    for view in ('front','right','back','three_quarter'):
        render_preview(objects=[root.name],view=view,width=320,height=320)
    set_lighting(preset='studio',subject=[root.name])
    shot=camera_shot(subject=[bounds.name],shot='full',angle=25,lens=85,
        start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)
    return built,shot['camera']


def projection(camera):
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from engine.commands.toon import anatomy,neutral_coords
    from engine.commands.materials import _family
    root,body,meshes=_family('Review_rig');p=neutral_coords(body)
    _,top,chin,eyes=anatomy(body,meshes,p);h=top-chin
    eye=np.mean(eyes,0)
    # Two unobscured cheek sites plus forehead. Masks are saved in pixel units.
    sites=[(-.18*h,eye[1]-.012*h,eye[2]-.14*h),(.18*h,eye[1]-.012*h,eye[2]-.14*h),
           (0,eye[1]+.02*h,eye[2]+.21*h)]
    cam=bpy.data.objects[camera];sc=bpy.context.scene
    points=[world_to_camera_view(sc,cam,body.matrix_world@Vector(v)) for v in sites]
    return dict(sites=[[float(q.x*384),float((1-q.y)*384)] for q in points],head_height_m=h)


def matrix(phase,tone,root_path,styles=('none','anime','animated_film')):
    import bpy
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render import render_preview
    from engine.commands.io import save_project
    out=Path(root_path)/phase;out.mkdir(parents=True,exist_ok=True)
    build,camera=setup(tone)
    previous=json.loads((out/f'{tone}.json').read_text()) if styles!=('none','anime','animated_film') else {}
    result=dict(build=build,projection=projection(camera),stills=previous.get('stills',[]))
    for style in styles:
        render_style(style=style)
        for look in ('studio','studio_film','golden_hour'):
            if style!='anime' and look!='studio_film':continue
            cinematic_look(clear=True) if look=='studio' else cinematic_look(preset=look,dof='off')
            path=out/f'{tone}_{style}_{look}.png'
            render_preview(camera=camera,engine='eevee',width=384,height=384,filename=str(path))
            result['stills']=[s for s in result['stills'] if (s['style'],s['look'])!=(style,look)]
            result['stills'].append(dict(style=style,look=look,path=str(path)))
            (out/f'{tone}.json').write_text(json.dumps(result,indent=2))
    save_project(path=f'round4/{phase}_{tone}.blend')
    return result


def details(phase,root_path,only_smile=False):
    import bpy
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render import render_preview
    from engine.commands.face import set_expression
    from engine.commands.materials import _family
    from engine.commands.toon import coords
    out=Path(root_path)/phase;out.mkdir(parents=True,exist_ok=True)
    build,camera=setup(hair='short02')
    bpy.context.scene.eevee.taa_render_samples=16
    root,body,meshes=_family('Review_rig')
    np.savez(out/'head_mesh.npz',points=coords(body.data.shape_keys.key_blocks[0].data),edges=np.array([tuple(e.vertices) for e in body.data.edges]))
    cinematic_look(preset='studio_film',dof='off');render_style(style='anime')
    result=[]
    for name,expression,units in (('neutral','neutral',None),('A','neutral',{'aa_02':1}),('O','neutral',{'ow_08':1}),('smile','smile',None),('surprised','surprised',None)):
        if only_smile and name!='smile':continue
        from engine.commands.face import _set,_face_meshes
        _set(_face_meshes(body),{key.name:0. for key in body.data.shape_keys.key_blocks if key.name!='Basis' and not key.name.startswith('$')})
        set_expression(character=root.name,expression=expression)
        if units:
            from engine.commands.face import _set,_face_meshes
            _set(_face_meshes(body),units)
        path=out/f'extreme_{name}.png';render_preview(camera=camera,engine='eevee',width=512,height=512,filename=str(path))
        result.append(str(path))
    if not only_smile:
        set_expression(character=root.name,expression='neutral');render_style(style='anime',outline=False)
        render_preview(camera=camera,engine='eevee',width=512,height=512,filename=str(out/'extreme_no_outline.png'))
    return result

PALETTES={'light':(.82,.68,.57),'medium':(.64,.43,.28),'dark':(.42,.26,.17)}


def controlled_tones(root_path,styles=('anime','animated_film'),merge=False):
    continuity=save_open_check(root_path)
    from engine.commands.materials import _family
    from engine.commands.toon import toon_materials
    from engine.materials import srgb_to_linear
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render import render_preview
    out=Path(root_path)/'tones';out.mkdir(parents=True,exist_ok=True)
    build,camera=setup(hair='short02')
    root,body,meshes=_family('Review_rig')
    previous=json.loads((out/'results.json').read_text()) if merge else {}
    report=dict(projection=projection(camera),cases=previous.get('cases',[]),save_open=continuity)
    for tone,pigment in PALETTES.items():
        toon_materials(body,meshes,skin=srgb_to_linear(pigment))
        for style in styles:
            render_style(style=style)
            looks=['studio','studio_film','golden_hour']
            if tone=='medium' and style=='anime':
                looks+=['sunset','misty_morning','blue_hour','night','overcast_soft','dreamy','epic']
            elif tone=='dark':looks+=['night']
            for look in looks:
                cinematic_look(clear=True) if look=='studio' else cinematic_look(preset=look,dof='off')
                path=out/f'{tone}_{style}_{look}.png'
                render_preview(camera=camera,engine='eevee',width=384,height=384,filename=str(path))
                report['cases']=[c for c in report['cases'] if (c['tone'],c['style'],c['look'])!=(tone,style,look)]
                report['cases'].append(dict(tone=tone,style=style,look=look,pigment_srgb=pigment,path=str(path)))
                (out/'results.json').write_text(json.dumps(report,indent=2))
    return report


def refine_animated(root_path):
    """Refresh only cells affected by the gentler toon face form gradient."""
    for tone in ('medium','dark'):matrix('after',tone,root_path,styles=('animated_film',))
    return controlled_tones(root_path,styles=('animated_film',),merge=True)


def save_open_check(root_path):
    from engine.commands.io import open_project
    from engine.commands.render import render_preview
    from engine.commands.photo import decode
    root=Path(root_path)
    open_project(path='round4/after_dark.blend')
    path=root/'save_open_dark.png'
    render_preview(camera='Shot1',engine='eevee',width=384,height=384,filename=str(path))
    before=decode(root/'after/dark_animated_film_studio_film.png');after=decode(path)
    sites=json.loads((root/'after/dark.json').read_text())['projection']['sites'];x,y=map(int,sites[1])
    error=abs(before-after);report=dict(mean_rgb_error=float(error.mean()),cheek_rgb_error=float(error[y-4:y+5,x-4:x+5].mean()),path=str(path))
    (root/'save_open.json').write_text(json.dumps(report,indent=2))
    assert report['mean_rgb_error']<.01 and report['cheek_rgb_error']<.02,report
    return report


def hair_visibility(camera):
    """Sample real eye apertures against evaluated skin and alpha-tested hair."""
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from engine.commands.materials import _family,_role,_image,_pixels
    from engine.commands.toon import neutral_coords
    from engine.toon import LID_PAIRS
    root,body,parts=_family('Review_rig');p=neutral_coords(body)
    def surface(obj):
        ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();mesh.calc_loop_triangles()
        vertices=[obj.matrix_world@v.co for v in mesh.vertices];triangles=[list(t.vertices) for t in mesh.loop_triangles]
        uv=mesh.uv_layers.active
        coords=np.array([[list(uv.data[i].uv) for i in tri.loops] for tri in mesh.loop_triangles]) if uv else None
        materials=[tri.material_index for tri in mesh.loop_triangles]
        tree=BVHTree.FromPolygons(vertices,triangles,all_triangles=True)
        ev.to_mesh_clear();return tree,vertices,triangles,coords,materials
    eyes=next(o for o in parts if _role(o,body)=='eyes');eye=surface(eyes)[0];skin=surface(body)[0]
    hairs=[(o,surface(o)) for o in parts if _role(o,body)=='hair']
    origin=bpy.data.objects[camera].matrix_world.translation;result={};cached={}
    def opaque(obj,data,direction,maximum):
        tree,vertices,triangles,uv,materials=data;start=origin.copy();travel=0.
        for _ in range(24):
            point,normal,index,distance=tree.ray_cast(start,direction,maximum-travel)
            if point is None:return False
            mat=obj.material_slots[materials[index]].material
            image=mat.get('c3d_toon_cutout') or _image(mat,'opacity') or _image(mat)
            alpha=1.
            if image and uv is not None:
                if image.name not in cached:cached[image.name]=_pixels(image).reshape(image.size[1],image.size[0],4)
                tri=np.array([vertices[i] for i in triangles[index]]);a,b=tri[1]-tri[0],tri[2]-tri[0]
                w=np.linalg.lstsq(np.c_[a,b],np.asarray(point)-tri[0],rcond=None)[0]
                xy=uv[index,0]+w[0]*(uv[index,1]-uv[index,0])+w[1]*(uv[index,2]-uv[index,0])
                tex=cached[image.name];x,y=np.clip((xy*[tex.shape[1],tex.shape[0]]).astype(int),[0,0],[tex.shape[1]-1,tex.shape[0]-1])
                alpha=float(tex[y,x,3])
            if alpha>.5:return True
            travel+=float(distance)+1e-5
            if travel>=maximum:return False
            start=point+direction*1e-5
        return False
    for side,pairs in LID_PAIRS.items():
        ideal=hidden=0
        for i in (3,5,7,9):
            upper,lower=pairs[i]
            for fraction in (.35,.5,.65):
                target=body.matrix_world@Vector(p[upper]*(1-fraction)+p[lower]*fraction)
                direction=(target-origin).normalized()
                e=eye.ray_cast(origin,direction);s=skin.ray_cast(origin,direction)
                if e[0] is None or (s[0] is not None and s[3]<e[3]-.0002):continue
                ideal+=1
                hidden+=any(opaque(obj,data,direction,e[3]) for obj,data in hairs)
        result[side]=dict(ideal=ideal,blocked_by_hair=hidden,visible=ideal-hidden)
    return result


def hair_views(root_path,explicit=False):
    from engine.commands.camera import camera_shot
    from engine.commands.render import render_preview
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    import bpy
    out=Path(root_path)/('hair_explicit' if explicit else 'hair');out.mkdir(parents=True,exist_ok=True)
    if explicit:
        from engine.commands.scene import new_scene
        from engine.commands.mpfb import create_realistic_human
        from engine.commands.materials import _family
        new_scene();isolate_assets();bpy.context.scene.render.resolution_x=bpy.context.scene.render.resolution_y=384
        bpy.context.scene.render.threads_mode='FIXED';bpy.context.scene.render.threads=4
        bpy.context.scene.eevee.taa_render_samples=16
        create_realistic_human(name='Review',gender=0,look={'version':1,'style':'anime','assets':{'hair':'bob01'}},clothes=['female_casualsuit01','shoes01'])
        root,body,parts=_family('Review_rig');portrait_bounds(body,parts)
        from engine.commands.lighting import set_lighting
        set_lighting(preset='studio',subject=[root.name])
    else:setup()
    render_style(style='anime');cinematic_look(preset='studio_film',dof='off')
    report=[]
    for angle in (0,35,-35,55,-55):
        camera=camera_shot(subject=['Round4Bounds'],shot='full',angle=angle,lens=85,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
        visibility=hair_visibility(camera)
        path=out/f'view_{angle}.png';render_preview(camera=camera,engine='eevee',width=384,height=384,filename=str(path))
        report.append(dict(angle=angle,path=str(path),eyes=visibility))
        (out/'results.json').write_text(json.dumps(report,indent=2))
        assert all(v['ideal']>=2 and v['blocked_by_hair']==0 for v in visibility.values()),report[-1]
    return report


def garment_case(style,gender,root_path):
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from engine.commands.materials import _family,_image,_pixels
    from engine.commands.toon import coords
    from engine.commands.camera import camera_shot
    from engine.commands.render import render_preview
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.toon_appearance import visible_albedo
    out=Path(root_path)/'garments';out.mkdir(parents=True,exist_ok=True)
    build,_=setup(style=style,gender=gender,hair='short02' if gender==0 else 'short01')
    root,body,parts=_family('Review_rig');hips=json.loads(root['c3d_landmarks'])['hips'][2]
    cloth=next(o for o in parts if 'casualsuit' in o.name)
    mat=cloth.material_slots[0].material;image=_image(mat)
    pixels=_pixels(image).reshape(image.size[1],image.size[0],4)
    cloth.data.calc_loop_triangles();uv=cloth.data.uv_layers.active.data
    p=coords(cloth.data.vertices);triangles=np.array([list(t.vertices) for t in cloth.data.loop_triangles])
    uvtri=np.array([[list(uv[i].uv) for i in t.loops] for t in cloth.data.loop_triangles]);centers=p[triangles].mean(1)
    camera=camera_shot(subject=[root.name],shot='full',angle=0,start_frame=1,end_frame=144,avoid_occlusion=False,depth_of_field=False)['camera']
    render_style(style='anime');cinematic_look(clear=True)
    result=dict(style=style,gender=gender,regions={},image=str(out/f'{gender}_{style}.png'),projection={},region_triangles={})
    reference=json.loads((out/f'{gender}_realistic.json').read_text()) if style!='realistic' else None
    for name,zmask in (('shirt',centers[:,2]>hips+.03),('trousers',centers[:,2]<hips-.03)):
        if reference:
            zmask=np.zeros(len(centers),bool);zmask[reference['region_triangles'][name]]=True
        result['region_triangles'][name]=np.flatnonzero(zmask).tolist()
        dominant,mask=visible_albedo(pixels,uvtri[zmask])
        result['regions'][name]=dict(albedo_srgb=dominant.tolist(),texels=int(mask.sum()))
        points=centers[zmask&(centers[:,1]<-.01)&(abs(centers[:,0])<.16)]
        projected=[world_to_camera_view(bpy.context.scene,bpy.data.objects[camera],cloth.matrix_world@Vector(v)) for v in points[::max(1,len(points)//250)]]
        result['projection'][name]=[[float(q.x*384),float((1-q.y)*384)] for q in projected if 0<q.x<1 and 0<q.y<1]
    render_preview(camera=camera,engine='eevee',width=384,height=384,filename=result['image'])
    (out/f'{gender}_{style}.json').write_text(json.dumps(result,indent=2))
    return result


def podcast(root_path):
    import bpy
    from engine.commands.scene import new_scene,scene_info
    from engine.commands.script_scene import script_to_scene
    from engine.commands.render import render_preview
    from engine.commands.io import save_project
    from engine.commands.render_style import render_style
    scene_info();new_scene(frame_end=144);isolate_assets()
    sc=bpy.context.scene;sc.render.threads_mode='FIXED';sc.render.threads=4;sc.eevee.taa_render_samples=16
    script='''JUDUL: Kabar Baik
LOKASI: podcast_studio
GAYA: anime
SUASANA: studio_film
LIA (perempuan, anime, rambut bob): Akhirnya karakter kita bisa bergerak. Senang sekali!
BIMA (laki-laki, chibi, rambut pendek): Serius?
LIA: Ekspresinya ikut berubah!
BIMA: Sekarang giliran kamu.
'''
    built=script_to_scene(script=script,sound=False,music=None,subtitles=False,life=.7,seed=11)
    out=Path(root_path)/'podcast';out.mkdir(parents=True,exist_ok=True)
    shots=built['shots'];records=[];animated=[]
    samples=[(item,sum(item['frames'])//2) for item in shots[:6]]
    if len(samples)==4:
        samples.insert(0,(shots[0],shots[0]['frames'][0]))
        samples.append((shots[-1],shots[-1]['frames'][1]))
    assert len(samples)==6,'The review needs six real frames'
    for style,items in (('anime',records),('animated_film',animated)):
        render_style(style=style)
        for i,(item,frame) in enumerate(samples):
            name=item['camera'] if 'camera' in item else item['name']
            path=out/f'{style}_shot_{i+1}.png'
            render_preview(camera=name,frame=frame,engine='eevee',width=512,height=288,filename=str(path))
            items.append(dict(camera=name,frame=frame,path=str(path),shot=item))
            (out/'results.json').write_text(json.dumps(dict(build=built,stills=records,animated_film=animated),indent=2))
    render_style(style='anime')
    save_project(path='round4/podcast.blend')
    return dict(build=built,stills=records,animated_film=animated)


def podcast_extra(root_path):
    """Resume four-cut evidence with real opening/closing frames, no new cameras."""
    from engine.commands.io import open_project
    from engine.commands.render import render_preview
    from engine.commands.render_style import render_style
    out=Path(root_path)/'podcast';report=json.loads((out/'results.json').read_text())
    if all(len(report[k])==6 for k in ('stills','animated_film')):return report
    open_project(path='round4/podcast.blend')
    shots=report['build']['shots']
    for style,key in (('anime','stills'),('animated_film','animated_film')):
        items=report[key];assert len(items)==4
        render_style(style=style)
        for name,item,frame in (('opening',shots[0],shots[0]['frames'][0]),('closing',shots[-1],shots[-1]['frames'][1])):
            path=out/f'{style}_{name}.png'
            render_preview(camera=item['camera'],frame=frame,engine='eevee',width=512,height=288,filename=str(path))
            items.append(dict(camera=item['camera'],frame=frame,path=str(path),shot=item))
        items.sort(key=lambda item:item['frame'])
        (out/'results.json').write_text(json.dumps(report,indent=2))
    return report


def dark_preview(root_path):
    from engine.commands.io import open_project
    from engine.commands.render_style import render_style
    from engine.commands.cinematic import cinematic_look
    from engine.commands.render import render_preview
    open_project(path='round4/after_dark.blend')
    render_style(style='anime');cinematic_look(preset='studio_film',dof='off')
    return render_preview(camera='Shot1',engine='eevee',width=384,height=384,filename=str(Path(root_path)/'dark_final_preview.png'))
