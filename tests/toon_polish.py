"""Measured, resumable visual review over the real MCP interface on port 9971.

Run one case at a time: python tests/toon_polish.py --case f_anime
Then --sheet. No optional downloads and no camera/renderer implementation edits.
"""
import argparse
import hashlib
import asyncio
import json
import os
from pathlib import Path
import shutil
import struct
import sys

import av
import numpy as np
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from e2e_smoke import isolate_mpfb,text_of
from toon_checks import LIDS
OUT=Path(os.environ.get('CHAR3D_TOON_REVIEW_DIR',str(ROOT/'output/toon_polish')))

PROXY='''
from engine.commands.toon import anatomy,neutral_coords,face_metrics
from engine.commands.materials import _family
root,body,meshes=_family('Review_rig')
p=neutral_coords(body);_,top,chin,_=anatomy(body,meshes,p)
head=p[(p[:,2]>=chin)&(p[:,2]<=top)]
lo=head.min(0);hi=head.max(0);hi[2]=top+(top-chin)*.09
me=bpy.data.meshes.new('ReviewBounds');me.from_pydata([(x,y,z) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])],[],[])
o=bpy.data.objects.new('ReviewBounds',me);bpy.context.collection.objects.link(o);o.hide_render=True
from engine.commands.anim import semantic_map
metrics=face_metrics(body,meshes);smap=semantic_map(root)
height=metrics['face_height_m']*metrics['head_ratio']
for label,bones in (('leg',('thigh.L','shin.L')),('arm',('upper_arm.L','forearm.L'))):
 metrics[label+'_length_height']=sum(root.data.bones[smap[k]].length for k in bones)/height
result=metrics
'''

CURRENT_FACE="""
import numpy as np
from engine.commands.toon import coords,LIP_PAIRS
from engine.toon import LID_PAIRS
body=bpy.data.objects['Review']
mask_states=[(m,m.show_viewport) for m in body.modifiers if m.type=='MASK']
try:
 for m,_ in mask_states:m.show_viewport=False
 bpy.context.view_layer.update()
 evaluated=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
 q=coords(mesh.vertices);evaluated.to_mesh_clear()
 result=dict(frame=bpy.context.scene.frame_current,
   lid_gap3d_m=max(float(np.linalg.norm(q[a]-q[b])) for pairs in LID_PAIRS.values() for a,b in pairs),
   lip_gap_m=max(abs(float(q[a,2]-q[b,2])) for a,b in LIP_PAIRS))
finally:
 for m,value in mask_states:m.show_viewport=value
"""

