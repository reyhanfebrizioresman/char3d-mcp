"""Offline emotional editor contract. No bpy, TTS, network or file mutation."""
import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.emocam import emotion_curve, plan_coverage, mode, safe_cut, SIZES, camera_overrides
from engine.review import rhythm, camera_checks


def fixture(emotion='anger', count=6, seconds=8):
    lines, words = [], {'A': [], 'B': []}
    for i in range(count):
        a = 1+i*(seconds*24+12)
        who = 'AB'[i%2]
        text = ('Saya marah! Mengapa kamu menyembunyikan kabar penting ini?'
                if emotion=='anger' else 'Aku senang kamu kembali. Mari kita duduk bersama sebentar.')
        lines.append(dict(speaker=who,start=a,end=a+seconds*24-1,text=text,emotion=emotion))
        tokens = text.split()
        step = (seconds*24-8)/len(tokens)
        words[who] += [(w,a+j*step,a+(j+.80)*step) for j,w in enumerate(tokens)]
    return lines,words


def plan(emotion='anger', **kwargs):
    lines,words=fixture(emotion, **kwargs)
    return plan_coverage(lines,['A','B'],1,lines[-1]['end']+12,words=words),lines,words


def run():
    for alias in ('directed','emosi','emotional','EMOSI'):
        assert mode(alias)=='directed'
    angry,lines,words=plan()
    tender,tender_lines,tender_words=plan('tender')
    assert len(angry['shots'])>len(tender['shots']), (len(angry['shots']),len(tender['shots']))
    for result,case_lines,case_words in ((angry,lines,words),(tender,tender_lines,tender_words)):
        shots=result['shots']
        assert shots[0]['reason']['role']=='establish'
        assert any(s['reason']['role']=='reaction' for s in shots)
        assert any(s['reason']['role']=='OTS' for s in shots)
        assert any(s['frames'][1]-s['frames'][0]+1>=120 for s in shots), 'held breath'
        assert all(s['frames'][1]-s['frames'][0]+1>=24 for s in shots)
        for a,b in zip(shots,shots[1:]):
            assert a['frames'][1]+1==b['frames'][0]
            if a['subject']==b['subject']:
                assert abs(SIZES.index(a['size'])-SIZES.index(b['size']))>=2
        all_words=[w for group in case_words.values() for w in group]
        assert all(not any(round(a)<s['frames'][0]<round(b) for _,a,b in all_words) for s in shots)
        for reaction in result['reactions']:
            line=next(l for l in case_lines if l['speaker']==reaction['speaker'] and l['start']<=reaction['cut']<=l['end'])
            assert reaction['cut']>=line['start']+24
            assert .2*24 <= reaction['onset']-reaction['trigger_frame'] <= .5*24
            assert any(s['subject']==reaction['character'] and s['frames'][0]<=reaction['peak']<=s['frames'][1] for s in shots)
        views=[dict(s,name=str(i),size=s['size'],subject=[s['subject']] if s['subject'] else ['A','B']) for i,s in enumerate(shots)]
        assert not rhythm(views,24,all_words,duration=52), rhythm(views,24,all_words,duration=52)
        assert not [i for i in camera_checks(views) if i['severity']!='info']
    # Equal fixtures produce equal plans without mutating input or random state.
    source=copy.deepcopy((lines,words))
    a=plan_coverage(lines,['A','B'],1,lines[-1]['end']+12,words=words)
    b=plan_coverage(lines,['A','B'],1,lines[-1]['end']+12,words=words)
    assert a==b and (lines,words)==source
    low,_,_=plan('neutral',count=2)
    assert max(s['size']=='close_up' for s in angry['shots'])
    assert not any(s['size']=='close_up' for s in low['shots'])
    # Explicit emotion and saved facial cues beat local lexical guesses.
    events=emotion_curve([dict(speaker='A',start=1,end=90,text='Senang!',emotion='sad')])
    assert events[0]['emotion']=='sad' and events[0]['source']=='line'
    saved={'A':[dict(frames=[1,80],emotion='surprised',strength=.9,source='cue')]}
    events=emotion_curve([dict(speaker='A',start=1,end=90,text='Halo.')],emotions=saved)
    assert events[0]['emotion']=='surprise' and events[0]['source']=='cue'
    cues=[dict(do='camera',shot='close_up',subject=['A'],frames=[1,0]),
          dict(do='camera',shot='auto',frames=[400,399])]
    assert camera_overrides(cues,900)==[(1,399)]
    overridden=plan_coverage(lines,['A','B'],1,lines[-1]['end']+12,words=words,beats=cues)
    assert all(r['peak']>=400 for r in overridden['reactions'])
    # A late authored ending must not expose a seven-frame listener insert.
    late = next(s for s in reversed(a['shots']) if s['reason']['role']=='reaction')
    closing = late['frames'][0]+7
    ending = [dict(do='camera',shot='medium_full',move='dolly_out',frames=[closing,closing-1])]
    bounded = plan_coverage(lines,['A','B'],1,lines[-1]['end']+12,words=words,beats=ending)
    assert camera_overrides(ending,lines[-1]['end']+12)==[(closing,lines[-1]['end']+12)]
    visible = [s for s in bounded['shots'] if s['frames'][0]<closing]
    assert all(min(closing-1,s['frames'][1])-s['frames'][0]+1>=24 for s in visible)
    assert not any(s['frames'][0]==late['frames'][0] for s in bounded['shots'])
    assert not any(r['cut']==late['frames'][0] for r in bounded['reactions'])
    assert safe_cut(20,2,35,[('continuous',1,40)]) is None
    assert safe_cut(20,2,45,[('continuous',1,40)])==40
    # Speech energy raises intensity; bilingual emotions share direction.
    line=[dict(speaker='A',start=1,end=90,text='Hello.')]
    assert emotion_curve(line,energy={'A':{0:1}})[0]['intensity']>emotion_curve(line)[0]['intensity']
    for text in ('Aku marah!', 'I am angry!'):
        assert emotion_curve([dict(speaker='A',start=1,end=90,text=text)])[0]['emotion']=='anger'
    # Previous close ending motivates a wider opening in the next film scene.
    result=plan_coverage(lines,['A','B'],1,lines[-1]['end']+12,words=words,previous_size='close_up')
    assert result['shots'][0]['size']=='full'
    movement=[dict(do='walk',who='A',frames=[205,240])]
    result=plan_coverage(lines,['A','B'],1,lines[-1]['end']+12,words=words,beats=movement)
    assert any(s['subject'] is None and s['frames'][0]<=220<=s['frames'][1]
               and s['reason']['role']=='establish' for s in result['shots'])
    body=emotion_curve(lines,beats=[dict(do='gesture',who='A',name='cry',frames=[1,20])])
    assert any(e['source']=='body' and e['emotion']=='sad' for e in body)
    from engine.director_cues import direction
    assert direction('KAMERA: ots Ana')['shot']=='over_shoulder'
    assert direction('CAMERA: over shoulder Ana')['shot']=='over_shoulder'
    shock=plan_coverage([dict(speaker='A',start=1,end=220,text='Wah!')],['A','B'],1,232,
        emotions={'A':[dict(frames=[1,220],emotion='surprised',strength=1.,source='cue',sentence='Wah!')]})
    assert sum(s['move']=='crash_zoom' for s in shock['shots'])==1
    assert not any(s['size']=='extreme_close_up' and s['subject']=='A' for s in shock['shots']), 'talking face stays whole'
    for result in (angry,tender):
        seen={}
        for shot in result['shots']:
            who=shot['subject']
            if who is None:continue
            signature=(shot['size'],shot['move'],shot['reason']['role']=='OTS')
            if who in seen and shot['frames'][0]-seen[who][0]<=12*24:
                assert signature!=seen[who][1],(shot,seen[who])
            seen[who]=(shot['frames'][0],signature)
        assert sum(s['size']=='extreme_close_up' for s in result['shots'])<=1
    print('EMOCAM UNIT OK')

if __name__=='__main__':
    run()
