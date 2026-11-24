"""Offline v10/v11 measured landmark top views and per-case comparison tables.

Uses saved benchmark telemetry, never rebakes or starts Blender. ImageMagick
rasterizes an SVG containing the actual XY heel/toe landmarks at touchdown.
"""
import json
import math
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def footprint_sheet(reports, work):
    columns = ('straight_1.0', 'turn_90_left', 'turn_90_right')
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="1680" height="1400" viewBox="0 0 1680 1400">',
           '<rect width="1680" height="1400" fill="#f4f5f7"/>']
    def text(x, y, value, size=16, color='#263747'):
        out.append(f'<text x="{x}" y="{y}" font-family="DejaVu Sans" font-size="{size}" fill="{color}">{value}</text>')
    def line(a, b, color, width=2, dash=False):
        out.append(f'<line x1="{a[0]:.3f}" y1="{a[1]:.3f}" x2="{b[0]:.3f}" y2="{b[1]:.3f}" stroke="{color}" stroke-width="{width}"'+(' stroke-dasharray="4 4"' if dash else '')+'/>')
    def arrow(a, b, color, width=3):
        line(a,b,color,width)
        dx,dy=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dy)
        ux,uy=dx/length,dy/length
        line(b,(b[0]-6*ux+3*uy,b[1]-6*uy-3*ux),color,width)
        line(b,(b[0]-6*ux-3*uy,b[1]-6*uy+3*ux),color,width)
        out.append(f'<circle cx="{a[0]}" cy="{a[1]}" r="3" fill="{color}"/>')
    for j, name in enumerate(columns):
        all_points = [r['pelvis_m'] for label in ('v10','v11') for r in reports[label]['cases']['male/'+name]['rows']]
        xmin=min(p[0] for p in all_points)-.45; xmax=max(p[0] for p in all_points)+.45
        ymin=min(p[1] for p in all_points)-.45; ymax=max(p[1] for p in all_points)+.45
        scale=min(475/(xmax-xmin),390/(ymax-ymin))
        for i,label in enumerate(('v10','v11')):
            x,y=j*560,i*700
            out.append(f'<rect x="{x+8}" y="{y+8}" width="544" height="684" rx="10" fill="white" stroke="#ccd5df"/>')
            text(x+25,y+38,f'{label} | male / {name}',20)
            text(x+25,y+62,'Top XY: measured touchdown heel → toe',14)
            case=reports[label]['cases']['male/'+name]; first=case['rows'][0]['frame']
            def project(p):
                return (x+280+(p[0]-(xmin+xmax)/2)*scale,y+265-(p[1]-(ymin+ymax)/2)*scale)
            route=[project(r['pelvis_m']) for r in case['rows']]
            for a,b in zip(route,route[1:]): line(a,b,'#a8b3c0',1)
            lands=[]
            for ev in case['nav']['footfalls']:
                row=case['rows'][ev['frame']-first]; side=ev['side']; f=row['feet'][side]
                a,b=project(f['heel_m']),project(f['toe_m']); color='#0086ad' if side=='L' else '#df6a24'
                arrow(a,b,color,2)
                text(a[0]+5,a[1]+3,str(ev['frame']),10,color)
                lands.append((row,side,f))
            # Matched row of each foot's first cruise landing, enlarged and
            # aligned to that landing's route heading. This exposes the sign
            # independently of later root rotation around a planted support.
            text(x+25,y+505,'Route-aligned detail (same measured landmarks)',13)
            # In this route-aligned top view +X is image-right, so anatomical
            # L belongs on the right and R on the left.
            for k,side in enumerate('RL'):
                selected=next((s for s in case['steps'] if s['side']==side and s['kind']=='cruise'),None)
                if selected is None:
                    corner=case['nav']['path_points'][1]
                    candidates=[v for v in lands if v[1]==side]
                    row,_,f=min(candidates,key=lambda v:math.dist(v[0]['pelvis_m'][:2],corner))
                else:
                    row=case['rows'][selected['land']-first]; f=row['feet'][side]
                yaw=math.radians(row['yaw_deg']); dx=f['toe_m'][0]-f['heel_m'][0]; dy=f['toe_m'][1]-f['heel_m'][1]
                right=dx*math.cos(yaw)+dy*math.sin(yaw); ahead=dx*math.sin(yaw)-dy*math.cos(yaw)
                heel=(x+140+260*k,y+655); toe=(heel[0]+right*450,heel[1]-ahead*450)
                color='#0086ad' if side=='L' else '#df6a24'
                line(heel,(heel[0],heel[1]-115),'#8795a6',1,True); arrow(heel,toe,color,3)
                text(x+40+260*k,y+535,f'{side} F{row["frame"]}: {f["progression_outward_deg"]:+.2f}°',15,color)
            text(x+25,y+682,'L cyan (+X at -Y facing) · R orange · grey route',12)
    out.append('</svg>')
    svg=work/'walk_fpa_v10_v11.svg'; svg.write_text('\n'.join(out))
    subprocess.run(['convert','-background','white',str(svg),str(work/'walk_fpa_v10_v11.png')],check=True)


