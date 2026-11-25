"""R11 offline comparisons/plots and final cached-pose contact/asset review.

No baseline rebake. SVG plots use the installed librsvg/Cairo libraries; no packages.
"""
import argparse
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from mcp_server.blender_client import BlenderClient
from walk_round8_review import montage


def svg_plot(path,width,height,parts):
    source=path.with_suffix('.svg')
    source.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><g font-family="DejaVu Sans" font-size="14">'+''.join(parts)+'</g></svg>')
    # Use the already installed librsvg/Cairo renderer: ImageMagick's SVG
    # delegate on this machine loses stroke attributes on line primitives.
    # https://gnome.pages.gitlab.gnome.org/librsvg/Rsvg-2.0/method.Handle.render_document.html
    import ctypes as ct
    cairo=ct.CDLL('libcairo.so.2');rsvg=ct.CDLL('librsvg-2.so.2');gobj=ct.CDLL('libgobject-2.0.so.0')
    class Viewport(ct.Structure):
        _fields_=[(k,ct.c_double) for k in ('x','y','width','height')]
    cairo.cairo_image_surface_create.argtypes=[ct.c_int,ct.c_int,ct.c_int];cairo.cairo_image_surface_create.restype=ct.c_void_p
    cairo.cairo_create.argtypes=[ct.c_void_p];cairo.cairo_create.restype=ct.c_void_p
    cairo.cairo_destroy.argtypes=[ct.c_void_p];cairo.cairo_surface_destroy.argtypes=[ct.c_void_p]
    cairo.cairo_surface_write_to_png.argtypes=[ct.c_void_p,ct.c_char_p];cairo.cairo_surface_write_to_png.restype=ct.c_int
    rsvg.rsvg_handle_new_from_file.argtypes=[ct.c_char_p,ct.c_void_p];rsvg.rsvg_handle_new_from_file.restype=ct.c_void_p
    rsvg.rsvg_handle_render_document.argtypes=[ct.c_void_p,ct.c_void_p,ct.POINTER(Viewport),ct.c_void_p];rsvg.rsvg_handle_render_document.restype=ct.c_int
    gobj.g_object_unref.argtypes=[ct.c_void_p]
    surface=cairo.cairo_image_surface_create(0,width,height);context=cairo.cairo_create(surface)
    handle=rsvg.rsvg_handle_new_from_file(os.fsencode(source),None)
    try:
        assert handle and rsvg.rsvg_handle_render_document(handle,context,ct.byref(Viewport(0,0,width,height)),None)
        assert cairo.cairo_surface_write_to_png(surface,os.fsencode(path))==0
    finally:
        if handle:gobj.g_object_unref(handle)
        cairo.cairo_destroy(context);cairo.cairo_surface_destroy(surface)


def txt(x,y,text,size=14,color='#222'):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(text)}</text>'


def line(points,color,width=2,opacity=1):
    # The installed ImageMagick SVG delegate fills open polylines even when
    # fill=none is explicit. Independent line primitives have no fill area.
    return ''.join(f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{color}" stroke-width="{width}" opacity="{opacity}"/>'
                   for a,b in zip(points,points[1:]))


