"""R14b acceptance: absolute pelvis smoothness and retained v13/v16 diagnostics."""
import json, statistics, sys
from pathlib import Path
from walk_round14_report import aggregate
from walk_round14_metrics import compare_pelvis
from walk_benchmark import ENVELOPE

def main():
 w=Path(sys.argv[1]);timing=json.loads((w/'devodo_v13_timing_matrix.json').read_text())['cases'];records={}
 lines=['# Ronde 14b: v13 → v16 → v17','', 'All lengths in mm. Pelvis gates use absolute first/second Z differences at 24 fps, each ≤110% of the same v13 case (+1 µm float tolerance). Offsets remain diagnostics.','', '| Case | Gap v13 / v16 / v17 | Penetration v17 | Drift v17 | Swing v17 | Bake ratio | Pelvis Δ / Δ² v13 → v16 → v17 | Mean lowering | Failures |','|---|---:|---:|---:|---:|---:|---|---:|---|']
 def mm(v):return '—' if v is None else f'{v*1000:.3f}'
 for mode in ('varied','symmetric'):
  suffix='' if mode=='varied' else '_symmetric'
  reports={v:json.loads((w/f'walk_benchmark_{v}{suffix}.json').read_text()) for v in ('v13','v16','v17')}
  assert all(len(r['cases'])==36 for r in reports.values())
  for key,c in reports['v17']['cases'].items():
   old=reports['v13']['cases'][key];data={v:aggregate(r['cases'][key]) for v,r in reports.items()};b=data['v17']
   pelvis=compare_pelvis(old['rows'],c['rows']);b['pelvis']=pelvis
   data['v16']['pelvis']=compare_pelvis(old['rows'],reports['v16']['cases'][key]['rows'])
   b['v13_bake_seconds']=timing[mode+'/'+key]['seconds'];b['bake_ratio']=b['bake_seconds']/b['v13_bake_seconds']
   fail=list(b['legacy_failures']);regressions=[]
   for s in 'LR':
    for phase,(lo,hi) in ENVELOPE.items():
     a,n=data['v13']['phase_means'][s][phase]['knee_deg'],b['phase_means'][s][phase]['knee_deg']
     if a is not None and n is not None and lo<=a<=hi and not lo<=n<=hi:regressions.append(s+'_'+phase+'_knee')
   fail+=regressions;fail+=['pelvis_'+f for f in pelvis['failures']]
   for field,limit in [('gap_max_m',.003),('penetration_m',.002),('drift_m',.006),('bake_ratio',1.3)]:
    if b[field] is not None and b[field]>limit:fail.append(field)
   if b['mid_swing_m'] is not None and b['mid_swing_m']<.008:fail.append('mid_swing_m')
   b.update(failures=fail,envelope_regressions=regressions);records[mode+'/'+key]=data
   lines.append(f"| {mode}/{key} | {' / '.join(mm(data[v]['gap_max_m']) for v in data)} | {mm(b['penetration_m'])} | {mm(b['drift_m'])} | {mm(b['mid_swing_m'])} | {b['bake_ratio']:.3f} | {mm(pelvis['v13']['step_max_m'])}/{mm(pelvis['v13']['second_difference_max_m'])} → {mm(data['v16']['pelvis']['candidate']['step_max_m'])}/{mm(data['v16']['pelvis']['candidate']['second_difference_max_m'])} → {mm(pelvis['candidate']['step_max_m'])}/{mm(pelvis['candidate']['second_difference_max_m'])} | {mm(-pelvis['mean_delta_m'])} | {', '.join(fail) or 'PASS'} |")
 bodies={}
 for body in ('male','female_short','male_tall_heavy'):
  vals=[r for k,r in records.items() if '/'+body+'/' in k]
  bodies[body]={}
  for label in ('v13','v16','v17'):
   values=[r[label] for r in vals]
   bodies[body][label]={f:max(v[f] for v in values if v[f] is not None) for f in ('gap_max_m','gap_p95_m','strike_max_m','penetration_m','drift_m')}
   bodies[body][label]['gap_mean_m']=statistics.mean(v['gap_mean_m'] for v in values)
  bodies[body]['mean_lowering_m']=-statistics.mean(v['v17']['pelvis']['mean_delta_m'] for v in vals)
 summary=dict(pelvis_passed={v:sum(not r[v]['pelvis']['failures'] for r in records.values()) for v in ('v16','v17')},cases=len(records),passed=sum(not r['v17']['failures'] for r in records.values()),bodies=bodies,failed_cases={k:r['v17']['failures'] for k,r in records.items() if r['v17']['failures']})
 (w/'round14b_comparison.json').write_text(json.dumps(records,indent=2));(w/'round14b_summary.json').write_text(json.dumps(summary,indent=2));(w/'round14b_comparison.md').write_text('\n'.join(lines)+'\n');print(json.dumps(summary,indent=2))
 assert summary['passed']==72,'Failures retained in round14b_summary.json'
if __name__=='__main__':main()