def comparison(reports, work):
    lines=['# Per-case anatomical FPA and heel track', '',
           'FPA = heel→toe floor axis versus planned route heading at touchdown; positive = anatomical outward. '
           'Initial inherited supports excluded. Ranges include braking/closing landings. Widths use cruise cycles; '
           'where no cruise exists, * marks all complete cycles (bends open the track). Units: degrees and cm.', '',
           '| Body / case | FPA L v10 → v11 | FPA R v10 → v11 | Heel width L v10 → v11 | Heel width R v10 → v11 |',
           '|---|---:|---:|---:|---:|']
    def limits(values, factor=1):
        return '—' if not values else f'{min(values)*factor:.2f}…{max(values)*factor:.2f}'
    for key,c in reports['v11']['cases'].items():
        old=reports['v10']['cases'][key]
        assert old['fixture_sha256']==c['fixture_sha256'],key
        assert old['parameters']==c['parameters'],key
        fields=[]
        for channel in ('progression_outward_deg','step_width_m'):
            for side in 'LR':
                values=[]
                for case in (old,c):
                    if channel=='progression_outward_deg':
                        subset=[s for s in case['steps'] if s['side']==side and s['land']!=case['rows'][0]['frame']]; suffix=''
                    else:
                        subset=[s for s in case['steps'] if s['side']==side and s['kind']=='cruise']; suffix=''
                        if not subset:
                            subset=[s for s in case['steps'] if s['side']==side and s['complete_cycle']]; suffix='*'
                    values.append(limits([s[channel] for s in subset],100 if channel=='step_width_m' else 1)+suffix)
                fields.append(' → '.join(values))
        lines.append('| '+key+' | '+' | '.join(fields)+' |')
    lines += ['', '# Contracts per case (v11)', '',
              '| Body / case | Drift mm | Sole penetration mm | Knee °/f | Heading °/s | Destination mm | Hold mm / rad | Flat rotation rad | Result |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for key,c in reports['v11']['cases'].items():
        s=c['summary']
        lines.append(f'| {key} | {1000*s["flat_drift_m"]:.3f} | {1000*s["penetration_m"]:.3f} | {s["max_knee_delta_deg"]:.3f} | {s["max_yaw_deg_s"]:.3f} | {1000*s["destination_error_m"]:.3f} | {1000*s["hold_m"]:.4f} / {s["hold_rad"]:.5f} | {s["flat_rotation_rad"]:.6f} | '+(', '.join(s['failures']) or 'PASS')+' |')
    lines += ['', 'Native soft-skin outsole/phase envelope diagnostics remain in the JSON, separately from skeletal contact contracts.',
              'v10 cache SHA-256/fixture hashes are retained; v10 source bake fingerprint is not replaced by the new analysis fingerprint.']
    (work/'walk_fpa_comparison.md').write_text('\n'.join(lines)+'\n')
    (work/'comparison_provenance.json').write_text(json.dumps({label:dict(
        bake_fingerprint=r['fingerprint'], analysis_fingerprint=r.get('analysis_fingerprint'),
        cases=len(r['cases']), fixture_hashes={k:c['fixture_sha256'] for k,c in r['cases'].items()})
        for label,r in reports.items()},indent=2)+'\n')


def main():
    work=Path(os.environ.get('CHAR3D_WORKSPACE',ROOT/'output/walk_round9'))
    reports={label:json.loads((work/f'walk_benchmark_{label}.json').read_text()) for label in ('v10','v11')}
    comparison(reports,work)
    footprint_sheet(reports,work)
    print('ROUND9 COMPARISON OK: matched fixture hashes, table and measured XY top sheet')


if __name__=='__main__': main()