async def run(case,smile_only=False):
    assert os.environ.get('CHAR3D_PORT')=='9971'
    source_hash=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in ('engine/toon.py','engine/commands/toon.py'))).hexdigest()
    sex,style=case.split('_');gender=0 if sex=='f' else 1
    OUT.mkdir(exist_ok=True,parents=True)
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        async def call(tool,**kw):
            print(case,tool,flush=True)
            value=await session.call_tool(tool,kw)
            assert not value.isError,text_of(value)
            return json.loads(text_of(value)[0])
        async def still(label,size=384,**kw):
            result=await call('render_preview',width=size,height=size,engine_name='eevee',**kw)
            dst=OUT/(case+'_'+label+'.png');shutil.copyfile(result['path'],dst)
            assert struct.unpack('>II',dst.read_bytes()[16:24])==(size,size)
            return str(dst)
        try:
            await call('scene_info');await call('new_scene',frame_end=180);await isolate_mpfb(session)
            build=await call('create_realistic_human',name='Review',style=style,gender=gender,
                             rig='rigify' if style=='cartoon' else 'game_engine',race={'asian':1},
                             hair='short02' if sex=='f' else 'short01',
                             clothes=[('female' if sex=='f' else 'male')+'_casualsuit01','shoes01'])
            metrics=(await call('run_blender_python',code=PROXY))['result']
            contract=None
            if style!='realistic':
                contract=(await call('run_blender_python',code=LIDS.replace('CHARACTER',"'Review_rig'")))['result']
                assert max(v['blink_gap3d_m'] for v in contract['lids'].values())<.0002,contract
                assert contract['visible_eye_samples']['open']>=4 and contract['visible_eye_samples']['closed']==0,contract
                assert contract['rest_face_error_m']<.003,contract
                assert abs(metrics['head_ratio']-{'anime':6.75,'cartoon':4.75,'chibi':2.8}[style])<.1,metrics
                assert metrics['lip_gap_m']['p_b_m_21']<.0003,metrics
                assert metrics['lip_gap_m']['aa_02']>.008 and metrics['lip_gap_m']['ow_08']>.002,metrics
            await call('render_views',objects=['Review_rig'],size=320)
            await call('apply_pose',armature='Review_rig',pose='relaxed')
            await call('set_lighting',preset='soft',subject=['Review_rig'])
            await call('render_style',style='anime')
            front=None if smile_only else await still('front',objects=['Review_rig'],view='front')
            shot=await call('camera_shot',subject=['ReviewBounds'],shot='medium_full',lens=85,angle=25,
                            start_frame=1,end_frame=180,avoid_occlusion=False,depth_of_field=False)
            if smile_only:
                assert case=='f_anime'
                await call('set_expression',character='Review_rig',expression='smile',strength=1)
                evidence=json.loads((OUT/(case+'.json')).read_text())
                evidence['poses']['smile']=await still('smile',size=256,camera=shot['camera'])
                evidence['smile_source_hash']=source_hash
                (OUT/(case+'.json')).write_text(json.dumps(evidence,indent=2))
                await call('save_project',path='round3_smile_'+case+'.blend')
                print('POLISH SMILE OK',case,flush=True)
                return
            portrait=await still('three_quarter',camera=shot['camera'])
            await call('save_project',path='polish_'+case+'.blend')
            evidence=dict(case=case,source_hash=source_hash,build=build,metrics=metrics,contract=contract,front=front,three_quarter=portrait,poses={})
            (OUT/(case+'.json')).write_text(json.dumps(evidence,indent=2))
            if case=='f_anime':
                for expression in ('smile','surprised','look_left','look_right'):
                    await call('set_expression',character='Review_rig',expression=expression,strength=1)
                    evidence['poses'][expression]=await still(expression,size=256,camera=shot['camera'])
                await call('set_expression',character='Review_rig',expression='neutral')
                blink=await call('auto_blink',character='Review_rig',frame_start=1,frame_end=48,interval_seconds=1.5)
                evidence['poses']['blink']=await still('blink',size=256,camera=shot['camera'],frame=blink['blinks'][0]+2)
                evidence['peak_measurements']={'blink':(await call('run_blender_python',code=CURRENT_FACE))['result']}
                assert evidence['peak_measurements']['blink']['lid_gap3d_m']<.0002,evidence
                peak_values=(await call('run_blender_python',code="b=bpy.data.objects['Review'].data.shape_keys.key_blocks;result=[b['eyeBlinkLeft'].value,b['eyeBlinkRight'].value]"))['result']
                assert min(peak_values)>.99,peak_values
                speech=await call('lip_sync',character='Review_rig',text='Mama. Opa. Aku.',language='id',start_frame=60)
                for label,viseme in [('A','aa_02'),('O','ow_08'),('MBP','p_b_m_21')]:
                    peak=next(p['frame'] for p in speech['phonemes'] if p['viseme']==viseme and p['frame'] is not None)
                    evidence['poses'][label]=await still(label,size=256,camera=shot['camera'],frame=peak)
                    measured=(await call('run_blender_python',code=CURRENT_FACE))['result']
                    evidence['peak_measurements'][label]=measured
                    assert (measured['lip_gap_m']<.0003 if label=='MBP' else measured['lip_gap_m']>(.008 if label=='A' else .002)),measured
            if case=='f_chibi':
                walk=await call('walk_path',armature='Review_rig',points=[[0,-.4]],start_frame=1,avoid=False)
                evidence['poses']['walk']=await still('walk',objects=['Review_rig'],view='three_quarter',frame=round(sum(walk['frames'])/2))
                chair=await call('add_prop',kind='chair',location=[0,-.4,0],scale=.45)
                seat=await call('sit_on',character='Review_rig',seat=chair['root'],start_frame=walk['next_start_frame'])
                assert abs(seat['contact_error_m'])<.003 and seat['max_ik_error_m']<.01,seat
                evidence['seat']=seat
                evidence['poses']['seated']=await still('seated',objects=['Review_rig',chair['root']],view='three_quarter',frame=seat['frames'][-1])
            (OUT/(case+'.json')).write_text(json.dumps(evidence,indent=2))
            print('POLISH CASE OK',case,metrics,flush=True)
        finally:
            await session.call_tool('engine_shutdown',{})

