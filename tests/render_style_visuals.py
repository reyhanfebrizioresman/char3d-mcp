"""Render the same MPFB close/medium shots in every look and time warmed 540p frames.

CHAR3D_PORT=9980 CHAR3D_ALLOW_PYTHON=1 .venv/bin/python tests/render_style_visuals.py
Uses only existing installed assets; no downloads. Writes output/render_style_*.
"""
import json
import os
import sys
import time
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mcp_server.blender_client import BlenderClient  # noqa: E402

os.environ.setdefault('CHAR3D_PORT', '9980')
os.environ['CHAR3D_ALLOW_PYTHON'] = '1'
os.environ.setdefault('CHAR3D_WORKSPACE', os.path.join(ROOT, 'output', 'style_visuals'))
c = BlenderClient()


def engine(command, **params):
    if command == 'run_python':
        params['code'] = textwrap.dedent(params['code'])
    return c.call(command, **params)


if os.environ.get('CHAR3D_STYLE_SHEET_ONLY'):
    with open(os.path.join(ROOT,'output','render_style_benchmark.json')) as f:
        data=json.load(f)
    paths,timings=data['images'],data['timings']
    styles=list(paths)
else:
    print(engine('scene_info'), flush=True)
    project=os.path.join(os.environ['CHAR3D_WORKSPACE'],'projects','render_style_comparison.blend')
    if os.environ.get('CHAR3D_STYLE_REUSE') and os.path.exists(project):
        engine('open_project',path=project)
    else:
        engine('new_scene', frame_end=4)
        engine('run_python', code=f'''
        import addon_utils, importlib, os, shutil
        module='bl_ext.user_default.mpfb'
        source=os.path.join(bpy.utils.extension_path_user(module),'data')
        home={os.path.join(ROOT,'output','style_visuals','mpfb')!r}
        os.makedirs(home,exist_ok=True)
        data=os.path.join(home,'data')
        if os.path.isdir(source) and not os.path.isdir(data): shutil.copytree(source,data)
        cls=importlib.import_module(module+'._preferences').MpfbPreferences
        if 'bl_rna' not in cls.__dict__: bpy.utils.register_class(cls)
        addon=bpy.context.preferences.addons.get(module)
        if addon is None:
            addon=bpy.context.preferences.addons.new()
            addon.module=module
        addon.preferences.mpfb_user_data=home
        result=True
        ''')
        print(engine('create_realistic_human', name='StyleMaya',gender=0,age=28,race={'asian':1},
                     hair='ponytail01',outfit='casual',seed=11),flush=True)
        engine('apply_pose',armature='StyleMaya_rig',pose='relaxed')
        engine('set_expression',character='StyleMaya_rig',expression='smile',strength=.35)
        engine('set_environment',preset='podcast_studio',subject=['StyleMaya_rig'])
        engine('set_lighting',preset='studio',subject=['StyleMaya_rig'])
        engine('camera_shot',subject=['StyleMaya_rig'],shot='close_up',angle=8,start_frame=1,end_frame=2,name='StyleClose')
        engine('camera_shot',subject=['StyleMaya_rig'],shot='medium',angle=8,start_frame=3,end_frame=4,name='StyleMedium')
        engine('run_python', code='bpy.context.scene.render.resolution_x=960\nbpy.context.scene.render.resolution_y=540\nresult=True')
        engine('save_project',path='render_style_comparison.blend')
    styles = ['none','anime','clay','film','noir','vintage']
    paths, timings = {}, {}
    state_code = """
    import hashlib, json
    sc=bpy.context.scene
    result=dict(materials=[(m.name,m.node_tree.name if m.node_tree else None) for m in bpy.data.materials],
                objects=[(o.name,o.data.name if o.data else None,
                          [(s.link,s.material.name if s.material else None) for s in o.material_slots],
                          [(m.name,m.type) for m in o.modifiers]) for o in sc.objects],
                groups=sorted(g.name for g in bpy.data.node_groups),
                meshes=sorted(m.name for m in bpy.data.meshes),keys=sorted(k.name for k in bpy.data.shape_keys),
                view=[sc.view_settings.view_transform,sc.view_settings.look,sc.view_settings.exposure,sc.view_settings.gamma],
                world=sc.world.name if sc.world else None)
    """
    before = None
    for style in styles:
        print(engine('render_style',style=style),flush=True)
        if style=='none' and os.environ.get('CHAR3D_STYLE_REUSE_IMAGES'):
            paths[style]=[dict(path=os.path.join(os.environ['CHAR3D_WORKSPACE'],'renders',f'render_style_none_f{frame:04d}.png'),frame=frame) for frame in [1,3]]
            assert all(os.path.exists(item['path']) for item in paths[style])
        else:
            paths[style]=engine('render_frames',frames=[1,3],camera='scene',engine='eevee',size=512,prefix='render_style_'+style)['frames']
        print(paths[style],flush=True)
        state=engine('run_python',code=state_code)['result']
        if before is None: before=state
        assert state==before, style
    if not os.environ.get('CHAR3D_STYLE_IMAGES_ONLY'):
        for style in styles:
            engine('render_style',style=style)
            # Warm a full 540p frame, then measure two with identical framing/settings.
            # Timings include render-time override setup and restoration, PNG I/O included.
            elapsed=[]
            for repeat in range(3):
                start=time.perf_counter()
                engine('render_preview',camera='scene',engine='eevee',width=960,height=540,frame=1,
                       filename='benchmark_'+style+'.png')
                elapsed.append(time.perf_counter()-start)
            timings[style]={'seconds_per_frame':round(sum(elapsed[1:])/2,3),'samples':elapsed}
            print(style,timings[style],flush=True)
    for style in timings:
        timings[style]['ratio']=round(timings[style]['seconds_per_frame']/timings['none']['seconds_per_frame'],3)
    with open(os.path.join(ROOT,'output','render_style_benchmark.json'),'w') as f:
        json.dump({'timings':timings,'images':paths},f,indent=2)