def plots(work,reports):
    colors={'v12':'#777777','v13':'#136cb5'}
    pieces=[txt(24,28,'Minimum evaluated shoe mesh clearance — all swings',20),
            txt(24,52,'One line per swing; gates exclude two endpoint frames. Green = 8 mm; display clips values above 125 mm.')]
    for panel,key in enumerate(('male/straight_1.0','male/turn_90_left')):
        x0=75+panel*610;y0=435;scale=2.4
        pieces += [txt(x0,y0-340,key,18),line([(x0,y0-300),(x0,y0),(x0+500,y0)],'#333',1)]
        for v in (0,8,20,40,60,80,100,120):
            y=y0-v*scale
            pieces += [line([(x0,y),(x0+500,y)],'#288147' if v==8 else '#dedede',1),txt(x0-45,y+4,str(v))]
        for u in (0,.2,.4,.6,.8,1): pieces.append(txt(x0+u*500-8,y0+22,str(round(u,1))))
        for label in ('v12','v13'):
            c=reports[label]['cases'][key]
            for side in 'LR':
                for ev in c['summary']['round11']['sides'][side]['swing_traces']:
                    points=[(x0+p['phase']*500,y0-min(125,1000*p['mesh_clearance_m'])*scale) for p in ev['trace']]
                    pieces.append(line(points,colors[label],1.5,.65))
            pieces.append(txt(x0+(0 if label=='v12' else 270),y0+53,label+': L & R, all swings',14,colors[label]))
        pieces += [txt(x0+190,y0+78,'Swing fraction'),txt(x0-48,y0-310,'mm')]
    svg_plot(work/'walk_swing_clearance_v12_v13.png',1280,560,pieces)
    pieces=[txt(24,28,'Whole-body kinematic COM estimate and actual foot placements',20),
            txt(24,52,'de Leva male mass fractions; approximate joint endpoints. COM projection is not COP or a force measurement.')]
    for col,case in enumerate(('turn_90_left','turn_90_right','pivot_180_left')):
        allpts=[r['com_m'][:2] for label in reports for r in reports[label]['cases']['male/'+case]['rows']]
        allpts += [r['feet'][s]['heel_m'][:2] for label in reports for r in reports[label]['cases']['male/'+case]['rows'] for s in 'LR']
        xmin,xmax=min(p[0] for p in allpts)-.15,max(p[0] for p in allpts)+.15
        ymin,ymax=min(p[1] for p in allpts)-.15,max(p[1] for p in allpts)+.15
        factor=min(340/(xmax-xmin),340/(ymax-ymin))
        for row,label in enumerate(('v12','v13')):
            x=30+col*420;y=90+row*430
            def project(p):return (x+20+(p[0]-xmin)*factor,y+30+(ymax-p[1])*factor)
            pieces += [txt(x+10,y,label+' | male/'+case,16),txt(x+10,y+405,'world XY; COM blue / pelvis grey; L green / R orange',11)]
            unit=.1 if 'pivot' in case else 1.
            pieces += [line([(x+20,y+375),(x+20+unit*factor,y+375)],'#444',2),txt(x+20,y+393,f'{unit:g} m',11)]
            c=reports[label]['cases']['male/'+case]
            pieces.append(line([project(r['com_m']) for r in c['rows']],'#136cb5',2))
            pieces.append(line([project(r['pelvis_m']) for r in c['rows']],'#a3a3a3',1))
            for s,color in (('L','#16804a'),('R','#c36322')):
                for ev in c['nav']['footfalls']:
                    if ev['side']!=s:continue
                    f=c['rows'][ev['frame']-c['rows'][0]['frame']]['feet'][s]
                    pieces.append(line([project(f['heel_m']),project(f['toe_m'])],color,4))
            for r in c['rows'][::4]:
                px,py=project(r['com_m']); pieces.append(f'<circle cx="{px}" cy="{py}" r="2" fill="#136cb5"/>')
    svg_plot(work/'walk_turn_com_v12_v13.png',1280,960,pieces)


def com_statistics(case):
    rows=case['rows'];nav=case['nav'];routes=nav.get('weight_transfer',{}).get('route_xy_m',[])
    outside=[];relative=[];pivot=[]
    for i,r in enumerate(rows):
        yaw=math.radians(r['yaw_deg']);left=(math.cos(yaw),math.sin(yaw))
        if abs(r['yaw_rate_deg_s'])<10: continue
        side='R' if r['yaw_rate_deg_s']>0 else 'L'
        sign=1 if side=='L' else -1
        if side in r.get('support_feet',[]):
            delta=[r['com_m'][k]-r['feet'][side]['ankle_m'][k] for k in (0,1)]
            relative.append(abs(sum(delta[k]*left[k] for k in (0,1))))
            if routes: outside.append(sign*sum((r['com_m'][k]-routes[i][k])*left[k] for k in (0,1)))
        active=r.get('support_feet',[])
        if len(active)==1:
            s=active[0];sgn=1 if s=='L' else -1
            origin=routes[i] if routes else r['pelvis_m'][:2]
            pivot.append(sgn*sum((r['com_m'][k]-origin[k])*left[k] for k in (0,1)))
    def stats(v):return dict(samples=len(v),mean=sum(v)/len(v),min=min(v),max=max(v)) if v else None
    return dict(outside_support_com_from_route_lateral_m=stats(outside),
                outside_support_com_distance_to_ankle_lateral_m=stats(relative),
                single_support_com_toward_support_from_route_m=stats(pivot))