# A deliberately small original bitmap label font; no Pillow/font dependency.
FONT={
'A':['01110','10001','10001','11111','10001','10001','10001'],
'B':['11110','10001','10001','11110','10001','10001','11110'],
'C':['01111','10000','10000','10000','10000','10000','01111'],
'E':['11111','10000','10000','11110','10000','10000','11111'],
'F':['11111','10000','10000','11110','10000','10000','10000'],
'G':['01111','10000','10000','10111','10001','10001','01110'],
'K':['10001','10010','10100','11000','10100','10010','10001'],
'H':['10001','10001','10001','11111','10001','10001','10001'],
'I':['11111','00100','00100','00100','00100','00100','11111'],
'L':['10000','10000','10000','10000','10000','10000','11111'],
'M':['10001','11011','10101','10101','10001','10001','10001'],
'N':['10001','11001','10101','10011','10001','10001','10001'],
'O':['01110','10001','10001','10001','10001','10001','01110'],
'Q':['01110','10001','10001','10001','10101','10010','01101'],
'R':['11110','10001','10001','11110','10100','10010','10001'],
'S':['01111','10000','10000','01110','00001','00001','11110'],
'T':['11111','00100','00100','00100','00100','00100','00100'],
'U':['10001','10001','10001','10001','10001','10001','01110'],
'V':['10001','10001','10001','10001','10001','01010','00100'],
'W':['10001','10001','10001','10101','10101','10101','01010'],
'Y':['10001','10001','01010','00100','00100','00100','00100'],
'D':['11110','10001','10001','10001','10001','10001','11110'],
'P':['11110','10001','10001','11110','10000','10000','10000']}

def read(path):
    with av.open(str(path)) as container:return next(container.decode(video=0)).to_ndarray(format='rgb24')

def save(path,pixels):
    with av.open(str(path),'w',format='image2') as container:
        stream=container.add_stream('png',rate=1);stream.width=pixels.shape[1];stream.height=pixels.shape[0];stream.pix_fmt='rgb24'
        for packet in stream.encode(av.VideoFrame.from_ndarray(pixels,format='rgb24')):container.mux(packet)
        for packet in stream.encode():container.mux(packet)

def label(canvas,text,x,y):
    for char in text.upper():
        for row,line in enumerate(FONT.get(char,['00000']*7)):
            for col,bit in enumerate(line):
                if bit=='1':canvas[y+row*2:y+row*2+2,x+col*2:x+col*2+2]=240
        x+=12

def sheet():
    styles=('realistic','anime','cartoon','chibi')
    pixels=np.full((4*410,4*384,3),28,np.uint8)
    for row,(sex,view) in enumerate((('f','front'),('f','three_quarter'),('m','front'),('m','three_quarter'))):
        for col,style in enumerate(styles):
            pixels[row*410+26:row*410+410,col*384:(col+1)*384]=read(OUT/(sex+'_'+style+'_'+view+'.png'))
            label(pixels,('FEMALE ' if sex=='f' else 'MALE ')+('FRONT ' if view=='front' else 'QUARTER ')+style.upper(),col*384+6,row*410+5)
    save(OUT/'comparison.png',pixels)
    print('POLISH COMPARISON SHEET OK',OUT/'comparison.png')
    poses=('blink','A','O','MBP','smile','surprised','look_left','look_right')
    cells=[read(OUT/('f_anime_'+pose+'.png')) for pose in poses]
    size=cells[0].shape[0]
    assert all(cell.shape==(size,size,3) for cell in cells)
    panels=np.full((2*(size+26),4*size,3),28,np.uint8)
    for i,(pose,cell) in enumerate(zip(poses,cells)):
        row,col=divmod(i,4);panels[row*(size+26)+26:(row+1)*(size+26),col*size:(col+1)*size]=cell
        label(panels,pose.replace('_',' '),col*size+6,row*(size+26)+5)
    save(OUT/'expressions.png',panels)
    motions=np.full((410,768,3),28,np.uint8)
    for col,pose in enumerate(('walk','seated')):
        motions[26:,col*384:(col+1)*384]=read(OUT/('f_chibi_'+pose+'.png'))
        label(motions,'CHIBI '+pose.upper(),col*384+6,5)
    save(OUT/'motion.png',motions)
    # Keep the actual four-sided workbench renders available for visual audit.
    import re
    views={}
    for block in (ROOT/'output/logs/blender.log').read_text(errors='replace').split('CHAR3D_READY '):
        case=re.search(r'Saved as "polish_([fm]_(?:realistic|anime|cartoon|chibi))\.blend"',block)
        if not case:continue
        paths={}
        for path,view in re.findall(r"Saved: '([^']*/preview_(front|right|back|three_quarter)_[^']+\.png)'",block):
            paths.setdefault(view,path)
        if len(paths)==4:views[case[1]]=paths
    if len(views)==8:
        board=np.full((8*346,4*320,3),28,np.uint8)
        for row,case in enumerate(sex+'_'+style for sex in ('f','m') for style in styles):
            for col,view in enumerate(('front','right','back','three_quarter')):
                board[row*346+26:(row+1)*346,col*320:(col+1)*320]=read(views[case][view])
                label(board,case.replace('_',' ')+' '+view.replace('_',' '),col*320+4,row*346+4)
        save(OUT/'workbench.png',board)
        (OUT/'workbench_paths.json').write_text(json.dumps(views,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case');parser.add_argument('--sheet',action='store_true');parser.add_argument('--smile-only',action='store_true');args=parser.parse_args()
    if args.sheet:sheet()
    else:asyncio.run(run(args.case,args.smile_only))
