"""Isolated Blender assertions called by e2e_smoke._motion_checks."""
import json
from fractions import Fraction
import os
import textwrap

from engine.motion_library import MOTIONS


async def single_engine_draft(call, text_of, filename, end):
    """Keep the existing script video assertions without a second Blender worker."""
    from pathlib import Path
    import av
    path = Path(__file__).resolve().parents[1]/"output"/"renders"/filename
    path.parent.mkdir(parents=True, exist_ok=True)
    await call("run_blender_python", code="bpy.context.scene.render.resolution_x=384\nbpy.context.scene.render.resolution_y=216\nresult=True")
    with av.open(str(path), mode="w") as movie:
        stream = movie.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = 384, 216, "yuv420p"
        stream.options = {"crf": "24", "preset": "fast"}
        for start in range(1, end+1, 12):
            res = await call("render_frames", frames=list(range(start, min(start+12, end+1))),
                             camera="scene", size=384, engine_name="workbench")
            for index, item in enumerate(map(json.loads, text_of(res)), start=start-1):
                with av.open(item["path"]) as source:
                    frame = next(source.decode(video=0))
                frame.pts = index
                frame.time_base = Fraction(1, 24)
                for packet in stream.encode(frame):
                    movie.mux(packet)
            print(f"SCRIPT DRAFT {min(start+11, end)}/{end}", flush=True)
        for packet in stream.encode():
            movie.mux(packet)
    return {"path": str(path), "status": "done", "frames": [1, end], "single_engine": True}


