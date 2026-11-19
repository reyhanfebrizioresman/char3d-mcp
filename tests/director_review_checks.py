"""Generated scenes must pass the same camera/rhythm rules used for user scenes."""
import json

CASES = (
    ('reunion3', 'dua sahabat lama bertemu lagi di taman setelah sepuluh tahun', 3),
    ('reunion7', 'dua sahabat bertemu lagi di taman saat senja setelah sepuluh tahun', 7),
    ('confession2', 'dua sahabat mengaku ingin lebih sering bertemu di teras kafe', 2),
)


async def setup(call, work):
    # Test-only writable MPFB preferences and periodic diagnostics for slow native builds.
    await call('run_blender_python', {'code': f'''import importlib,os,shutil
module='bl_ext.user_default.mpfb'
source=os.path.join(bpy.utils.extension_path_user(module),'data')
home={str(work / 'director_mpfb')!r}
os.makedirs(home,exist_ok=True)
if not os.path.isdir(os.path.join(home,'data')): shutil.copytree(source,os.path.join(home,'data'))
cls=importlib.import_module(module+'._preferences').MpfbPreferences
if 'bl_rna' not in cls.__dict__: bpy.utils.register_class(cls)
a=bpy.context.preferences.addons.get(module)
if a is None:
    a=bpy.context.preferences.addons.new();a.module=module
a.preferences.mpfb_user_data=home
from engine.commands import dispatch
dispatch('mpfb_assets',{{}})
bpy.context.scene.render.threads_mode='FIXED'
bpy.context.scene.render.threads=4
import faulthandler
faulthandler.dump_traceback_later(600,repeat=True)
result=True
'''}, 'test_setup')


async def run(call, work, case=None):
    path=work/'director_polish_reviews.json'
    evidence=json.loads(path.read_text()) if case and path.is_file() else []
    chosen=[c for c in CASES if case is None or c[0]==case]
    for index,(name,idea,seed) in enumerate(chosen):
        if index:
            await call('engine_shutdown',{},name+'_stop_previous')
            await call('scene_info',{},name+'_fresh_engine')
            await call('new_scene',{'frame_end':2},name+'_reset')
            await setup(call,work)
        evidence=[e for e in evidence if e['name']!=name]
        draft=await call('direct_scene',dict(idea=idea,generator='offline',language='id',duration_s=30,seed=seed),name+'_draft')
        built=await call('script_to_scene',dict(script=draft['script'],voice=True,sound=True,subtitles=True,
                                               **draft['build_options']),name+'_build')
        reviewed=await call('review_scene',dict(level='standard',size=384),name+'_review')
        entry=dict(name=name,seed=seed,draft=draft,build=built,review=reviewed)
        evidence.append(entry)
        (work/'director_polish_reviews.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        assert all(c['realistic'] for c in built['characters'].values()),built['warnings']
        findings=[i for i in reviewed['issues'] if i['category'] in ('rhythm','camera') and i['severity'] in ('warn','error')]
        assert not findings,(name,findings)
        assert reviewed['score']>=90,(name,reviewed['score'],reviewed['issues'])
        # Every speaking turn is either in a group view or its own single.
        for line in built['lines']:
            middle=(line['start']+line['end'])//2
            shot=next(s for s in reviewed['shots'] if s['frames'][0]<=middle<=s['frames'][1])
            assert line['speaker'] in shot['subject'],(name,line,shot)
        assert not any(s['move']=='static' and (s['frames'][1]-s['frames'][0]+1)/24>6 for s in reviewed['shots'])
        await call('save_project',dict(path='director_polish_'+name+'.blend'),name+'_save')
        print(f"DIRECTOR REVIEW {name}: {reviewed['score']}, camera/rhythm clear",flush=True)
    print('DIRECTOR REVIEWS OK',flush=True)
    return evidence
