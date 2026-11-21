"""Offline VRM casting/path/metadata/continuity contracts; no Blender or downloads."""
import copy
import json
import os
import struct
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine.vrm import actor_path,metadata,read_document,dialog_declarations,face_regions,gaze_degrees
import numpy as np
from engine.script_plan import parse_script
from engine.film_plan import parse_film
from engine.credits import collect,text


def reject(fn,*args):
    try:fn(*args)
    except ValueError:return
    raise AssertionError((fn,args))


def fixture(path,version=0):
    meta={'title':'Base_Female','author':'Original author','licenseName':'CC0'} if not version else {
        'name':'Original Male','authors':['A','B'],'licenseUrl':'https://example.test/licence'}
    document={'asset':{'version':'2.0'},'extensions':{('VRM' if not version else 'VRMC_vrm'):{'meta':meta}}}
    raw=json.dumps(document).encode();raw+=b' '*((-len(raw))%4)
    path.write_bytes(struct.pack('<4sIIII',b'glTF',2,20+len(raw),len(raw),0x4e4f534a)+raw)


def main():
    assert gaze_degrees({'extensions':{'VRM':{'firstPerson':{
        'lookAtHorizontalInner':{'xRange':90,'yRange':8},
        'lookAtHorizontalOuter':{'yRange':12}}}}})==dict(In=8.,Out=12.,Up=17.1887,Down=17.1887)
    assert gaze_degrees({'extensions':{'VRMC_vrm':{'lookAt':{
        'rangeMapHorizontalInner':{'inputMaxValue':90,'outputScale':7},
        'rangeMapVerticalUp':{'outputScale':0}}}}})['In']==7
    assert gaze_degrees({'extensions':{'VRMC_vrm':{'lookAt':{
        'rangeMapVerticalUp':{'outputScale':0}}}}})['Up']==0
    # A coupled authored surprise has lip + eyelid + brow motion. Listener eye
    # aliases preserve eyelids while leaving the mouth and brows independent.
    regions=face_regions([0,.5,1.,1.4],eye=1.,mouth=0.,brow_indices=[3])
    authored=np.ones((4,3))
    assert not (authored*regions['eye'][:,None])[[0,3]].any()
    assert regions['eye'][2]==1 and regions['mouth'][0]==1 and regions['mouth'][2]==0
    shifted=face_regions(np.array([0,.5,1.,1.4])*2+7,eye=9.,mouth=7.,brow_indices=[3])
    assert all(np.array_equal(regions[k],shifted[k]) for k in regions)
    with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,CHAR3D_WORKSPACE=directory):
        root=Path(directory)/'imports';(root/'vrm').mkdir(parents=True)
        fixture(root/'vrm'/'sample.vrm');fixture(root/'sample.vrm',1)
        path,rel=actor_path('sample.vrm');assert rel=='vrm/sample.vrm'
        assert metadata(path)['licence']=='CC0'
        assert metadata(root/'sample.vrm')['author']==['A','B']
        reject(actor_path,'../../outside.vrm');reject(actor_path,'model.glb');reject(actor_path,'')
        outside=Path(directory)/'outside.vrm';fixture(outside)
        (root/'bad.vrm').symlink_to(outside);reject(actor_path,'bad.vrm')
        script={'characters':[{'id':'Nara','vrm':'sample.vrm','outfit':'winter','hair':'bob01','age':27}],
                'beats':[{'say':'Nara','text':'Halo!'}]}
        before=copy.deepcopy(script);p=parse_script(script)
        assert before==script
        char=p['characters'][0]
        assert char['gender']==0 and char['age']==27 and char['vrm']=='vrm/sample.vrm'
        assert char['vrm_meta']['author']=='Original author'
        assert not set(char)&{'hair','outfit','clothes','style'}
        assert sum('ignored for VRM' in w for w in p['warnings'])==2
        assert parse_script(p)['characters']==p['characters']
        explicit=parse_script('NARA (vrm: sample.vrm, pria, 33, rambut bob): Halo!')['characters'][0]
        assert explicit['vrm']=='vrm/sample.vrm' and explicit['gender']==1 and explicit['age']==33
        entries, notes, mapping=dialog_declarations([{'id':'Nara','vrm':'sample.vrm','gender':0},'Existing_rig'])
        assert mapping['nara']['gender']==0 and entries[1]=='Existing_rig'
        reject(dialog_declarations,[{'id':'Nara'}])
        missing=parse_script('A (vrm: missing.vrm): Halo!')
        assert missing['characters'][0]['vrm_meta']['status']=='unverified'
        assert any('sex hint' in w for w in missing['warnings'])
        film=parse_film({'characters':[{'id':'Nara','vrm':'sample.vrm'}], 'scenes':[
            {'beats':[{'say':'Nara','text':'Satu'}]},
            {'beats':[{'do':'outfit','who':'Nara','outfit':'formal'},{'say':'Nara','text':'Dua'}]}]})
        assert film['scenes'][0]['plan']['characters']==film['scenes'][1]['plan']['characters']
        assert any('same VRM persists' in w for w in film['warnings'])
        middle=parse_film({'characters':[{'id':'Nara','vrm':'sample.vrm'}], 'scenes':[
            {'beats':[{'say':'Nara','text':'Halo'},{'do':'outfit','who':'Nara','outfit':'formal'}]}]})
        assert len(middle['scenes'][0]['plan']['beats'])==1 and any('ignored' in w for w in middle['warnings'])
        report=collect({'vrm':[dict(char['vrm_meta'],path=str(path))]})
        assert report['assets'][0]['kind']=='VRM' and 'Original author' in text(report) and 'CC0' in text(report)
        corrupt=root/'corrupt.vrm';corrupt.write_bytes(b'bad');reject(read_document,corrupt)
        (root/'vrm'/'sample.vrm').unlink()
        assert actor_path('sample.vrm')[1]=='sample.vrm'
    print('VRM ACTORS UNIT OK')

if __name__=='__main__':main()
