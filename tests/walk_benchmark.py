"""Deterministic cached locomotion matrix, baseline 42487f5 and candidate.

CHAR3D_PORT=9977 CHAR3D_ALLOW_PYTHON=1 LIBGL_ALWAYS_SOFTWARE=1 \
GALLIUM_DRIVER=llvmpipe CHAR3D_WORKSPACE=$PWD/output/walk_round9 \
/home/reyhan/projects/char3d-engine/.venv/bin/python tests/walk_benchmark.py --label v9 --baseline
Repeat with --label v10. --body/--case select cheap iterations; --resume reuses
completed cases only when their source/fixture fingerprints match. No renders.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp_server.blender_client import BlenderClient

BODIES = {'male': dict(gender=1, age=32, hair='short02', outfit='casual', seed=3),
          'female_short': dict(gender=0, age=32, height=.3, hair='short02', outfit='casual', seed=3),
          'male_tall_heavy': dict(gender=1, age=32, height=.9, weight=.9, muscle=.8,
                                  hair='short02', outfit='casual', seed=3)}
CASES = {f'straight_{s}': dict(points=[[0, -5]], speed=s) for s in (.6, 1., 1.6)}
CASES.update(short_start_stop=dict(points=[[0, -1.5]]),
             cruise_stop=dict(points=[[0, -3]]),
             s_curve=dict(points=[[0, -1.5], [1, -2.5], [1, -4], [0, -5]]))
for angle in (45, 90):
    # Facing -Y, anatomical left is +X (positive world-Z yaw).
    for side, sign in (('left', 1), ('right', -1)):
        CASES[f'turn_{angle}_{side}'] = dict(points=[[0, -2],
            [sign*2*math.sin(math.radians(angle)), -2-2*math.cos(math.radians(angle))]])
for side, initial in (('left', .001), ('right', -.001)):
    # 179.999 degrees on either side of the shortest-path tie, rounded to 180.
    CASES['pivot_180_'+side] = dict(target=[initial, 100])

PHASES = dict(loading=.05, mid_stance=.2, terminal_stance=.4, pre_swing=.55)
ENVELOPE = dict(loading=[15,20], mid_stance=[5,12], terminal_stance=[5,15],
                pre_swing=[30,40], toe_off=[35,45], peak_swing=[55,65])
REFERENCES = [
    dict(url='https://pubmed.ncbi.nlm.nih.gov/10199275/',
         note='Nawoczenski et al. 1999: 33 subjects, mean dynamic first-MTP dorsiflexion 42 degrees; clinical heel-rise 58 degrees is a different measure.'),
    dict(url='https://pmc.ncbi.nlm.nih.gov/articles/PMC9405699/',
         note='G.A.I.T. 2022: separates plantarflexion from toe extension; its observational push-off criterion is 10 degrees, illustrating differences between clinical conventions.'),
    dict(url='https://www.medicine.missouri.edu/sites/default/files/pm-r/Normal_Gait.pdf',
         note='Normal Gait teaching reference: ankle plantarflexion 20 degrees at toe-off.'),
]


def summarize(nav, measured, turning=False, speed=1.):
    rows = measured['rows']; first = rows[0]['frame']; fps = 24
    def row(f): return rows[max(0, min(len(rows)-1, int(f)-first))]
    def foot(f, s): return row(f)['feet'][s]
    def peak(values): return max(values, default=0.)
    def drift(s, a, b, field):
        anchor = foot(a, s)[field]
        return peak(math.dist(foot(f, s)[field], anchor) for f in range(a, b+1))
    def rotation_drift(s,a,b):
        anchor = foot(a,s)['foot_rotation_wxyz']
        def distance(q):
            dot = abs(sum(x*y for x,y in zip(q,anchor)))/math.sqrt(sum(x*x for x in q)*sum(x*x for x in anchor))
            return 2*math.acos(min(1.,dot))
        return peak(distance(foot(f,s)['foot_rotation_wxyz']) for f in range(a,b+1))
    contacts = nav['foot_lock']['contacts']
    flat_drift = peak(drift(s, a, b, 'ankle_m') for s in 'LR' for a,b in contacts[s])
    flat_rotation = peak(rotation_drift(s,a,b) for s in 'LR' for a,b in contacts[s])
    flat_gap = peak(abs(foot(f,s)['sole_gap_m']) for s in 'LR' for a,b in contacts[s] for f in range(a,b+1))
    penetration = max(0., peak(-r['feet'][s]['sole_gap_m'] for r in rows for s in 'LR'))
    toe_drift = peak(drift(e['side'], e['opposite_land'], e['lift'], 'toe_m')
                     for e in nav['support_events'] if e['opposite_land'] <= e['lift'])
    yaw = {'single_support': 0., 'double_support': 0., 'flight': 0.}
    for r in rows:
        supports = sum(r['feet'][s].get('interval_support', r['feet'][s]['support'] != 'swing') for s in 'LR')
        yaw[['flight','single_support','double_support'][supports]] += abs(r['yaw_rate_deg_s'])/fps
    total_yaw = sum(yaw.values())
    steps = []
    for s in 'LR':
        other = 'R' if s == 'L' else 'L'
        lands = sorted(set([first]+[e['frame'] for e in nav['footfalls'] if e['side'] == s]))
        for idx,a in enumerate(lands):
            b = lands[idx+1] if idx+1 < len(lands) else rows[-1]['frame']
            ev = next((e for e in nav['support_events'] if e['side'] == s and e['land'] == b), None)
            complete = ev is not None and a != first
            end = b if ev is not None else rows[-1]['frame']
            segment = [r for r in rows if a <= r['frame'] < end]
            if not segment: continue
            frames = {k: round(a+(b-a)*u) for k,u in PHASES.items()} if complete else {}
            if ev:
                frames['toe_off'] = ev['lift']
                frames['peak_swing'] = max(range(ev['lift'], b+1), key=lambda f: foot(f,s)['knee_deg'])
            phases = {k: dict(frame=f, **{key: foot(f,s)[key] for key in
                ('knee_deg','foot_roll_deg','ankle_plantarflexion_deg','mtp_extension_deg')}) for k,f in frames.items()}
            yaw_a = math.radians(row(a)['yaw_deg'])
            fw = (math.sin(yaw_a), -math.cos(yaw_a)); lat = (math.cos(yaw_a), math.sin(yaw_a))
            delta = [foot(a,s)['heel_m'][i]-foot(a,other)['heel_m'][i] for i in (0,1)]
            warnings = [k+'_knee' for k,v in phases.items() if complete and not ENVELOPE[k][0] <= v['knee_deg'] <= ENVELOPE[k][1]]
            jump = peak(r['feet'][s]['knee_delta_deg'] for r in segment)
            if jump >= 15: warnings.append('knee_delta_ge_15')
            # The standing/braking exclusion follows cadence; a fixed 30-frame
            # window would erase every interior cycle in the fast tall fixture.
            transition_frames = max(1, round(30/speed))
            opposite_land = max([first]+[e['frame'] for e in nav['footfalls']
                                         if e['side']==other and e['frame'] <= a])
            # Width uses TWO heels. A new cruise strike opposite a still-wide
            # acceleration footprint is a transition until both were replaced.
            cruise = (complete and min(a, opposite_land) > first+transition_frames
                      and b < rows[-1]['frame']-transition_frames)
            width = abs(sum(x*y for x,y in zip(delta,lat)))
            if cruise and not .045*measured['dimensions_m'][2] <= width <= .075*measured['dimensions_m'][2]:
                warnings.append('width_outside_stature_envelope')
            if complete:
                if not 5 <= foot(a,s)['progression_outward_deg'] <= 10:
                    warnings.append('progression_outside_5_10')
            if complete and not turning:
                v = phases['toe_off']['ankle_plantarflexion_deg']
                if not 15 <= v <= 20: warnings.append('ankle_toe_off_outside_15_20')
                mtp = phases['toe_off']['mtp_extension_deg']
                if mtp is not None and not 40 <= mtp <= 55: warnings.append('mtp_toe_off_outside_40_55')
            local_yaw = {'single_support':0., 'double_support':0., 'flight':0.}
            for r in segment:
                rr = row(r['frame']+1)
                support_count = sum(rr['feet'][q].get('interval_support',rr['feet'][q]['support']!='swing') for q in 'LR')
                local_yaw[['flight','single_support','double_support'][support_count]] += abs(rr['yaw_rate_deg_s'])/fps
            local_flat = [(max(a,x), min(end,y)) for x,y in contacts[s] if max(a,x) <= min(end,y)]
            steps.append(dict(side=s, land=a, next_land=b if ev is not None else None,
                kind='cruise' if cruise else 'transition',
                complete_cycle=complete, phases=phases,
                transition='standing_start' if a == first else 'closing_hold' if ev is None else None,
                phase_duration_s={**({k:(b-a)*(v-u)/fps for k,u,v in
                    [('loading',0,.1),('mid_stance',.1,.3),('terminal_stance',.3,.5),('pre_swing',.5,.6),('swing',.6,1)]} if complete else {}),
                    'observed_stance':sum(foot(r['frame']+1,s).get('interval_support', r['feet'][s]['support'] != 'swing') for r in segment)/fps},
                release_frame=ev['lift'] if ev else None,
                double_support_fraction=sum(all(foot(r['frame']+1,q).get('interval_support', r['feet'][q]['support'] != 'swing') for q in 'LR') for r in segment)/len(segment),
                step_width_m=width,
                step_length_m=sum(x*y for x,y in zip(delta,fw)),
                progression_outward_deg=foot(a,s)['progression_outward_deg'],
                flat_drift_m=peak(drift(s,x,y,'ankle_m') for x,y in local_flat),
                flat_rotation_rad=peak(rotation_drift(s,x,y) for x,y in local_flat),
                penetration_m=max(0.,peak(-r['feet'][s]['sole_gap_m'] for r in segment)),
                max_yaw_deg_s=peak(abs(r['yaw_rate_deg_s']) for r in segment),
                rotation_degrees_by_support=local_yaw,
                max_knee_delta_deg=jump, warnings=warnings))
    sides = {}
    for s in 'LR':
        subset = [x for x in steps if x['side'] == s and x['complete_cycle']]
        sides[s] = {k: sum(x[k] for x in subset)/len(subset) if subset else None for k in
                    ('step_length_m','step_width_m','progression_outward_deg','double_support_fraction','max_knee_delta_deg')}
    asymmetry = {k: abs(sides['L'][k]-sides['R'][k]) if all(sides[s][k] is not None for s in 'LR') else None for k in sides['L']}
    phase_means = {}
    for s in 'LR':
        subset = [x for x in steps if x['side']==s and x['kind']=='cruise']
        phase_means[s] = {phase:{channel:sum(x['phases'][phase][channel] for x in subset)/len(subset)
                                   if subset and all(x['phases'][phase][channel] is not None for x in subset) else None
                                for channel in ('knee_deg','foot_roll_deg','ankle_plantarflexion_deg','mtp_extension_deg')}
                          for phase in ENVELOPE}
    phase_asymmetry = {phase:{channel:abs(phase_means['L'][phase][channel]-phase_means['R'][phase][channel])
                                       if all(phase_means[s][phase][channel] is not None for s in 'LR') else None
                              for channel in phase_means['L'][phase]} for phase in ENVELOPE}
    destination = nav.get('destination', rows[0]['pelvis_m'][:2])
    summary = dict(flat_drift_m=flat_drift, flat_rotation_rad=flat_rotation, flat_floor_m=flat_gap, toe_drift_m=toe_drift,
                   mesh_penetration_m=measured['mesh_penetration_m'], mesh_flat_gap_m=measured['mesh_flat_gap_m'],
                   penetration_m=penetration, max_knee_delta_deg=peak(r['feet'][s]['knee_delta_deg'] for r in rows for s in 'LR'),
                   max_yaw_deg_s=peak(abs(r['yaw_rate_deg_s']) for r in rows),
                   rotation_degrees_by_support=yaw,
                   double_support_rotation_fraction=yaw['double_support']/total_yaw if total_yaw else 0.,
                   destination_error_m=math.dist(rows[-1]['pelvis_m'][:2], destination),
                   hold_m=measured['hold_m'], hold_rad=measured['hold_rad'],
                   asymmetry_absolute=asymmetry, side_means=sides, cruise_phase_means=phase_means,
                   cruise_phase_asymmetry_deg=phase_asymmetry,
                   flagged_steps=sum(bool(x['warnings']) for x in steps))
    limits = dict(flat_drift_m=.005, flat_rotation_rad=.002, flat_floor_m=.002, toe_drift_m=.005, penetration_m=.002,
                  max_yaw_deg_s=200 if turning else 100.001, destination_error_m=.01, hold_m=.001, hold_rad=.002)
    summary['failures'] = [k for k,v in limits.items() if summary[k] >= v]
    # Hard anatomical sign gate on every actual touchdown, including closing
    # steps. Initial inherited supports are not newly planned footfalls.
    landed = [x for x in steps if x['land'] != first]
    cruise = [x for x in landed if x['kind'] == 'cruise']
    summary['landing_fpa_by_side_deg'] = {
        s: [min(values), max(values)] if values else None
        for s in 'LR' for values in [[x['progression_outward_deg'] for x in landed if x['side']==s]]}
    summary['cruise_width_by_side_m'] = {
        s: [min(values), max(values)] if values else None
        for s in 'LR' for values in [[x['step_width_m'] for x in cruise if x['side']==s]]}
    if any(x['progression_outward_deg'] < -.1 for x in landed):
        summary['failures'].append('anatomical_toe_in')
    summary['final_fpa_by_side_deg'] = {s: foot(rows[-1]['frame'], s)['progression_outward_deg'] for s in 'LR'}
    if any(v < -.1 for v in summary['final_fpa_by_side_deg'].values()):
        summary['failures'].append('final_anatomical_toe_in')
    if any(not 5 <= x['progression_outward_deg'] <= 10 for x in cruise):
        summary['failures'].append('cruise_fpa_outside_5_10')
    if not turning and len(nav.get('path_points', [])) == 2 and any(not .08 <= x['step_width_m'] <= .12 for x in cruise):
        summary['failures'].append('cruise_heel_width_outside_8_12_cm')
    if summary['max_knee_delta_deg'] >= 15:
        summary['failures'].append('max_knee_delta_deg')
    summary['envelope_flags'] = (['phase_or_progression_steps'] if summary['flagged_steps'] else [])
    for k,limit in (('max_knee_delta_deg',15),('mesh_penetration_m',.002),('mesh_flat_gap_m',.01)):
        if summary[k] >= limit:
            summary['envelope_flags'].append(k)
    return summary, steps


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', action='store_true'); p.add_argument('--label', default='v11')
    p.add_argument('--body', choices=BODIES); p.add_argument('--case', choices=CASES)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--remeasure', action='store_true', help='Refresh telemetry on cached pinned-baseline animations, without rebaking')
    p.add_argument('--refresh-summary', action='store_true', help='Recalculate anatomical FPA and report summaries from saved rows, offline')
    args = p.parse_args()
    os.environ.setdefault('CHAR3D_PORT', '9977')
    os.environ.setdefault('CHAR3D_WORKSPACE', str(ROOT/'output/walk_round9'))
    if os.environ['CHAR3D_PORT'] != '9977': raise RuntimeError('Benchmark owns port 9977 only')
    if args.refresh_summary:
        path = Path(os.environ['CHAR3D_WORKSPACE'])/f'walk_benchmark_{args.label}.json'
        report = json.loads(path.read_text())
        for key, case in report['cases'].items():
            for row in case['rows']:
                for side, foot in row['feet'].items():
                    axis = [b-a for a,b in zip(foot['heel_m'],foot['toe_m'])]
                    yaw = math.degrees(math.atan2(axis[0],-axis[1]))
                    foot.setdefault('legacy_progression_deg', foot['progression_outward_deg'])
                    foot['progression_outward_deg'] = ((yaw-row['yaw_deg']+180)%360-180)*(1 if side=='L' else -1)
            case['summary'],case['steps'] = summarize(case['nav'],case,'/pivot_' in key,case['parameters'].get('speed',1.))
        report['progression_convention'] = 'Actual heel-to-toe axis vs planned heading; positive outward on anatomical L(+X at -Y facing)/R. legacy_progression_deg retains the old reversed sign for reference.'
        report['analysis_fingerprint'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report['hard_failures'] = {k:c['summary']['failures'] for k,c in report['cases'].items() if c['summary']['failures']}
        path.write_text(json.dumps(report,indent=2)+'\n')
        if not args.baseline: assert not report['hard_failures'], report['hard_failures']
        print('WALK BENCHMARK OFFLINE SUMMARY OK',args.label,len(report['cases']),'cases')
        return
    engine = BlenderClient(); call = engine.call
    work = Path(engine.workspace); work.mkdir(parents=True, exist_ok=True)
    path = work/f'walk_benchmark_{args.label}.json'
    source = subprocess.check_output(['git','show','42487f5:engine/commands/walk.py'],cwd=ROOT,text=True) if args.baseline else (ROOT/'engine/commands/walk.py').read_text()
    sample_source = (ROOT/'tests/walk_benchmark_sample.py').read_text()
    fingerprint = hashlib.sha256((source+sample_source+Path(__file__).read_text()).encode()).hexdigest()
    if args.remeasure and not args.baseline:
        raise RuntimeError('--remeasure is limited to the pinned 42487f5 baseline')
    report = json.loads(path.read_text()) if (args.resume or args.remeasure) and path.exists() else {}
    if not args.remeasure and report.get('fingerprint', fingerprint) != fingerprint: raise RuntimeError('Stale result: source changed; rerun without --resume')
    report.update(schema=1, label=args.label, baseline_commit='42487f5' if args.baseline else None,
                  fingerprint=fingerprint, references=REFERENCES, envelope=ENVELOPE,
                  angle_convention='degrees; heel-up foot roll positive, shin-relative plantarflexion positive, foot-relative MTP extension positive; rest=0 for joint angles',
                  sampling='24 fps; phases normalized to same-foot heel strikes; toe-off uses actual support event; initial/final partial cycles retained as transitions',
                  cases=report.get('cases', {}))
    cached_cases = dict(report['cases'])
    try:
        print('SCENE', call('scene_info'), flush=True)
        report['angle_calibration'] = call('run_python',code=sample_source+'\nresult=calibrate()')['result']
        call('run_python', code='from engine.commands import walk\nexec(compile('+repr(source)+",'walk_benchmark_source.py','exec'),vars(walk))\n"+'''
original_headings = walk.support_headings
def capture_headings(*args, **kwargs):
    samples = original_headings(*args, **kwargs)
    walk._benchmark_headings = [v[1] for v in samples]
    return samples
walk.support_headings = capture_headings
result=True
''')
        for body, params in BODIES.items():
            if args.body and args.body != body: continue
            fixture = work/'projects'/f'{body}_rest.blend'
            if not fixture.exists():
                call('new_scene', fps=24)
                call('create_realistic_human', name='Gait', **params)
                call('save_project', path=str(fixture))
            fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
            for case, settings in CASES.items():
                if args.case and args.case != case: continue
                key = body+'/'+case
                if args.resume and key in report['cases']:
                    assert report['cases'][key]['fixture_sha256'] == fixture_hash
                    continue
                call('open_project', path=str(fixture))
                call('scene_info')
                turning = 'target' in settings
                project = f'{args.label}_{body}_{case}.blend'
                if args.remeasure:
                    cached = next(v for k,v in cached_cases.items() if k.startswith(body+'/') and v['parameters'] == settings)
                    assert cached['fixture_sha256'] == fixture_hash
                    nav = cached['nav']
                    project = cached['project']
                    # Reconstruct just the original plan to distinguish route
                    # root yaw from the pelvis' +/-5 degree gait accent. Abort
                    # before keying: cached animation remains the measurement.
                    call('run_python', code=f'''
from engine.commands import walk
original_bake = walk._bake_motion
class PlanCaptured(Exception): pass
def capture_plan(rig, start, samples, active, feet, clip, speed, ground=None, phases=None, runs=None, _world_route=False, gait=None):
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    walk.support_headings(samples, phases, fps, math.radians(195) if (gait or {{}}).get('weight') else walk.TURN_RATE)
    raise PlanCaptured()
import math
walk._bake_motion = capture_plan
try:
    walk.{'turn_to' if turning else 'walk_path'}(armature='Gait_rig',start_frame=1,avoid=False,**{settings!r})
except PlanCaptured:
    pass
finally:
    walk._bake_motion = original_bake
result=True
''')
                    call('open_project', path=str(work/'projects'/project))
                else:
                    nav = call('turn_to' if turning else 'walk_path', armature='Gait_rig', start_frame=1, avoid=False, **settings)
                measured = call('run_python',code=sample_source+f"\nresult=sample('Gait_rig', {nav!r})")['result']
                summary, steps = summarize(nav, measured, turning,settings.get('speed',1.))
                if not args.remeasure:
                    call('save_project',path=project)
                report['cases'][key] = dict(parameters=settings, phenotype=params, fixture_sha256=fixture_hash,
                    nav=nav, summary=summary, steps=steps, **measured, project=project)
                path.write_text(json.dumps(report, indent=2)+'\n')
                print(key, json.dumps({k:v for k,v in summary.items() if k not in
                      ('cruise_phase_means','cruise_phase_asymmetry_deg','side_means')}), flush=True)
        failures = {k:v['summary']['failures'] for k,v in report['cases'].items() if v['summary']['failures']}
        report['hard_failures'] = failures
        path.write_text(json.dumps(report, indent=2)+'\n')
        if not args.baseline: assert not failures, failures
        print('WALK BENCHMARK OK', args.label, len(report['cases']), 'cases', flush=True)
    finally:
        engine.stop()


if __name__ == '__main__': main()