async def run(call, text_of):
    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])

    async def python(code):
        return (await data("run_blender_python", code=textwrap.dedent(code)))["result"]

    catalog = await data("list_animations")
    registry = catalog["clips"]
    assert set(MOTIONS) <= registry.keys()
    assert set(MOTIONS) <= catalog["poses"].keys()
    for clip, meta in MOTIONS.items():
        assert all(registry[clip][k] == meta[k] for k in meta), clip
    totals, seam_max, contact_max = {}, 0., 0.
    families = os.environ.get("CHAR3D_MOTION_FAMILIES", "mpfb,basic,rigify,mpfb_rigify").split(",")
    selection = os.environ.get("CHAR3D_MOTION_CLIPS")
    for family in families:
        assert family in ("mpfb", "basic", "rigify", "mpfb_rigify"), family
        await call("new_scene")
        if family.startswith("mpfb"):
            rig = (await data("create_realistic_human", name="MotionTest", gender=0,
                              rig="rigify" if family == "mpfb_rigify" else "game_engine",
                              clothes=[], hair=None, face=True))["armature"]
        else:
            await call("create_human", name="MotionTest", style="realistic")
            rig = (await data("auto_rig_humanoid", mesh="MotionTest", rig_type=family))["armature"]
        drivers = await python(f"r=bpy.data.objects[{rig!r}];result=len(r.animation_data.drivers) if r.animation_data else 0")
        if family in ("rigify", "mpfb_rigify"):
            assert drivers > 0, (family, drivers)
        clips = list(MOTIONS) if family in ("mpfb", "basic") else ["sad", "cry", "drink", "phone_call", "kneel", "lie_down", "get_up", "sit_floor", "type", "dance_traditional", "punch", "kick"]
        if selection:
            clips = selection.split(",")
            assert set(clips) <= MOTIONS.keys(), clips
        for clip in clips:
            print(f"MOTION CHECK {family}/{clip}", flush=True)
            await call("clear_environment")
            await call("clear_animation", armature=rig)
            remaining = await python(f"r=bpy.data.objects[{rig!r}];result=len(r.animation_data.drivers) if r.animation_data else 0")
            assert remaining == drivers, (family, "clear_animation removed structural drivers", drivers, remaining)
            await call("set_timeline", frame_start=1, frame_end=2)
            start = 1
            if clip == "type":
                chair = (await data("add_prop", kind="chair"))["root"]
                await call("sit_on", character=rig, seat=chair, start_frame=1)
                await call("add_prop", kind="laptop", location=[0, -.45, .72], rotation_z=180)
                start = 24
            for kind in MOTIONS[clip]["required_props"]:
                prop = (await data("add_prop", kind=kind))["root"]
                prop_hand = "left" if family == "mpfb_rigify" else "right"
                await call("hold_prop", character=rig, prop=prop, start_frame=1, hand=prop_hand)
            result = await data("animate", armature=rig, clip=clip, start_frame=start, cycles=2 if MOTIONS[clip]["loops"] else 1,
                                speed=2, blend_frames=0, **({"bpm": 90} if clip.startswith("dance_") else {}))
            assert result["frames"][1] > start and result["next_start_frame"] == result["frames"][1]+1
            if clip == "type":
                assert result["seated_lower_body_preserved"]
                stable = await python(f"""
                    from engine.commands.anim import semantic_map
                    from engine.commands.gaze import head_frame
                    from mathutils import Vector
                    r=bpy.data.objects[{rig!r}];s=semantic_map(r);rows=[]
                    for f in {[start-1,start+result['cycle_frames']]!r}:
                        bpy.context.scene.frame_set(f)
                        rows.append([(r.matrix_world@r.pose.bones[s[b]].matrix).translation.copy() for b in ('hips','foot.L','foot.R')])
                    left=head_frame(r,'hips')[1]@Vector((1,0,0))
                    hands=[(r.matrix_world@r.pose.bones[s['hand.'+side]].matrix).translation for side in 'LR']
                    result=dict(stable=max((a-b).length for a,b in zip(*rows)), hands=(hands[0]-hands[1]).dot(left))
                """)
                assert stable["stable"] < .001 and stable["hands"] > .1, (family, stable)
            if clip in ("drink", "phone_call"):
                assert result["contact_error_m"] < .03, (family, clip, result)
                contact_max = max(contact_max, result["contact_error_m"])
                held = await python(f"""
                    obj=bpy.data.objects[{prop!r}]
                    result=dict(owner=obj.get('c3d_hold_character'), constraint=any(c.name.startswith('char3d_hold') for c in obj.constraints))
                """)
                assert held["owner"] == rig and held["constraint"], held
                distance = await python(f"""
                    from engine.commands.anim import semantic_map
                    from engine.commands.gaze import head_frame
                    from mathutils import Vector
                    r=bpy.data.objects[{rig!r}];s=semantic_map(r)
                    bpy.context.scene.frame_set({start+round(result['cycle_frames']*.5)})
                    center,q=head_frame(r)
                    height=(r.matrix_world@r.data.bones[s['head']].tail_local).z-r.matrix_world.translation.z
                    point=center+q@Vector((0,-.052*height,-.025*height))
                    wrist=(r.matrix_world@r.pose.bones[s[{'hand.L' if family == 'mpfb_rigify' else 'hand.R'!r}]].matrix).translation
                    side={'L' if family == 'mpfb_rigify' else 'R'!r}
                    elbow=(r.matrix_world@r.pose.bones[s['forearm.'+side]].matrix).translation
                    shoulder=(r.matrix_world@r.pose.bones[s['upper_arm.'+side]].matrix).translation
                    front=head_frame(r,'hips')[1]@Vector((0,-1,0))
                    result=dict(distance=(point-wrist).length, elbow_rise=elbow.z-shoulder.z,
                                elbow_front=(elbow-shoulder).dot(front))
                """)
                # Arm/head proportions can put a phone elbow slightly above
                # the shoulder. It must remain in front, away from the ear/back.
                assert (distance["distance"] < .23 and distance["elbow_rise"] < .06
                        and (not family.startswith("mpfb") or distance["elbow_front"] > -.005)), (family, clip, distance)
            if family in ("rigify", "mpfb_rigify"):
                deform = await python(f"""
                    from engine.commands.anim import semantic_map
                    r=bpy.data.objects[{rig!r}];s=semantic_map(r)
                    bpy.context.scene.frame_set({start+round(result['cycle_frames']*.5)})
                    result=max(((r.matrix_world@r.pose.bones[s[b+'.'+side]].matrix).translation-
                                (r.matrix_world@r.pose.bones['DEF-'+b+'.'+side].matrix).translation).length
                               for b in ('forearm','hand','foot') for side in 'LR')
                """)
                assert deform < .004, (family, clip, "deform bones must follow FK controls", deform)
            if clip in ("facepalm", "thinking", "cover_mouth"):
                contact = await python(f"""
                    from engine.commands.anim import semantic_map
                    from engine.commands.gaze import head_frame
                    from engine.commands.holding import _palm
                    from mathutils import Vector
                    r=bpy.data.objects[{rig!r}];s=semantic_map(r)
                    bpy.context.scene.frame_set({start+round(result['cycle_frames']*.5)})
                    head,q=head_frame(r)
                    height=((r.matrix_world@r.data.bones[s['head']].tail_local).z-r.matrix_world.translation.z)*1.04
                    bone,palm=_palm(r,'R')
                    actual=(r.matrix_world@r.pose.bones[bone].matrix)@palm.translation
                    offsets=({{'facepalm':(0,-.066,.003),'thinking':(0,-.06,-.08),'cover_mouth':(0,-.07,-.06)}}
                             if {family.startswith('mpfb')!r} else {{'facepalm':(0,-.068,.04),'thinking':(0,-.05,-.05),'cover_mouth':(0,-.06,-.025)}})
                    goal=head+q@(Vector(offsets[{clip!r}])*height)
                    result=(actual-goal).length
                """)
                assert contact < .06, (family, clip, contact)
            if clip in ("point", "punch", "angry") and family.startswith("mpfb"):
                fingers = await python(f"""
                    from engine.commands.fingers import find_fingers
                    from engine.commands.gaze import head_frame
                    from mathutils import Vector
                    r=bpy.data.objects[{rig!r}]
                    bpy.context.scene.frame_set({start+round(result['cycle_frames']*.5)})
                    names=find_fingers(r)['R']['index']
                    a=r.matrix_world@r.pose.bones[names[0]].head
                    b=r.matrix_world@r.pose.bones[names[-1]].tail
                    rest=sum((r.data.bones[n].tail_local-r.data.bones[n].head_local).length for n in names)*r.matrix_world.to_scale().x
                    front=head_frame(r,'hips')[1]@Vector((0,-1,0))
                    result=dict(extension=(b-a).length/rest,direction=(b-a).normalized().dot(front))
                """)
                if clip == "point":
                    assert fingers["extension"] > .8 and fingers["direction"] > .6, (family, clip, fingers)
                else:
                    assert fingers["extension"] < .65, (family, clip, fingers)
            if clip in ("kneel", "lie_down", "get_up", "sit_floor", "fall_down"):
                measured = await python(f"""
                    import numpy as np
                    rig=bpy.data.objects[{rig!r}]
                    rows=[]
                    for f in { [start+round((result['frames'][1]-start)*x) for x in (.25,.5,1.)]!r}:
                        bpy.context.scene.frame_set(f)
                        lows=[]
                        for obj in rig.children_recursive:
                            if obj.type!='MESH' or obj.hide_render: continue
                            ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh=ev.to_mesh()
                            try:
                                co=np.empty(len(mesh.vertices)*3);mesh.vertices.foreach_get('co',co)
                                m=np.asarray(ev.matrix_world)
                                lows.append(float((co.reshape(-1,3)@m[2,:3]+m[2,3]).min()))
                            finally: ev.to_mesh_clear()
                        rows.append(min(lows))
                    result=rows
                """)
                assert all(-.012 <= z <= .012 for z in measured), (family, clip, measured)
            if clip in ("kneel", "pick_up"):
                planted = await python(f"""
                    from engine.commands.anim import semantic_map
                    r=bpy.data.objects[{rig!r}];s=semantic_map(r);rows=[]
                    for f in {[start,start+round(result['cycle_frames']*.5),result['frames'][1]]!r}:
                        bpy.context.scene.frame_set(f)
                        rows.append({{side:(r.matrix_world@r.pose.bones[s['foot.'+side]].matrix).translation.xy.copy() for side in 'LR'}})
                    result=max((row[side]-rows[0][side]).length for row in rows for side in 'LR')
                """)
                assert planted < .015, (family, clip, planted)
            if MOTIONS[clip]["loops"]:
                seam = await python(f"""
                    from engine.commands.anim import semantic_map
                    r=bpy.data.objects[{rig!r}];sm=semantic_map(r);poses=[]
                    for f in {[start,start+result['cycle_frames'],result['frames'][1]]!r}:
                        bpy.context.scene.frame_set(f)
                        poses.append({{k:(r.matrix_world@r.pose.bones[n].matrix).copy() for k,n in sm.items()}})
                    loc=max((poses[0][b].translation-p[b].translation).length for p in poses[1:] for b in sm)
                    angle=max(poses[0][b].to_quaternion().rotation_difference(p[b].to_quaternion()).angle for p in poses[1:] for b in sm)
                    result=dict(location=loc,angle=angle)
                """)
                assert seam["location"] < .015 and seam["angle"] < .05, (family, clip, seam)
                seam_max = max(seam_max, seam["location"])
            if "foot_lock" in result:
                assert any(result["foot_lock"]["contacts"].values()), (family, clip)
                if MOTIONS[clip]["category"] in ("body_language", "dance"):
                    drift = await python(f"""
                        from engine.commands.anim import semantic_map
                        r=bpy.data.objects[{rig!r}];s=semantic_map(r);worst=0.
                        for side,spans in {result['foot_lock']['contacts']!r}.items():
                            for a,b in spans:
                                points=[]
                                for f in (a,(a+b)//2,b):
                                    bpy.context.scene.frame_set(f)
                                    points.append((r.matrix_world@r.pose.bones[s['foot.'+side]].matrix).translation.copy())
                                worst=max(worst,max((p-points[0]).length for p in points))
                        result=worst
                    """)
                    assert drift < .01, (family, clip, drift)
            await call("apply_pose", armature=rig, pose=clip,
                       frame=start+round(result["cycle_frames"]*.5), keyframe=False)
        totals[family] = len(clips)
        print(f"MOTION BAKE OK {family}: {len(clips)} clips", flush=True)

    # World-space parity after movement, arbitrary yaw and uniform scaling.
    await call("new_scene")
    for i, (yaw, scale) in enumerate(((0, 1), (35, .85))):
        await call("create_realistic_human", name=f"Parity{i}", gender=1, face=False, hair=None, clothes=[])
        await call("transform_object", name=f"Parity{i}_rig", location=[i*2, .4*i, 0], rotation_deg=[0, 0, yaw], scale=[scale]*3)
        await call("animate", armature=f"Parity{i}_rig", clip="dance_traditional", bpm=120, cycles=1, blend_frames=0)
    parity = await python("""
        from engine.commands.anim import semantic_map
        from mathutils import Vector
        bpy.context.scene.frame_set(19)
        rows=[]
        for i in range(2):
            r=bpy.data.objects[f'Parity{i}_rig'];s=semantic_map(r)
            inv=r.matrix_world.to_3x3().inverted()
            origin=(r.matrix_world@r.pose.bones[s['hips']].matrix).translation
            rows.append({b:list(inv@((r.matrix_world@r.pose.bones[n].matrix).translation-origin)) for b,n in s.items()})
        result=max((Vector(rows[0][b])-Vector(rows[1][b])).length for b in rows[0])
    """)
    assert parity < .025, parity

    # A chained action preserves earlier keys; phase transitions end at the same pose.
    await call("new_scene")
    await call("create_human", name="Chain")
    await call("auto_rig_humanoid", mesh="Chain")
    w = await data("animate", armature="Chain_rig", clip="walk", cycles=1)
    a = await data("animate", armature="Chain_rig", clip="shrug", start_frame=w["next_start_frame"])
    assert a["crossfade"]["blend_frames"] >= 4 and a["foot_lock"]["contacts"]["L"]
    down = await data("animate", armature="Chain_rig", clip="kneel", phase="down", start_frame=a["next_start_frame"])
    up = await data("animate", armature="Chain_rig", clip="kneel", phase="up", start_frame=down["next_start_frame"])
    assert up["frames"][0] == down["frames"][1]+1
    turn = await data("turn_to", armature="Chain_rig", target=[3, -1], start_frame=up["next_start_frame"], avoid=False)
    dance = await data("animate", armature="Chain_rig", clip="dance_casual", start_frame=turn["next_start_frame"], bpm=120, cycles=1)
    heading = await python(f"""
        from engine.commands.gaze import head_frame
        from engine.commands.anim import semantic_map
        from engine.commands.seating import _rest_front
        from mathutils import Vector
        r=bpy.data.objects['Chain_rig'];s=semantic_map(r);rows=[]
        for f in {[turn['frames'][1],dance['frames'][0]+24]!r}:
            bpy.context.scene.frame_set(f)
            front=head_frame(r,'hips')[1]@Vector((0,-1,0))
            front.z=0;front.normalize();rows.append(front)
        rest_front=_rest_front(r,s)
        errors=[]
        for side in 'LR':
            p=r.pose.bones[s['foot.'+side]]
            posed=(r.matrix_world@p.matrix).to_quaternion()
            rest=(r.matrix_world@p.bone.matrix_local).to_quaternion()
            foot=posed@rest.inverted()@rest_front
            errors.append(foot.normalized().angle(rows[-1]))
        result=dict(body=rows[0].angle(rows[1]),feet=max(errors))
    """)
    assert heading["body"] < .02 and heading["feet"] < .05, heading
    import shutil
    from pathlib import Path
    output = Path(__file__).resolve().parents[1]/"output"/"motion_sheets"
    output.mkdir(parents=True, exist_ok=True)
    for view in ("front", "right", "three_quarter"):
        image = await call("render_frames", frames=[dance["frames"][0]+24], view=view, size=256, objects=["Chain_rig"])
        path = json.loads(text_of(image)[0])["path"]
        shutil.copyfile(path, output/f"heading_after_turn_{view}.png")
    confident = await data("animate", armature="Chain_rig", clip="confident", start_frame=dance["next_start_frame"])
    entry = await python(f"""
        from engine.commands.anim import semantic_map
        r=bpy.data.objects['Chain_rig'];s=semantic_map(r);rows=[]
        for f in {[dance['frames'][1],confident['frames'][0]]!r}:
            bpy.context.scene.frame_set(f)
            rows.append([(r.matrix_world@r.pose.bones[s['hand.'+side]].matrix).translation.copy() for side in 'LR'])
        result=max((a-b).length for a,b in zip(*rows))
    """)
    assert entry < .04, ("contact targets must retain the entry crossfade", entry)
    print(f"MOTION E2E OK {totals} | seam {seam_max:.6f} m | prop contact {contact_max:.5f} m | rotated parity {parity:.5f} m", flush=True)


