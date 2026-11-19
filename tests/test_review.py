"""Pure directing/review contracts: synthetic signals and mocked online generators."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine.review import rhythm,camera_checks,subtitle_checks,audio_metrics,wer,safe_fixes,issue,call,articulation_present,camera_followups
from engine.credits import collect
from engine.script_plan import parse_script
from engine.film_plan import parse_film,transition,layout
from engine.music.cues import resolve
from providers.director import direct
from providers.director.common import options,validate,SCHEMA
from providers.director.offline import Backend
from providers.director.treatment import validate_treatment


def shot(name,a,b,angle=0,side=1,size='medium'):
    return dict(name=name,frames=[a,b],subject=['Ana'],size=size,move='static',angle=angle,action_side=side)


def ids(issues): return {i['id'].split(':')[0] for i in issues}


class ReviewTests(unittest.TestCase):
    def test_segment_bounds_parallel_and_inside(self):
        from engine.ray_bounds import intersects
        targets=np.array([[0,0,0],[4,0,0],[2,3,0],[-2,0,0],[2,.5,0],[2,0,3]])
        self.assertEqual(intersects([2,0,0],targets,[-1,-1,-1],[1,1,1]).tolist(),[True,False,False,True,False,False])
        self.assertTrue(intersects([0,0,0],targets,[-1,-1,-1],[1,1,1]).all())

    def test_rhythm_and_cuts(self):
        shots=[shot('a',1,12),shot('b',13,36),shot('c',37,300)]
        found=rhythm(shots,24,[('word',10,20)],duration=40)
        self.assertTrue({'short_shot','word_cut','long_static'}<=ids(found))
        self.assertIn('even_pace',ids(rhythm([shot(str(i),i*48+1,(i+1)*48) for i in range(5)],24)))
        self.assertNotIn('short_shot',ids(rhythm([dict(shot('hit',1,10),deliberate=True)],24)))

    def test_jump_and_line(self):
        found=camera_checks([shot('a',1,24,5),shot('b',25,48,15,-1)])
        self.assertTrue({'jump_cut','line_crossing'}<=ids(found))
        self.assertNotIn('jump_cut',ids(camera_checks([shot('a',1,24,0),shot('b',25,48,50)])))
        tiny=shot('tiny',1,24,size='close_up');tiny['samples']=[dict(head_chest_height=.05,eye_y=.05,face_edge=True)]
        self.assertTrue({'small_subject','eye_line','face_visibility'}<=ids(camera_checks([tiny])))

    def test_native_camera_repairs_and_directing_suggestions(self):
        shots=[shot('a',1,12),shot('b',13,72),shot('c',73,400)]
        for s in shots:
            s['repair']=[call('camera_shot',subject=s['subject'],shot=s['size'],move=s['move'],
                             name=s['name'],start_frame=s['frames'][0],end_frame=s['frames'][1],action_line=['Ana','Budi'])]
        shots[2].update(samples=[dict(head_chest_height=.03)],face_angle=100)
        findings=rhythm(shots,24)+camera_checks(shots)
        for rule in ('short_shot','long_static','face_turned'):
            finding=next(i for i in findings if i['id'].split(':')[0]==rule)
            self.assertTrue(finding['fix']);self.assertFalse(finding['auto_fixable'])
        for finding in findings:
            if finding['id'].split(':')[0] in ('jump_cut','small_subject'):
                self.assertTrue(finding['auto_fixable']);self.assertEqual(finding['fix'][0]['tool'],'camera_shot')
                self.assertEqual(finding['fix'][0]['args']['action_line'],['Ana','Budi'])
        self.assertEqual(next(i for i in findings if i['id'].startswith('jump_cut:b'))['fix'][0]['args']['shot'],'full')
        remaining=camera_followups(shots,findings,[dict(call('camera_shot',name='c'),status='applied')])
        small=next(i for i in remaining if i['id'].startswith('small_subject:'))
        self.assertFalse(small['auto_fixable']);self.assertTrue(small['evidence']['refit_attempted'])
        self.assertEqual(small['fix'][0]['args']['shot'],'medium_close')

    def test_localized_editorial_draft_and_arrangement(self):
        from engine.music.description import describe
        from engine.music.soundfont import arrangement
        from engine.director_cues import direction
        for en in (False,True):
            r=direct('dua sahabat lama bertemu lagi di taman setelah sepuluh tahun',generator='offline',language='en' if en else 'id',seed=3)
            self.assertFalse(r['plan']['warnings'])
            self.assertTrue(any(b.get('shot')=='auto' for b in r['plan']['beats']))
            cues=[ln for ln in r['script'].splitlines() if ln.startswith(('[KAMERA:','[CAMERA:'))]
            self.assertTrue(all('_' not in ln for ln in cues))
            self.assertIn('[MUSIC: calm]' if en else '[MUSIK: tenang]',r['script'])
            self.assertIn('[SILENCE 1 second]' if en else '[HENING 1 detik]',r['script'])
            self.assertNotIn('[CAMERA:' if not en else '[KAMERA:',r['script'])
            self.assertIn('ten years' if en else 'sepuluh tahun',r['treatment']['logline'])
            self.assertTrue(all(b['event'] not in ('camera','music','look','interact') for b in r['treatment']['beat_sheet']))
            self.assertGreaterEqual(len({s['reason'] for s in r['treatment']['shot_list']}),4)
            self.assertIn('Establish' if en else 'Kenalkan',r['treatment']['shot_list'][0]['reason'])
            self.assertIn('all characters' if en else 'semua tokoh',r['treatment']['beat_sheet'][1]['event'])
        self.assertEqual(direction('KAMERA: medium close-up Ana, diam')['shot'],'medium_close')
        self.assertIn('rambut ekor kuda',direct('dua sahabat reuni di taman',generator='offline',seed=7)['script'])
        self.assertIn('rambut bob',direct('dua sahabat, perempuan berambut bob',generator='offline',seed=7)['script'])
        synth=describe('warm',backend='synth');self.assertIn('piano elektrik',synth)
        with patch('engine.music.description.resolve_backend',return_value='soundfont'):
            sf=describe('warm');self.assertIn(f"GM {arrangement('warm')['melody']}",sf)
            self.assertNotEqual(sf,describe('calm'))

    def test_caption_hold_cps_and_wer(self):
        chunks=[dict(start=1,end=13,words=[('A very long caption to read immediately',1,10)])]
        self.assertTrue({'subtitle_hold','subtitle_speed'}<=ids(subtitle_checks(chunks,24)))
        good=[dict(start=1,end=73,words=[('Welcome.',2,24)])]
        self.assertEqual(subtitle_checks(good,24),[])
        self.assertEqual(wer('Aku pulang sekarang','Aku pulang'),1/3)

    def test_loudness_gain_and_clipping(self):
        t=np.arange(48000)/48000
        x=np.repeat((.1*np.sin(2*np.pi*1000*t))[:,None],2,axis=1)
        a,b=audio_metrics(x),audio_metrics(x*.5)
        self.assertAlmostEqual(a['lufs']-b['lufs'],6.0206,places=2)
        self.assertAlmostEqual(a['true_peak_dbfs']-b['true_peak_dbfs'],6.0206,places=2)
        self.assertEqual(audio_metrics(np.zeros((48000,2)))['lufs'],-100)
        self.assertGreater(audio_metrics(x*20)['clipped_samples'],0)

    def test_audio_only_mouth_coverage(self):
        from types import SimpleNamespace
        self.assertFalse(articulation_present([],1,48))
        self.assertFalse(articulation_present([SimpleNamespace(evaluate=lambda f:.6)],1,48))
        self.assertTrue(articulation_present([SimpleNamespace(evaluate=lambda f:.3+.2*math.sin(f))],1,48))

    def test_one_round_merges_safe_sound_fixes(self):
        findings=[issue('ambience','sound','warn','missing',fix=[call('auto_sfx',kinds=['ambience'])],auto=True),
                  issue('steps','sound','warn','missing',fix=[call('auto_sfx',characters=['Ana'],kinds=['footsteps'])],auto=True),
                  issue('duck','sound','warn','masking',fix=[call('duck_music')],auto=True),
                  issue('mask','sound','warn','masking',fix=[call('duck_music',amount_db=-18)],auto=True),
                  issue('story','rhythm','warn','suggestion',fix=[call('script_to_scene',script='new story')],auto=True)]
        before=copy.deepcopy(findings);batch=safe_fixes(findings)
        self.assertEqual(findings,before)
        self.assertEqual(len(batch),2)
        self.assertEqual(batch[0]['args']['kinds'],['ambience','footsteps'])
        self.assertNotIn('characters',batch[0]['args'])
        self.assertEqual(batch[1]['args']['amount_db'],-18)

    def test_encoded_black_and_frozen_video(self):
        import av
        import tempfile
        from engine.review_media import review_video
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.mp4'
            with av.open(str(path),'w') as container:
                stream=container.add_stream('libx264',rate=8)
                stream.width,stream.height,stream.pix_fmt=96,64,'yuv420p'
                for _ in range(40):
                    frame=av.VideoFrame.from_ndarray(np.zeros((64,96,3),np.uint8),format='rgb24')
                    for packet in stream.encode(frame):container.mux(packet)
                for packet in stream.encode(None):container.mux(packet)
            report=review_video(str(path))
            self.assertTrue({'black_frames','frozen_frames','missing_audio'}<=ids(report['issues']))
            self.assertEqual(report['frames'],40)
            self.assertAlmostEqual(report['video_duration_s'],5,places=2)

    def test_credits_used_only_and_licences(self):
        evidence=dict(mpfb=[dict(name='bob01',pack='system'),dict(name='coat',pack='winter01')],
            voices=[dict(engine=k,voice=k+':voice') for k in ('piper','edge','f5','chatterbox')],
            soundfonts=[dict(path='/font.sf2',licence_file='/LICENSE.txt')],
            whisper=['tiny'],fonts=[dict(path='/font.ttf')],imports=['/user.glb'],procedural=['Foley'])
        result=collect(evidence)
        content=json.dumps(result,ensure_ascii=False)
        for required in ('CC0','GPL-3.0','CC-BY-NC','Microsoft','Hugging Face','system font — check licence','winter01','user is responsible'):
            self.assertIn(required,content)
        self.assertNotIn('unused_skin',content)
        evidence['mpfb'].append(evidence['mpfb'][0]); self.assertEqual(collect(evidence),result)

    def test_bilingual_cues_and_zero_duration(self):
        for camera,music,silence,auto in (
            ('KAMERA: close-up Ana, push in','MUSIK: tegang','HENING 1 detik','KAMERA: otomatis'),
            ('CAMERA: close-up Ana, push in','MUSIC: tense','SILENCE 1 second','CAMERA: auto')):
            p=parse_script('Ana: Hello.\n'+''.join('['+v+']\n' for v in (camera,music,silence,auto)))
            self.assertEqual(p['warnings'],[])
            self.assertEqual([b.get('do') for b in p['beats'][1:]],['camera','music','silence','camera'])
            a,b,c,d=p['beats'][1:];self.assertEqual(a['estimated_frames'][0],b['estimated_frames'][0])
            self.assertEqual(c['estimated_frames'][1]-c['estimated_frames'][0]+1,24)
            self.assertEqual(a['subject'],['Ana']);self.assertEqual(d['shot'],'auto')
        self.assertTrue(parse_script('Ana: Hello.\n[CAMERA: imaginary fly]')['warnings'])
        self.assertIsNone(parse_script('Ana: Hi.\n[MUSIC: stop]')['beats'][-1]['mood'])
        p=parse_script(dict(characters=[dict(id='Ana')],beats=[dict(do='camera',shot='wide'),dict(say='Ana',text='Hi')]))
        self.assertEqual(p['beats'][0]['estimated_frames'],[1,0])
        self.assertEqual(resolve([dict(frame=26,mood='tense')],120,24,1,240)[0]['frame'],49)

    def test_audio_transition_handles_keep_alignment(self):
        for cue,kind in (('J-cut','j_cut'),('L-cut','l_cut')):
            tr=transition('dissolve 0.5 detik, '+cue+' 0.4')
            self.assertEqual(tr['audio'],kind)
            scenes=[dict(frames=[1,120],transition_in=transition()),dict(frames=[1,120],transition_in=tr)]
            layout(scenes,24)
            self.assertEqual(scenes[1]['source_in_frames'] if kind=='j_cut' else scenes[0]['source_out_frames'],10)
            # The source audio offset and picture source trim agree at every visible frame.
            self.assertEqual(scenes[1]['audio_offset_frames'],scenes[1]['film_frames'][0]-1-scenes[1]['source_in_frames'])
        p=parse_film('SCENE: A\nAna: Hello.\n[TRANSITION: cut, J-cut 0.2]\nSCENE: B\nAna: Goodbye.')
        self.assertEqual(p['scenes'][1]['transition_in']['audio'],'j_cut')
        with self.assertRaises(ValueError):transition('cut, J-cut nan')

    def test_treatment_all_generators_and_repair(self):
        opts=options('dua sahabat reuni di taman',characters=2,seed=7)
        payload=Backend().generate(opts)
        validate_treatment(payload['treatment']);validate(payload,opts)
        self.assertIn('treatment',SCHEMA['required'])
        self.assertEqual(len(payload['treatment']['structures']['candidates']),3)
        plan=parse_script(payload['script'],seed=7)
        self.assertTrue({'camera','music','silence'}<={b.get('do') for b in plan['beats']})
        self.assertNotEqual(payload['treatment']['logline'],opts['idea'])
        from providers.director import claude,claude_cli
        for provider,name in ((claude,'claude'),(claude_cli,'claude_cli')):
            with patch.object(provider.Backend,'available',return_value=True),patch.object(provider.Backend,'generate',return_value=copy.deepcopy(payload)):
                result=direct(opts['idea'],generator=name,characters=2,seed=7,consent=True)
                self.assertEqual(result['generator'],name);validate_treatment(result['treatment'])
                self.assertIn('## Treatment',result['brief'])
            invalid=copy.deepcopy(payload);invalid['treatment']['cue_map']['tempo']=float('nan')
            with patch.object(provider.Backend,'available',return_value=True),patch.object(provider.Backend,'generate',side_effect=[invalid,copy.deepcopy(payload)]) as mocked:
                self.assertEqual(direct(opts['idea'],generator=name,characters=2,seed=7,consent=True)['generator'],name)
                self.assertEqual(mocked.call_count,2)
            with patch.object(provider.Backend,'available',return_value=True),patch.object(provider.Backend,'generate',return_value=invalid) as mocked:
                self.assertEqual(direct(opts['idea'],generator=name,characters=2,seed=7,consent=True)['generator'],'offline')
                self.assertEqual(mocked.call_count,2)
        for name in ('offline','claude','claude_cli'):
            if name=='offline':validate_treatment(direct('a reunion',generator=name)['treatment'])
        film=direct('dua sahabat di kafe lalu taman',generator='offline',duration_s=60)
        self.assertEqual(len(film['plan']['scenes']),3)
        validate_treatment(film['treatment'])

    def test_director_rejects_lost_speaker_and_long_override(self):
        opts=options('dua sahabat reuni di taman',characters=2,seed=3)
        good=Backend().generate(opts)
        lost=copy.deepcopy(good)
        lost['script']=lost['script'].replace('[KAMERA: medium full dua tokoh, diam]',
            '[KAMERA: medium '+good['characters'][1]['id']+', diam]',1)
        long=copy.deepcopy(good);long['script']=long['script'].replace('[KAMERA: otomatis]\n','',1)
        for bad in (lost,long):
            with self.assertRaisesRegex(ValueError,'kamera'):validate(bad,opts)
        from providers.director import claude,claude_cli
        for provider,name in ((claude,'claude'),(claude_cli,'claude_cli')):
            with patch.object(provider.Backend,'available',return_value=True),patch.object(provider.Backend,'generate',side_effect=[lost,copy.deepcopy(good)]) as mocked:
                result=direct(opts['idea'],generator=name,characters=2,seed=3,consent=True)
                self.assertEqual(result['generator'],name);self.assertEqual(mocked.call_count,2)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if not result.wasSuccessful():sys.exit(1)
    print('REVIEW UNIT OK')