def comparison(work,reports):
    lines=['# Ronde 11 — lampiran seluruh kasus','',
           'Panjang dalam mm. Gap: maksimum minimum patch aktif, bukan maksimum semua vertex sol. '
           'Arch terpisah. COM adalah estimasi kinematik; tidak menyatakan GRF/COP. '
           'Metrik turunan finite difference di 24 fps, termasuk transisi/hold.','',
           '| Mode/kasus | Penetrasi v12 → v13 | Gap aktif heel/ball/toe v13 L/R maks | Clearance swing/tengah v13 | Lutut tumpu berputar maks v12 → v13 ° | Limiter v13 frame (episode) | Kontrak | Target tersisa |',
           '|---|---:|---|---|---|---|---|---|']
    table={}
    for mode,label in [('varied','v13'),('symmetric','v13_symmetric')]:
        if label not in reports:continue
        for key,c in reports[label]['cases'].items():
            old=reports['v12']['cases'][key]
            assert old['fixture_sha256']==c['fixture_sha256'],key
            m=c['summary']['round11'];om=old['summary']['round11']
            def combined(field):return [v[field] for v in m['sides'].values() if v[field] is not None]
            gaps=[1000*max(v['active_contact_regions'][r]['max_gap_m'] for v in m['sides'].values()) for r in ('heel','ball','toe')]
            def knee(data):return max((v['turning_support_knee_deg']['max'] for v in data['sides'].values() if v['turning_support_knee_deg']),default=0)
            limits=[v['knee_limiter'] for v in m['sides'].values()]
            record=dict(old=old['summary'],new=c['summary'],com_statistics=dict(v12=com_statistics(old),v13=com_statistics(c)),active_gap_mm=gaps,
                        remaining_targets=m['target_failures'])
            table[mode+'/'+key]=record
            lines.append('| '+mode+'/'+key+' | '+f'{old["mesh_penetration_m"]*1000:.2f} → {c["mesh_penetration_m"]*1000:.2f}'+' | '+
                         '/'.join(f'{v:.2f}' for v in gaps)+' | '+
                         '/'.join(f'{min(combined(f),default=0)*1000:.2f}' for f in ('swing_min_mesh_clearance_m','mid_swing_min_mesh_clearance_m'))+' | '+
                         f'{knee(om):.2f} → {knee(m):.2f}'+' | '+
                         str(sum(v['active_frames'] for v in limits))+' ('+str(sum(v['activations'] for v in limits))+') | '+
                         ('PASS' if not c['summary']['failures'] else ', '.join(c['summary']['failures']))+' | '+', '.join(m['target_failures'])+' |')
    lines += ['', '## COM saat belok / pivot', '',
              'Jarak lateral absolut COM ke ankle kaki luar saat kaki luar menopang. Nilai lebih kecil berarti lebih dekat pada sumbu lateral kaki itu; bukan estimasi gaya.', '',
              '| Mode/kasus | Mean jarak lateral ke ankle luar v12 → v13 (mm) | Mean COM menuju kaki tunggal dari rute v12 → v13 (mm) |',
              '|---|---:|---:|']
    for key,record in table.items():
        if not any(tag in key for tag in ('turn_','pivot_')):continue
        data=record['com_statistics']
        cells=[]
        for field in ('outside_support_com_distance_to_ankle_lateral_m','single_support_com_toward_support_from_route_m'):
            cells.append(' → '.join(f"{data[label][field]['mean']*1000:.2f}" if data[label][field] else '—' for label in ('v12','v13')))
        lines.append('| '+key+' | '+' | '.join(cells)+' |')
    (work/'walk_round11_comparison.md').write_text('\n'.join(lines)+'\n')
    (work/'walk_round11_comparison.json').write_text(json.dumps(table,indent=2)+'\n')
    plots(work,{k:reports[k] for k in ('v12','v13')})


CAMERA='''
from mathutils import Vector
sc=bpy.context.scene
cam=bpy.data.objects.new('ContactCamera',bpy.data.cameras.new('ContactCamera'));sc.collection.objects.link(cam)
cam.data.type='ORTHO';cam.data.ortho_scale=SCALE
centre=Vector(CENTRE); axis=Vector(AXIS)
cam.location=centre+axis*3+Vector((0,0,.25))
cam.rotation_euler=(centre-cam.location).to_track_quat('-Z','Y').to_euler();sc.camera=cam
sc.render.resolution_x=512;sc.render.resolution_y=320;sc.render.resolution_percentage=100
curve=bpy.data.curves.new('FloorLine','CURVE');curve.dimensions='3D';curve.bevel_depth=.0006
sp=curve.splines.new('POLY');sp.points.add(1)
sp.points[0].co=(*list(centre-Vector(FORWARD)*2)[:2],0,1);sp.points[1].co=(*list(centre+Vector(FORWARD)*2)[:2],0,1)
sc.collection.objects.link(bpy.data.objects.new('FloorLine',curve))
result=True
'''