async def scene_checks(call, text_of):
    """Directions, automatic typing props, emotion faces and the static pose API."""
    async def data(tool, **args):
        return json.loads(text_of(await call(tool, **args))[-1])

    await call("new_scene")
    script = """ANA (perempuan, 28, rambut bob): Aku sedih sekali.
BUDI (laki-laki, 32, rambut pendek): Aku senang bertemu kamu.
[Ana menangis]
[Budi tertawa]
[Ana mengetik]
[Budi minum]
[Ana minum]
[Budi menelepon]
"""
    built = await data("script_to_scene", script=script, voice=False, sound=False, subtitles=False, camera="none")
    assert {r["clip"] for r in built["body_language"]} >= {"sad", "happy"}, built["body_language"]
    beats = {b.get("name"): b for b in built["plan"]["beats"] if b.get("do") == "gesture"}
    assert len(beats["type"]["created_props"]) == 2, beats["type"]
    assert beats["type"]["result"]["seated_lower_body_preserved"]
    assert beats["drink"]["result"]["contact_error_m"] < .03
    props = json.loads(text_of(await call("run_blender_python", code="""
result={kind:[dict(owner=o.get('c3d_hold_character'),hand=o.get('c3d_hold_hand'))
              for o in bpy.context.scene.objects if o.get('c3d_prop_kind')==kind]
        for kind in ('cup','phone')}
"""))[-1])["result"]
    assert len(props["cup"]) == 2 and len({o["owner"] for o in props["cup"]}) == 2, props
    assert props["phone"][0]["hand"] == "left", props
    ranges = {name: beat["frames"] for name, beat in beats.items()}
    code = f"""
from engine.commands.face import _basemesh
result={{}}
for ident,clip,unit in [('ANA','cry','mouthFrownLeft'),('BUDI','laugh','jawOpen')]:
    a,b={ranges!r}[clip]
    bpy.context.scene.frame_set((a+b)//2)
    mesh=_basemesh({built['characters']!r}[ident]['rig'])
    result[clip]=mesh.data.shape_keys.key_blocks[unit].value
"""
    faces = (await data("run_blender_python", code=code))["result"]
    assert faces["cry"] > .25 and faces["laugh"] > .2, faces
    rig = built["characters"]["ANA"]["rig"]
    plain = await data("dialog", lines=[{"speaker": rig, "text": "Aku takut."}], stage=False,
                       start_frame=built["frames"][1]+30, camera="none", gestures=None)
    assert "body_language" not in plain
    aware = await data("dialog", lines=[{"speaker": rig, "text": "Aku takut.", "emotion": "fear"}],
                       stage=False, start_frame=plain["next_start_frame"]+30, camera="none", gestures=None,
                       body_language=True)
    assert aware["body_language"][0]["clip"] == "nervous", aware

    await call("new_scene")
    await call("create_human", name="PoseTest")
    await call("auto_rig_humanoid", mesh="PoseTest")
    for clip, meta in MOTIONS.items():
        await call("clear_environment")
        await call("clear_animation", armature="PoseTest_rig")
        await call("set_timeline", frame_start=1, frame_end=2)
        if meta["required_seat"]:
            chair = (await data("add_prop", kind="chair"))["root"]
            await call("sit_on", character="PoseTest_rig", seat=chair, start_frame=1)
        for kind in meta["required_props"]:
            prop = (await data("add_prop", kind=kind))["root"]
            await call("hold_prop", character="PoseTest_rig", prop=prop, start_frame=1)
        before = (await data("run_blender_python", code="from engine.commands.talk import _fcurves\nr=bpy.data.objects['PoseTest_rig']\nresult=sum(len(c.keyframe_points) for c in _fcurves(r.animation_data.action if r.animation_data else None))"))["result"]
        await call("apply_pose", armature="PoseTest_rig", pose=clip, frame=1, keyframe=False)
        after = (await data("run_blender_python", code="from engine.commands.talk import _fcurves\nr=bpy.data.objects['PoseTest_rig']\nresult=sum(len(c.keyframe_points) for c in _fcurves(r.animation_data.action if r.animation_data else None))"))["result"]
        assert before == after, (clip, before, after)
    print("MOTION SCENE OK | directions + auto desk/laptop/cup | cry/laugh faces | dialog opt-in | 46 unkeyed poses", flush=True)
