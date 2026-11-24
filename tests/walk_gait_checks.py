"""Measure the baked feet, toe articulation, support overlap and settle on MPFB.

CHAR3D_PORT=9977 CHAR3D_WORKSPACE=... CHAR3D_ALLOW_PYTHON=1 python tests/walk_gait_checks.py
Uses one char3d engine. Evidence is retained in the assigned workspace.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp_server.blender_client import BlenderClient


def check(call, rig, nav):
    return call('run_python', code=f'''
import math
from engine.commands import anim
from engine.commands.footlock import _legs, _sole_points
rig = bpy.data.objects[{rig!r}]
nav = {nav!r}
sc = bpy.context.scene
mw = rig.matrix_world
smap = anim.semantic_map(rig)
legs, _ = _legs(rig)
sole = {{s: _sole_points(rig, legs[s], 0) for s in 'LR'}}
shoes = [o for o in sc.objects if o.type == 'MESH' and o.get('c3d_garment_category') == 'shoes'
         and any(m.type == 'ARMATURE' and m.object == rig for m in o.modifiers)]
flat_frames = {{s: {{f for a,b in intervals for f in range(a,b+1)}}
               for s,intervals in nav['foot_lock']['contacts'].items()}}
mesh_penetration = mesh_flat_gap = 0.0
# Distal sole points follow the articulated toe, rather than a rigid ankle proxy.
toe_sole = {{}}
for s in 'LR':
    toe = smap.get('toe.'+s)
    if toe:
        inv = (mw @ rig.data.bones[toe].matrix_local).inverted()
        foot = mw @ rig.data.bones[smap['foot.'+s]].matrix_local
        toe_sole[s] = [inv @ (foot @ p) for p in sole[s][1:]]
flat_drift = flat_floor = penetration = toe_bend = knee_jump = 0.0
worst_knee = None
prev_knees = {{}}
roots, feet, gaps, knees = [], {{'L': [], 'R': []}}, {{'L': [], 'R': []}}, {{'L': [], 'R': []}}
toe_points = {{'L': [], 'R': []}}
for f in range(nav['frames'][0], nav['frames'][1]+1):
    sc.frame_set(f)
    hp = mw @ rig.pose.bones[smap['hips']].matrix
    roots.append(hp.translation.copy())
    for s in 'LR':
        fw = mw @ rig.pose.bones[smap['foot.'+s]].matrix
        feet[s].append(fw.copy())
        pts = [fw @ p for p in sole[s]]
        if s in toe_sole:
            tw = mw @ rig.pose.bones[smap['toe.'+s]].matrix
            pts[1:] = [tw @ p for p in toe_sole[s]]
            rest = rig.data.bones[smap['foot.'+s]].matrix_local.to_quaternion().inverted() @ rig.data.bones[smap['toe.'+s]].matrix_local.to_quaternion()
            relative = fw.to_quaternion().inverted() @ tw.to_quaternion()
            angle = math.degrees(rest.rotation_difference(relative).angle)
            toe_bend = max(toe_bend, min(angle, 360-angle))
        toe_points[s].append(pts[-1].copy())
        gap = min(p.z for p in pts)
        penetration = max(penetration, -gap)
        gaps[s].append(gap)
        thigh = mw @ rig.pose.bones[smap['thigh.'+s]].matrix
        shin = mw @ rig.pose.bones[smap['shin.'+s]].matrix
        u, v = shin.translation-thigh.translation, fw.translation-shin.translation
        bend = math.degrees(u.angle(v))
        knees[s].append(bend)
        if s in prev_knees:
            jump = abs(bend-prev_knees[s])
            if jump > knee_jump:
                knee_jump, worst_knee = jump, [f,s,prev_knees[s],bend]
        prev_knees[s] = bend
    # Check the visible, skinned outsole too, including every airborne frame.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for shoe in shoes:
        ev = shoe.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        try:
            lows = {{s: math.inf for s in 'LR'}}
            for vertex in mesh.vertices:
                p = ev.matrix_world @ vertex.co
                side = min('LR', key=lambda s: (p-feet[s][-1].translation).length_squared)
                lows[side] = min(lows[side], p.z)
                mesh_penetration = max(mesh_penetration, -p.z)
            for side, low in lows.items():
                if f in flat_frames[side] and math.isfinite(low):
                    mesh_flat_gap = max(mesh_flat_gap, abs(low))
        finally:
            ev.to_mesh_clear()
for s, ivs in nav['foot_lock']['contacts'].items():
    for first, last in ivs:
        anchor = feet[s][first-nav['frames'][0]].translation
        for f in range(first, last+1):
            flat_drift = max(flat_drift, (feet[s][f-nav['frames'][0]].translation-anchor).length)
            flat_floor = max(flat_floor, abs(gaps[s][f-nav['frames'][0]]))
# Overlap is physical support, including heel/toe rolls, not flat-only contact metadata.
overlaps = []
toe_support_drift = 0.0
for ev in nav.get('support_events', []):
    other = 'R' if ev['side'] == 'L' else 'L'
    a, b = ev['opposite_land'], ev['lift']
    overlaps.append(b-a)
    if ev['side'] in toe_sole:
        anchor = toe_points[ev['side']][a-nav['frames'][0]]
        toe_support_drift = max(toe_support_drift, max((toe_points[ev['side']][i-nav['frames'][0]]-anchor).length for i in range(a,b+1)))
    assert all(gaps[ev['side']][i-nav['frames'][0]] < .002 for i in range(a, b+1)), (ev, gaps[ev['side']][a-1:b])
    assert gaps[other][a-nav['frames'][0]] < .002, ev
# Round 6: measure actual baked straight-walk joint angles and heel centres.
# Exclude the standing start and the two gathering/braking steps.
cycles = []
heel_widths, progression = [], []
route = nav.get('path_points', [])
straight = (len(route) >= 2 and route[-1][1] < route[0][1]
            and all(abs(p[0]-route[0][0]) < 1e-5 for p in route))
for side in ('LR' if straight else ''):
    lands = [e['frame'] for e in nav.get('footfalls', []) if e['side'] == side]
    for a,b in zip(lands, lands[1:]):
        if a < nav['frames'][0]+20 or b > nav['frames'][1]-30:
            continue
        cycles.append({{str(u): knees[side][round(a+(b-a)*u)-nav['frames'][0]]
                       for u in (0,.05,.2,.3,.4,.55,.8)}})
    for frame in lands:
        if nav['frames'][0]+20 < frame < nav['frames'][1]-30:
            i = frame-nav['frames'][0]
            heels = {{s: feet[s][i] @ sole[s][0] for s in 'LR'}}
            heel_widths.append(abs(heels['L'].x-heels['R'].x))
            rest = mw @ rig.data.bones[smap['foot.'+side]].matrix_local
            from mathutils import Vector
            forward = feet[side][i].to_quaternion() @ rest.to_quaternion().inverted() @ Vector((0,-1,0))
            progression.append(math.degrees(math.atan2(forward.x,-forward.y)) * (-1 if side=='L' else 1))
curve = {{u: sum(c[u] for c in cycles)/len(cycles) for u in cycles[0]}} if cycles else {{}}
end_motion = max((p-roots[-1]).length for p in roots[-4:])
# Ankle and all upper/lower body joints must settle in the final four frames.
settled = settled_rotation = 0.0
for name in smap.values():
    sc.frame_set(nav['frames'][1])
    anchor = (mw @ rig.pose.bones[name].matrix).copy()
    for f in range(nav['frames'][1]-3, nav['frames'][1]+1):
        sc.frame_set(f)
        mat = mw @ rig.pose.bones[name].matrix
        settled = max(settled, (mat.translation-anchor.translation).length)
        angle = anchor.to_quaternion().rotation_difference(mat.to_quaternion()).angle
        settled_rotation = max(settled_rotation, min(angle, 2*math.pi-angle))
result = dict(flat_drift_m=flat_drift, flat_floor_m=flat_floor, penetration_m=penetration,
              toe_bend_deg=toe_bend, toe_support_drift_m=toe_support_drift, overlap_frames=overlaps, knee_step_deg=knee_jump,
              worst_knee=worst_knee, knee_range_deg={{s: [min(v),max(v)] for s,v in knees.items()}},
              root_hold_m=end_motion, joint_hold_m=settled, joint_hold_rotation_rad=settled_rotation,
              mesh_penetration_m=mesh_penetration, mesh_flat_gap_m=mesh_flat_gap,
              destination_error_m=math.dist(roots[-1][:2], nav.get('destination', roots[-1][:2])),
              momentum=nav.get('momentum'), gaze=nav.get('gaze_lead'),
              knee_curve_deg=curve, cruise_heel_width_m=heel_widths, progression_deg=progression)
''')['result']


def main():
    engine = BlenderClient()
    evidence = Path(engine.workspace)
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        call = engine.call
        print('SCENE', json.dumps(call('scene_info')), flush=True)
        if '--baseline' in sys.argv:
            import subprocess
            source = subprocess.check_output(['git','show','fcdc0a1:engine/commands/walk.py'], cwd=ROOT, text=True)
            call('run_python', code="from engine.commands import walk\nexec(compile("+repr(source)+", 'walk_baseline.py', 'exec'), vars(walk))\nresult=True")
        call('new_scene', fps=24)
        h = call('create_realistic_human', name='Gait', gender=1, age=32, hair='short02', outfit='casual', seed=3)
        rig = h['armature']
        call('save_project', path='walk_gait_rest.blend')
        nav = call('walk_path', armature=rig, points=[[0,-5]], start_frame=1, avoid=False)
        measured = check(call, rig, nav)
        (evidence/'gait_metrics.json').write_text(json.dumps({'route':nav,'measured':measured}, indent=2))
        print('GAIT', json.dumps(measured), flush=True)
        call('save_project', path='walk_gait_round6.blend')
        if '--baseline' in sys.argv:
            print('WALK GAIT BASELINE MEASURED', flush=True)
            return
        assert measured['flat_drift_m'] <= .005 and measured['toe_support_drift_m'] <= .005, measured
        assert measured['flat_floor_m'] <= .002 and measured['penetration_m'] <= .002, measured
        # Authored soft shoe weights flex even with a fixed ankle. Keep that
        # visible sole near the floor while enforcing the 2 mm penetration cap.
        assert measured['mesh_penetration_m'] <= .002 and measured['mesh_flat_gap_m'] <= .01, measured
        assert measured['destination_error_m'] < .01, measured
        assert measured['root_hold_m'] < .001 and measured['joint_hold_m'] < .001, measured
        assert measured['joint_hold_rotation_rad'] < .002, measured
        assert 20 < measured['toe_bend_deg'] < 23, measured
        assert min(measured['overlap_frames']) >= 1, measured
        for ev in nav['support_events']:
            half = ev['land']-ev['opposite_land']
            # Each overlap is 10% of a full cycle, within half a video frame.
            assert abs((ev['lift']-ev['opposite_land'])/(2*half)-.10) <= .5/(2*half)+1e-9, ev
        assert measured['knee_step_deg'] < 25, measured
        assert all(.08 <= width <= .12 for width in measured['cruise_heel_width_m']), measured
        assert all(5 <= angle <= 10 for angle in measured['progression_deg']), measured
        assert 5 <= measured['knee_curve_deg']['0.2'] <= 12, measured
        assert 5 <= measured['knee_curve_deg']['0.3'] <= 12, measured
        assert 55 <= measured['knee_curve_deg']['0.8'] <= 65, measured
        assert measured['momentum']['lean_deg'][0] < -1 and measured['momentum']['lean_deg'][1] > 1, measured
        frames = [nav['support_events'][2]['opposite_land']+k for k in (0,1,2,3,5,8)]
        call('render_frames', frames=frames, view='right', size=512, engine='workbench', objects=[rig])
        for view in ('front','right','back','three_quarter'):
            call('render_preview', objects=[rig], view=view, frame=nav['support_events'][2]['lift'], width=384, height=384, engine='workbench')
        call('save_project', path='walk_gait_round6.blend')
        # A preceding gait can finish with one foot in flight. The initial
        # overlap must never turn that airborne pose into a reported contact.
        call('new_scene')
        call('create_human', name='Incoming')
        call('auto_rig_humanoid', mesh='Incoming')
        call('animate', armature='Incoming_rig', clip='walk', cycles=1)
        chained = call('walk_path', armature='Incoming_rig', points=[[0,-3]], avoid=False)
        floor = call('run_python', code=f'''
from engine.commands import anim
from engine.commands.footlock import _legs, _sole_points
rig = bpy.data.objects['Incoming_rig']
legs, smap = _legs(rig)
floor_error = 0.0
for side, intervals in {chained['foot_lock']['contacts']!r}.items():
    sole = _sole_points(rig, legs[side], 0)
    for a,b in intervals:
        for f in range(a,b+1):
            bpy.context.scene.frame_set(f)
            foot = rig.matrix_world @ rig.pose.bones[smap['foot.'+side]].matrix
            floor_error = max(floor_error, abs(min((foot @ p).z for p in sole)))
result = floor_error
''')['result']
        assert floor < .002, floor
        print('INCOMING GAIT CONTACT OK', floor, flush=True)
        print('WALK GAIT BAKED OK (MPFB support overlap, toe hinge, <=5 mm drift, <=2 mm penetration, settled hold)', flush=True)
    finally:
        engine.stop()


if __name__ == '__main__':
    main()