def render(work,reports):
    engine=BlenderClient();call=engine.call
    try:
        call('scene_info')
        environment=call('run_python',code="import sys\nsys.path.insert(0,'/home/reyhan/.codex/skills/blender-core/scripts')\nimport env_report\nresult=env_report.run()")['result']
        (work/'blender_environment.json').write_text(json.dumps(environment,indent=2)+'\n')
        paths=[];labels=[]
        for body in ('male','male_tall_heavy'):
            for phase in ('heel_strike','mid_stance','pre_swing'):
                for label in ('v12','v13'):
                    c=reports[label]['cases'][body+'/straight_1.0']
                    step=next(s for s in c['steps'] if s['side']=='L' and s['complete_cycle'] and s['land']>20)
                    f=step['land'] if phase=='heel_strike' else step['phases'][phase]['frame']
                    call('open_project',path=c['project']);call('scene_info')
                    foot=c['rows'][f-c['rows'][0]['frame']]['feet']['L']
                    forward=[b-a for a,b in zip(foot['heel_m'],foot['toe_m'])];forward[2]=0
                    length=math.hypot(*forward[:2]);forward=[v/length for v in forward]
                    centre=[(a+b)/2 for a,b in zip(foot['heel_m'],foot['toe_m'])];centre[2]=.06
                    axis=[-forward[1],forward[0],0]
                    call('run_python',code=CAMERA.replace('SCALE',repr(max(.50,1.8*length))).replace('CENTRE',repr(centre)).replace('FORWARD',repr(forward)).replace('AXIS',repr(axis)))
                    call('run_python',code=f'''
from engine.shoe_contact import calibrate
rig=bpy.data.objects['Gait_rig'];patches=calibrate(rig)
colors={{'heel':(.15,.35,.95,1),'arch':(.65,.25,.75,1),'ball':(.1,.7,.25,1),'toe':(1,.4,.06,1)}}
for name,sides in patches:
 ob=bpy.data.objects[name]
 region_vertices={{k:set(v) for k,v in sides['L']['regions'].items()}}
 slots={{}}
 for k,col in colors.items():
  mat=bpy.data.materials.new(k);mat.diffuse_color=col;ob.data.materials.append(mat);slots[k]=len(ob.data.materials)-1
 for face in ob.data.polygons:
  hits={{k:sum(i in ids for i in face.vertices) for k,ids in region_vertices.items()}}
  k=max(hits,key=hits.get)
  if hits[k]:face.material_index=slots[k]
result=True
''')
                    output=call('render_frames',frames=[f],camera='scene',objects=['Gait_rig'],size=512,engine='workbench',prefix=f'r11_contact_{body}_{label}_{phase}')
                    paths.append(output['frames'][0]['path'])
                    regions=foot['contact_regions_m']
                    active='+'.join({'heel':'H','ball':'B','toe':'T'}[k] for k in foot.get('active_contact_regions',[]))
                    labels.append(f'{body} {label} L {phase} F{f} | active {active}\nheel {regions["heel"]*1000:+.2f} / ball {regions["ball"]*1000:+.2f} / toe {regions["toe"]*1000:+.2f} mm\narch (purple) {regions["arch"]*1000:+.2f} mm; blue heel, green ball, orange toe')
        montage(paths,labels,work/'walk_contact_regions_v12_v13.png','2x6','512x320+4+12')
        qa={}
        for body in ('male','female_short','male_tall_heavy'):
            c=reports['v13']['cases'][body+'/straight_1.0']
            step=next(s for s in c['steps'] if s['complete_cycle'])
            f=step['phases']['peak_swing']['frame']
            call('open_project',path=c['project']);call('scene_info');qa[body]={}
            for mode in ('random','wire'):
                dest=work/'renders'/f'qa_{body}_{mode}.png'
                qa[body][mode]=call('run_python',code=f'''
import sys
sys.path.insert(0,'/home/reyhan/.codex/skills/blender-asset-qa/scripts')
import review_shots
bpy.context.scene.frame_set({f})
rig=bpy.data.objects['Gait_rig']
objects=[o.name for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
result=review_shots.run(objects=objects,out={str(dest)!r},views=['front','right','back','three_quarter'],mode={mode!r},res=256)
''')['result']
        (work/'qa_visual_sheets.json').write_text(json.dumps(qa,indent=2)+'\n')
        print('CONTACT REGIONS AND MULTI-ANGLE QA RENDERED',flush=True)
    finally:engine.stop()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',action='store_true');p.add_argument('--render',action='store_true');a=p.parse_args()
    assert os.environ.get('CHAR3D_PORT')=='9977'
    work=Path(os.environ['CHAR3D_WORKSPACE'])
    reports={label:json.loads((work/f'walk_benchmark_{label}.json').read_text()) for label in ('v12','v13','v13_symmetric')}
    if a.report:comparison(work,reports)
    if a.render:render(work,reports)


if __name__=='__main__':main()
