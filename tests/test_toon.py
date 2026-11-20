"""Offline toon/VRM/photo contracts, synthetic fitting and mocked ONNX tensors."""
from pathlib import Path
import json
import math
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine.toon import PRESETS, RestMap, iris_pixels, style_name, LID_PAIRS, LOWER_RIM, UPPER_RIM, lid_taper
from engine.vrm import BONES, bone_map, expression_map, addon_bones, addon_expressions, eye_rotation_delta
from engine.photo_fit import validate, photo_path, project, fit_modifiers, likeness_geometry
from engine.looks import validate_look
from unittest.mock import patch
import json,os
from engine.photo_landmarks import detect, model_files, model_directory, decode_heatmaps
from engine.toon_appearance import downsample_rgba,visible_albedo
from engine.script_plan import parse_script


def rejects(fn, *args, **kwargs):
    try:
        fn(*args,**kwargs)
    except (ValueError,RuntimeError,FileNotFoundError):
        return
    raise AssertionError((fn,args,kwargs))


def main():
    assert len(LID_PAIRS['R'])==len(UPPER_RIM)==14
    assert set(b for a,b in LID_PAIRS['R'])==set(LOWER_RIM)
    assert LID_PAIRS['L']==tuple((a+6784,b+6784) for a,b in LID_PAIRS['R'])
    # Fourteen-point lid ink previously produced NaN at its final vertex.
    for count in (7,14):
        taper=lid_taper(np.arange(count)/(count-1))
        assert np.isfinite(taper).all() and taper.min()>=0
        assert max(taper[0],taper[-1])<1e-6
    for name,preset in PRESETS.items():
        mapping = RestMap(name,0,1.8,1.56,[[-.03,-.08,1.69],[.03,-.08,1.69]])
        pts = np.array([[0,0,0],[0,0,1.56],[0,0,1.8]])
        mapped = mapping(pts,features=False)
        if name=='realistic':
            assert np.array_equal(mapped,pts)
        else:
            assert abs((mapped[-1,2]-mapped[0,2])/(mapped[-1,2]-mapped[1,2])-preset['heads'])<1e-8
        assert abs(mapped[0,2])<1e-10 and abs(mapped[-1,2]-mapping.output_top)<1e-10
        # Shared mapping keeps coincident closed lid points coincident.
        closed = mapping([[-.03,-.09,1.69],[-.03,-.09,1.69]])
        assert np.array_equal(closed[0],closed[1])
        # Socket expansion must not fold the facial surface into an outlined ridge.
        for z in (1.66,1.69,1.72):
            x=np.linspace(-.1,.1,401)
            line=mapping(np.c_[x,np.full_like(x,-.09),np.full_like(x,z)])
            assert np.diff(line[:,0]).min()>0,(name,z)
    # Short limbs must not drag off-axis feet up with the arm field. Neck
    # interpolation has one shared derivative across the head/torso boundary.
    for name in ('anime','cartoon','chibi'):
        warp=RestMap(name,0,1.8,1.56,[[-.03,-.08,1.69],[.03,-.08,1.69]])
        foot=warp([[.15,-.1,0]],features=False)
        assert abs(foot[0,2])<1e-8,(name,foot)
        z=np.linspace(0,1.8,1501)
        q=warp(np.c_[np.zeros_like(z),np.zeros_like(z),z],features=False)
        assert np.diff(q[:,2]).min()>0,name
        epsilon=1e-6
        joint=warp([[0,-.09,1.56-epsilon],[0,-.09,1.56],[0,-.09,1.56+epsilon]])
        slopes=np.diff(joint[:,2])/epsilon
        assert abs(slopes[0]-slopes[1])<.001,(name,slopes)
        # Mirrored eye fields must have a smooth sagittal join. abs(x)-based
        # masks can make a cusp here and leak the inverted hull down the forehead.
        mid=warp([[-epsilon,-.09,1.74],[0,-.09,1.74],[epsilon,-.09,1.74]])
        join=np.diff(mid[:,2])/epsilon
        assert abs(join[0]-join[1])<.001,(name,join)
        # Eye remapping has compact support; it must not move scalp/chin or
        # introduce a seam at the bottom of the head.
        ends=warp([[0,-.09,1.56],[0,-.09,1.8]])
        assert abs(ends[0,2]-warp.new_chin)<1e-9
        assert abs(ends[1,2]-warp.output_top)<1e-9
        vertical=warp(np.c_[np.full_like(z,.03),np.full_like(z,-.09),z])
        assert np.diff(vertical[:,2]).min()>0,name
    assert style_name('kartun')=='cartoon' and style_name('realistis')=='realistic'
    rejects(style_name,'pirate');rejects(style_name,None)
    iris = iris_pixels()
    assert iris.shape==(256,256,4) and np.isfinite(iris).all()
    assert (iris[128,128,:3]<.03).all() and (iris[180,90,:3]>.9).all()
    # A 1024-wide atlas with a white first column used to turn a blue shirt
    # white. Unused UV margins and a small orange print must remain distinct.
    pixels=np.ones((1024,1024,4),np.float32)
    pixels[128:896,128:896,:3]=[.025,.18,.50]
    pixels[300:500,400:600,:3]=[.8,.22,.015]
    small=downsample_rgba(pixels)
    triangles=[[[.125,.125],[.875,.125],[.875,.875]],[[.125,.125],[.875,.875],[.125,.875]]]
    dominant,mask=visible_albedo(small,triangles)
    assert np.max(abs(dominant-[.025,.18,.50]))<1e-6
    assert (small[:,:,0][mask]>.6).sum()>100,'simplified print lost'
    irregular=np.full((37,211,4),.3,np.float32)
    assert np.max(abs(downsample_rgba(irregular,32)-.3))<1e-6
    for name in ('anime','cartoon','chibi'):
        warp=RestMap(name,0,1.8,1.56,[[-.03,-.08,1.69],[.03,-.08,1.69]])
        inner=.03-.073*.24
        bridge=warp([[-inner,-.09,1.69],[inner,-.09,1.69]])
        assert np.ptp(bridge[:,0])/(warp.output_top-warp.new_chin)>.035,(name,bridge)
    for desc,expected in (('gaya anime','anime'),('anime','anime'),('kartun','cartoon'),
                          ('cartoon','cartoon'),('chibi','chibi'),('realistis','realistic'),('realistic','realistic')):
        plan = parse_script('GAYA: anime\nA ('+desc+'): Halo!\nB: Hello!')
        assert plan['characters'][0]['style']==expected and plan['characters'][1]['style']=='anime'
        assert not plan['warnings'],plan['warnings']
    for header in ('GAYA','STYLE'):
        plan = parse_script(header+': anime\nA (realistis): Hi!\nB (kartun): Hello!')
        assert [c['style'] for c in plan['characters']]==['realistic','cartoon']
    plan = parse_script(dict(style='anime',characters=[dict(id='A',style='chibi')],beats=[dict(say='A',text='Halo')]))
    assert plan['characters'][0]['style']=='chibi'
    plan = parse_script('GAYA: anime\nA: Hallo',style='none')
    assert 'style' not in plan['characters'][0]
    rejects(parse_script,dict(characters=[dict(id='A',style='unknown')],beats=[dict(say='A',text='Hi')]))

    source = {k:'unrecognizable_'+str(i) for i,k in enumerate(BONES)}
    for side in ('left','right'):
        for finger in ('Thumb','Index','Middle','Ring','Little'):
            for part in ('Proximal','Intermediate','Distal'):
                source[side+finger+part]=side+finger+part+'_joint'
    mapped,fingers = bone_map(source)
    assert set(mapped)==set(BONES.values()) and len(fingers['L'])==5
    assert mapped['upper_arm.R']==source['rightUpperArm']
    source1 = {''.join('_'+c.lower() if c.isupper() else c for c in k):v for k,v in source.items()}
    source1['left_thumb_metacarpal']='thumb_base'
    assert bone_map(source1)[1]['L']['thumb'][0]=='thumb_base'
    mapped = expression_map({'A':[('Face','Mouth_A',1)],'I':[('Face','Mouth_I',.7)],
                             'Blink':[('Face','Closed',1)],'Joy':[('Face','Smile',1)],
                             'blinkLeft':[('Face','LeftClosed',1)],'Surprised':[('Face','Wow',1)]})
    # Normalization accepts VRM0 preset casing and VRM1 camelCase independently.
    assert mapped['jawOpen']==[('Face','Mouth_A',1)]
    assert mapped['eyeBlinkRight']==[('Face','Closed',.5)]
    assert mapped['eyeBlinkLeft']==[('Face','LeftClosed',1)]
    assert sum(b[2] for k in ('mouthSmileLeft','mouthSmileRight') for b in mapped[k])==1
    node=SimpleNamespace(bone_name='OriginalHip')
    bind1=SimpleNamespace(node=SimpleNamespace(mesh_object_name='Face'),index='A',weight=.8)
    bind0=SimpleNamespace(mesh=SimpleNamespace(mesh_object_name='Face'),index='Blink',weight=1.)
    ext1=SimpleNamespace(spec_version='1.0',vrm1=SimpleNamespace(
        humanoid=SimpleNamespace(human_bones=SimpleNamespace(hips=SimpleNamespace(node=node))),
        expressions=SimpleNamespace(preset=SimpleNamespace(aa=SimpleNamespace(morph_target_binds=[bind1])))))
    ext0=SimpleNamespace(spec_version='0.0',vrm0=SimpleNamespace(
        humanoid=SimpleNamespace(human_bones=[SimpleNamespace(bone='hips',node=node)]),
        blend_shape_master=SimpleNamespace(blend_shape_groups=[SimpleNamespace(preset_name='blink',binds=[bind0])])))
    assert addon_bones(ext0)==addon_bones(ext1)==dict(hips='OriginalHip')
    assert addon_expressions(ext1)=={'aa':[('Face','A',.8)]}
    assert expression_map(addon_expressions(ext0))['eyeBlinkLeft']==[('Face','Blink',.5)]
    ext0.vrm0.blend_shape_master.blend_shape_groups.append(SimpleNamespace(
        preset_name='unknown',name='Surprised',binds=[SimpleNamespace(mesh=SimpleNamespace(mesh_object_name='Face'),index='Wow',weight=1)]))
    assert expression_map(addon_expressions(ext0))['eyeWideLeft']==[('Face','Wow',.5)]
    assert expression_map({'blink':[('Face','Blink',1)],'blinkLeft':[]})['eyeBlinkLeft']==[('Face','Blink',.5)]
    delta=eye_rotation_delta([[0,-1,0],[0,-1,0]],[0,0,0],[0,0,1],math.pi/2,[1,.5])
    assert np.allclose(delta,[[1,1,0],[.5,.5,0]])

    for consent in (False,None,0,1,'yes'):
        rejects(validate,consent,1)
    validate(True,1)
    for strength in (-1,2,math.nan,math.inf,True):
        rejects(validate,True,strength)
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp);imports=workspace/'imports';imports.mkdir()
        path=imports/'face.png';path.write_bytes(b'synthetic')
        assert photo_path(tmp,'face.png')==path
        rejects(photo_path,tmp,'../outside.jpg')
        rejects(photo_path,tmp,'https://example.com/face.jpg')
        outside=workspace/'outside.png';outside.write_bytes(b'x')
        (imports/'link.png').symlink_to(outside)
        rejects(photo_path,tmp,'link.png')
        nested=workspace/'nested';nested.mkdir()
        (nested/'imports').symlink_to(imports,target_is_directory=True)
        rejects(photo_path,nested,'face.png')
        rejects(model_files,workspace)
        modeldir=workspace/'models';modeldir.mkdir()
        for name in ('mnv3_detection_opt.onnx','lm_model0_opt.onnx'):
            (modeldir/name).write_bytes(b'mocked, never used by ONNX')
        inputs = []
        heat=np.zeros((198,28,28),dtype=np.float32);heat[66:]=.5
        positions = np.tile([14,14],(66,1))
        positions[36:42]=[10,12];positions[42:48]=[18,12];positions[30]=[14,15]
        for i,(x,y) in enumerate(positions):heat[i,y,x]=.95
        class MockSession:
            def __init__(self,path):self.detection=path.name.startswith('mnv3')
            def get_inputs(self):return [SimpleNamespace(name='input')]
            def run(self,_,feed):
                value=feed['input'];inputs.append(value)
                assert value.shape==(1,3,224,224) and value.dtype==np.float32
                if self.detection:
                    output=np.zeros((1,2,56,56),dtype=np.float32)
                    output[0,0,28,28]=.95;output[0,1,28,28]=.65
                    return [output,output[:,:1].copy()]
                return [heat[None]]
        detection=detect(np.full((300,300,3),.5,dtype=np.float32),modeldir,MockSession)
        assert json.loads(json.dumps(detection))['box'] == detection['box']
        assert len(detection['landmarks'])==66 and min(detection['confidence'])>.9 and len(inputs)==2
    # Offset planes have different nonzero row/column values, so swapping them
    # cannot pass this regression (unlike an all-0.5 mocked offset tensor).
    tensor=np.full((198,28,28),.5,dtype=np.float32)
    tensor[:66]=0;tensor[:66,5,21]=.95
    tensor[66:132]=1/(1+np.exp(-16*.03))
    tensor[132:]=1/(1+np.exp(16*.02))
    points,confidence=decode_heatmaps(tensor,(10,20,210,180))
    expected=[10+200*223/224*(21/27-.02),20+160*223/224*(5/27+.03)]
    assert np.max(abs(points-expected))<1e-4 and min(confidence)>.9
    json.dumps(detection)  # real inference previously failed on NumPy crop ints.
    recipe=dict(version=1,style='anime',seed=37,modifiers={'chin-width':.2},colors_srgb={'skin':[.5,.4,.3]},assets={'hair':'short02'})
    assert validate_look(json.loads(json.dumps(recipe)))==recipe
    rejects(validate_look,dict(recipe,modifiers={'untrusted':.3}))
    rejects(validate_look,dict(recipe,asset_fit={'hair':'untrusted'}))
    rejects(validate_look,dict(recipe,color_strength=True))
    rejects(validate_look,dict(recipe,colors_srgb={'hair':[float('nan'),0,0]}))
    planned=parse_script(dict(characters=[dict(id='A',look=recipe)],beats=[dict(say='A',text='Hello')]))
    assert planned['characters'][0]['look']==recipe and planned['characters'][0]['style']=='anime'
    with tempfile.TemporaryDirectory() as tmp:
        home=Path(tmp);shared=home/'.local/share/char3d/face';fallback=home/'workspace/models/face'
        fallback.mkdir(parents=True)
        for name in ('mnv3_detection_opt.onnx','lm_model0_opt.onnx'):(fallback/name).touch()
        with patch('engine.photo_landmarks.Path.home',return_value=home),patch.dict(os.environ,{},clear=True):
            assert model_directory(home/'workspace')==fallback
            shared.mkdir(parents=True)
            for name in ('mnv3_detection_opt.onnx','lm_model0_opt.onnx'):(shared/name).touch()
            assert model_directory(home/'workspace')==shared
            with patch.dict(os.environ,{'CHAR3D_FACE_MODEL_DIR':str(home/'explicit')}):assert model_directory(home/'workspace')==home/'explicit'
    rng=np.random.default_rng(17)
    base=rng.normal(size=(40,3))*.05
    deltas=rng.normal(size=(8,40,3))*.01
    deltas[:,:12]=0  # independent unmodified anchors constrain the camera.
    known=np.array([.3,-.4,.2,.1,-.25,.35,.45,-.15])
    camera=np.array([1800,.04,220,180])
    target=project(base+np.einsum('m,mnc->nc',known,deltas),camera)
    for calibration in (camera,None):
        fit=fit_modifiers(base,deltas,target,camera=calibration)
        assert np.max(abs(fit['coefficients']-known))<1e-4,fit
        assert fit['rmse_px']<1e-4,fit
    tilted=np.r_[camera,.12,-.06]
    target=project(base+np.einsum('m,mnc->nc',known,deltas),tilted)
    fit=fit_modifiers(base,deltas,target,allow_yaw=True)
    assert np.max(abs(fit['coefficients']-known))<1e-4 and np.max(abs(fit['camera']-tilted))<1e-4,fit
    rejects(fit_modifiers,base,deltas,np.full((40,2),np.nan))
    landmarks=rng.normal(size=(66,2));rot=np.array([[.98,-.2],[.2,.98]])
    same=likeness_geometry(landmarks,landmarks@rot*3+[50,90])
    assert same['score']>99.99 and not same['identity_probability'],same
    for installer in ('install_vrm.sh','install_face_landmarks.sh'):
        result=subprocess.run(['bash',str(ROOT/'scripts'/installer),'--dry-run'],capture_output=True,text=True,check=True)
        assert 'TOON INSTALL DRY RUN OK' in result.stdout and 'Licence:' in result.stdout and 'URL:' in result.stdout
    print('TOON UNIT OK')


if __name__=='__main__':main()
