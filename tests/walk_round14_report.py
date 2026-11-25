"""Offline complete R14 acceptance; keep all failed gates and native telemetry."""
import json,sys,statistics,math
from pathlib import Path
from walk_benchmark import ENVELOPE

def aggregate(c):
 rows=c['rows'];gaps=[];strikes=[]
 for row in rows:
  for s in 'LR':
   p=row['feet'][s]
   gaps.extend(max(0.,p['contact_regions_m'][a]) for a in p.get('active_contact_regions',[]) if a in p.get('contact_regions_m',{}))
 for e in c['nav']['footfalls']:
  z=rows[e['frame']-c['nav']['frames'][0]]['feet'][e['side']].get('contact_regions_m',{}).get('heel')
  if z is not None:strikes.append(z)
 metrics=c['summary'].get('round14',{})
 middle=[v['mid_swing_min_mesh_clearance_m'] for v in c['summary']['round11']['sides'].values() if v['mid_swing_min_mesh_clearance_m'] is not None]
 return dict(gap_max_m=max(gaps,default=0),gap_mean_m=statistics.mean(gaps) if gaps else None,gap_p95_m=sorted(gaps)[min(len(gaps)-1,int(.95*len(gaps)))] if gaps else None,
  strike_max_m=max(strikes,default=None),strike_mean_m=statistics.mean(strikes) if strikes else None,penetration_m=c['summary']['mesh_penetration_m'],
  drift_m=max((v['mesh_contact_drift_xy_m'] for v in metrics.get('sides',{}).values()),default=None),
  mid_swing_m=min(middle,default=None),knee_delta_deg=c['summary']['max_knee_delta_deg'],bake_seconds=c['nav'].get('bake_wall_seconds'),
  legacy_failures=c['summary']['failures'],heel_strikes=strikes,
  phase_means=c['summary']['cruise_phase_means'],envelope_flags=c['summary']['envelope_flags'],flagged_steps=c['summary']['flagged_steps'],
  contact_point_samples=sum(len(row['feet'][s].get('contact_mesh_points_m',{})) for row in rows for s in 'LR'))

def main():
 w=Path(sys.argv[1]);timing=json.loads((w/'devodo_v13_timing_matrix.json').read_text())['cases'];records={};lines=['# Ronde 14: seluruh 72 kasus','',
 'mm kecuali waktu (detik), rasio, dan sudut. Drift = episode vertex native, arch dikecualikan dari gap; seluruh mesh tetap diuji penetrasi. Fixture v16 dibangun ulang.','',
 '| Kasus | Gap maks v13 → v16 | Mean / p95 v16 | Strike maks v13 → v16 | Penetrasi v16 | Drift v16 | Swing tengah | Bake v13 → v16 | Δ pelvis/frame vs v13 | Gagal |',
 '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
 def mm(x):return '—' if x is None else f'{1000*x:.2f}'
 for mode in ('varied','symmetric'):
  suffix='' if mode=='varied' else '_symmetric';base=json.loads((w/f'walk_benchmark_v13{suffix}.json').read_text());new=json.loads((w/f'walk_benchmark_v16{suffix}.json').read_text())
  for key,c in new['cases'].items():
   old=base['cases'][key];a,b=aggregate(old),aggregate(c)
   b['v13_bake_seconds']=timing[mode+'/'+key]['seconds'];b['bake_ratio']=b['bake_seconds']/b['v13_bake_seconds']
   prev={r['frame']:r for r in old['rows']};d=[r['pelvis_m'][2]-prev[r['frame']]['pelvis_m'][2] for r in c['rows'] if r['frame'] in prev]
   b['pelvis_step_vs_v13_m']=max((abs(y-x) for x,y in zip(d,d[1:])),default=0);b['pelvis_delta_mean_m']=statistics.mean(d);b['pelvis_max_lowering_m']=max(max(0.,-x) for x in d)
   b['failures']=list(b['legacy_failures'])
   b['envelope_regressions']=[]
   for s in 'LR':
    for phase,(lo,hi) in ENVELOPE.items():
     ov=a['phase_means'][s][phase]['knee_deg'];nv=b['phase_means'][s][phase]['knee_deg']
     if ov is not None and nv is not None and lo<=ov<=hi and not lo<=nv<=hi:
      b['envelope_regressions'].append(s+'_'+phase+'_knee')
   b['failures'].extend(b['envelope_regressions'])
   for field,limit in [('gap_max_m',.003),('penetration_m',.002),('drift_m',.006),('bake_ratio',1.3),('pelvis_step_vs_v13_m',.003)]:
    if b[field] is not None and b[field]>limit:b['failures'].append(field)
   if b['mid_swing_m'] is not None and b['mid_swing_m']<.008:b['failures'].append('mid_swing_m')
   records[mode+'/'+key]=dict(v13=a,v16=b,fixture_sha256=dict(v13=old['fixture_sha256'],v16=c['fixture_sha256']))
   lines.append(f"| {mode}/{key} | {mm(a['gap_max_m'])} → {mm(b['gap_max_m'])} | {mm(b['gap_mean_m'])} / {mm(b['gap_p95_m'])} | {mm(a['strike_max_m'])} → {mm(b['strike_max_m'])} | {mm(b['penetration_m'])} | {mm(b['drift_m'])} | {mm(b['mid_swing_m'])} | {b['v13_bake_seconds']:.2f} → {b['bake_seconds']:.2f} ({b['bake_ratio']:.2f}×) | {mm(b['pelvis_step_vs_v13_m'])} | {', '.join(b['failures']) or 'LULUS'} |")
 bodies={}
 for body in ('male','female_short','male_tall_heavy'):
  vals=[v['v16'] for k,v in records.items() if '/'+body+'/' in k]
  bodies[body]=dict(cases=len(vals),passed=sum(not v['failures'] for v in vals),**{field:max(v[field] for v in vals if v[field] is not None) for field in ('gap_max_m','gap_p95_m','strike_max_m','penetration_m','drift_m','bake_ratio','pelvis_step_vs_v13_m')},gap_mean_m=statistics.mean(v['gap_mean_m'] for v in vals),mid_swing_min_m=min(v['mid_swing_m'] for v in vals if v['mid_swing_m'] is not None))
 summary=dict(cases=len(records),passed=sum(not v['v16']['failures'] for v in records.values()),bodies=bodies,failed_cases={k:v['v16']['failures'] for k,v in records.items() if v['v16']['failures']})
 (w/'round14_comparison.json').write_text(json.dumps(records,indent=2));(w/'round14_summary.json').write_text(json.dumps(summary,indent=2));(w/'round14_comparison.md').write_text('\n'.join(lines)+'\n');print(json.dumps(summary,indent=2))
 assert summary['cases']==72 and summary['passed']==72,'R14 acceptance failures retained in round14_summary.json'
if __name__=='__main__':main()