# Build the contact sheet with Blender's own image API/numpy, avoiding extra deps.
print(engine('run_python',code=f'''
import numpy as np
import blf, imbuf, os
paths={paths!r}
styles={styles!r}
tile_w,tile_h=512,288
header=36
sheet=np.zeros((tile_h*2+header,tile_w*len(styles),4),dtype=np.float32)
sheet[:,:,3]=1
for col,style in enumerate(styles):
    label_path=os.path.join(os.path.dirname({os.path.join(ROOT,'output','render_style_contact_sheet.png')!r}), 'style_label_'+style+'.png')
    label=imbuf.new((tile_w,header))
    with blf.bind_imbuf(0,label,display_name='sRGB'):
        blf.size(0,22)
        blf.color(0,1,1,1,1)
        blf.position(0,16,9,0)
        blf.draw_buffer(0,style.upper())
    imbuf.write(label,filepath=label_path)
    del label
    label_img=bpy.data.images.load(label_path,check_existing=False)
    label_pixels=np.empty(tile_w*header*4,dtype=np.float32)
    label_img.pixels.foreach_get(label_pixels)
    sheet[tile_h*2:,col*tile_w:(col+1)*tile_w,:3]=label_pixels.reshape(header,tile_w,4)[:,:,:3]
    bpy.data.images.remove(label_img)
    os.remove(label_path)
    for row,item in enumerate(paths[style]):
        img=bpy.data.images.load(item['path'],check_existing=False)
        pixels=np.empty(tile_w*tile_h*4,dtype=np.float32)
        img.pixels.foreach_get(pixels)
        sheet[(1-row)*tile_h:(2-row)*tile_h,col*tile_w:(col+1)*tile_w]=pixels.reshape(tile_h,tile_w,4)
        bpy.data.images.remove(img)
img=bpy.data.images.new('Style contact sheet',width=tile_w*len(styles),height=tile_h*2+header)
img.pixels.foreach_set(sheet.ravel())
img.filepath_raw={os.path.join(ROOT,'output','render_style_contact_sheet.png')!r}
img.file_format='PNG'
img.save()
bpy.data.images.remove(img)
result=True
'''),flush=True)
print(json.dumps(timings,indent=2),flush=True)
