# char3d — agent guide

This repo is a 3D character engine driven through MCP. A headless Blender process
(`engine/`) does the work; `mcp_server/` exposes it as tools. Use the **char3d** MCP
tools — do not try to launch Blender yourself.

## Conventions
- Units: meters. Z is up. Characters stand on Z=0 and **face -Y** (the "front" view).
- A human character is ~1.6–1.9 m tall. Check `dimensions` in `scene_info`.
- Object names are case-sensitive and unique; always take them from `scene_info`.
- Relative paths resolve inside the workspace (`output/` by default):
  `import_model` → `imports/`, `export_asset` → `exports/`,
  `save_project`/`open_project` → `projects/`, renders → `renders/`.

## Working loop (always)
1. `scene_info` — know what exists before changing anything.
2. Make **one** change.
3. Look at it: `render_preview` (workbench, ~1 s). For a character use
   `render_views` (front/right/back/¾) to check every side.
4. Fix what looks wrong before moving on. Don't claim a result you have not rendered.
5. `save_project` at milestones. Deliver assets with `export_asset("name.glb")`.

## Render engines (this machine has no dedicated GPU)
| engine | speed | use for |
|---|---|---|
| `workbench` | ~1 s | shape, proportions, pose, rig deformation checks |
| `eevee` | ~10 s | lit preview with materials, final stills |
| `cycles` | minutes | only when asked for photoreal quality |

Keep previews ≤ 512 px unless the user asks for more.

## Tools
- Scene: `engine_status`, `scene_info`, `new_scene`, `add_primitive`,
  `transform_object`, `delete_objects`
- Files: `import_model`, `export_asset`, `save_project`, `open_project`
- Look: `render_preview`, `render_views`
- Characters & rigs: `create_human`, `estimate_landmarks`, `auto_rig_humanoid`,
  `validate_rig`, `list_bones`, `set_pose`
- Animation: `list_animations`, `apply_pose`, `animate`, `import_mocap`,
  `retarget_animation`, `clear_animation`, `render_frames`
- Film: `list_camera_moves`, `camera_shot`, `list_shots`, `delete_shot`, `set_timeline`,
  `list_lighting_presets`, `set_lighting`, `set_material`, `render_video`,
  `render_status`, `cancel_render`
- `run_blender_python` exists only when the server runs with `CHAR3D_ALLOW_PYTHON=1`.
  Prefer dedicated tools; if you must use it, keep scripts small and set `result`.

## Characters
`create_human(style=...)` makes a smooth mannequin body (no clothes, hair or face
details yet). Proportions by `style`: realistic 7.5 heads, heroic 8, stylized 6,
cartoon 4.5, chibi 3. `build` 0.7–1.4 = slim–heavy. Keep `arm_angle` 35 (A-pose) when
the character will be rigged.

## Rigging
`auto_rig_humanoid(mesh, rig_type)`:
- `basic` (default): 21 deform bones — `hips, spine, chest, neck, head`,
  `shoulder/upper_arm/forearm/hand.{L,R}`, `thigh/shin/foot/toe.{L,R}`.
  Best for games, glTF export and mocap.
- `rigify`: animator rig. Pose these controls (limbs are set to FK):
  `torso`, `hips`, `chest`, `neck`, `head`, `upper_arm_fk.L`, `forearm_fk.L`,
  `hand_fk.L`, `thigh_fk.L`, `shin_fk.L`, `foot_fk.L`, `toe_fk.L` (+ `.R`).
  Exports keep only the 33 deform bones.
- `.L` = the character's left = world +X (the character faces -Y).
- Meshes from `create_human` carry exact joint landmarks. Other meshes get estimated
  landmarks: they must stand upright on Z=0, face -Y, in T- or A-pose. Check with
  `estimate_landmarks`, fix single joints via `landmarks={"elbow.L": [x,y,z]}`.
- Always read the report: `ok` must be true and `issues` empty-ish, then render a
  test pose (bend elbows/knees) with `render_views` before calling it done.

## Posing (`set_pose`, local Euler degrees, verified on char3d rigs)
| axis | meaning |
|---|---|
| X+ | bend / lift toward the **front**: spine leans forward, head nods down, arm swings forward, elbow curls (forearm X+), thigh lifts forward, toes up (foot X+) |
| X− on shin | knee bends naturally (shin X+ would hyper-extend) |
| Z | sideways. Left arm up = `upper_arm.L` Z+, right arm up = `upper_arm.R` Z−. Spine/head Z+ lean/tilt to the character's right |
| Y | twist along the bone |

Arms rest at ~35° down (A-pose), so arms fully down ≈ `upper_arm.L` Z −50, `.R` Z +50.
`reset=True` returns to rest pose. `keyframe=True, frame=N` keys the pose (simple
animation until phase 3 adds clips).

## Animation
Works on **any humanoid rig**: char3d `basic`, char3d `rigify`, and imported skeletons
with common naming (Mixamo `mixamorig:LeftArm`, CMU BVH `LeftUpLeg`, Unreal `thigh_l`,
...). Non-basic rigs are driven through a hidden proportion-matched basic rig and a
world-space retarget, so the same pose/clip looks the same everywhere.

- `apply_pose(armature, pose)` — library: rest, t_pose, relaxed, wave, cheer,
  point_forward, hands_on_hips, thinking, crouch, sit, fight_stance, run_pose.
  `keyframe=True, frame=N` to build pose-to-pose animation.
- `animate(armature, clip, start_frame, cycles, speed, amplitude, in_place)` — clips:
  idle (96 f), walk (32 f/cycle, moves forward −Y), run (18 f), wave (36 f),
  cheer (30 f), jump (40 f, one-shot), nod, head_shake (30 f). 24 fps.
  **Chain** clips with `start_frame = previous["next_start_frame"]`.
- `import_mocap(path, armature)` — .bvh/.fbx/.glb motion (CMU, Mixamo "without skin",
  Rokoko...). Matches names, T/A rest pose, facing and body size automatically;
  the imported source skeleton is deleted afterwards. If `mapped` is missing bones,
  pass `bone_map={"thigh.L": "their_bone", ...}` (keys = basic bone names).
- `retarget_animation(source, target)` — copy motion between two rigs in the scene.
- Check motion with `render_frames([1, 9, 17, 25], view="right", objects=[mesh])`
  (side view for walking/running, three_quarter for gestures).
- Chained clips continue from where the previous one ended (no snapping back to
  the start position).
- `export_asset("hero.glb")` includes the animation; `export_asset("walk.bvh",
  objects=[rig])` writes motion only.
- Known limits: feet can slide slightly on walk/run (no foot IK yet); clips blend by
  hard cuts, not crossfades.

## Film: cameras, lighting, video
**Lighting** — `set_lighting(preset, subject)`: studio, soft, dramatic, sunset, noon,
overcast, night, neon, silhouette, horror. Adds a large ground plane by default and
switches the scene to Eevee. `rotate` spins the rig of lights around the subject.
`set_material(objects, color, roughness, metallic, emission_strength)` for quick looks.

**Shots** — `camera_shot(subject, shot, move, start_frame, end_frame, angle, elevation,
intensity, handheld, roll, depth_of_field)`:
- shot sizes: extreme_wide, wide, full, medium_full, medium, medium_close, close_up,
  extreme_close_up (lens picked automatically, override with `lens`).
- moves: static, push_in, dolly_in, dolly_out, pull_out, orbit_left, orbit_right, arc,
  crane_up, crane_down, truck_left, truck_right, pan_left, pan_right, tilt_up,
  tilt_down, zoom_in, crash_zoom (ends on the face), dolly_zoom (vertigo), handheld,
  tracking, tracking_side (side-on follow, best for walks/runs), drone_reveal.
- angle 0 = front, 90 = subject's left, 180 = behind; elevation < 0 = low/heroic angle.
- The camera keeps framing a moving subject. One camera per shot; each adds a timeline
  marker so shots **cut** in order. Make shots back-to-back:
  `start_frame = previous["next_start_frame"]`. Re-use `name` to replace a shot.
- Check framing through the real cameras:
  `render_frames([first, middle, last], camera="scene", engine_name="eevee")`.

**Video** — `render_video(path, quality)` runs in a separate Blender process and returns
`job_id`; poll `render_status(job_id)` (progress, ETA). Measured on this machine
(960×540): draft ≈ 0.1 s/frame (clay, for timing), preview ≈ 2.7 s/frame (Eevee),
final is full-res 64 samples (~4× preview). Always do a draft first, then preview/final.
Vertical video: `width=1080, height=1920`. Output is H.264 MP4, 24 fps unless
`set_timeline(fps=...)`.

## Recipes
**Rigged character from scratch**
`new_scene` → `create_human(name="Hero", style="stylized")` → `render_views`
→ `auto_rig_humanoid("Hero")` → `set_pose` test → `render_views`
→ `set_pose(reset=True)` → `export_asset("hero.glb")`.

**Animated shot: walk in, wave, jump**
`create_human` → `auto_rig_humanoid` → `w = animate(rig, "walk", cycles=2)`
→ `a = animate(rig, "wave", start_frame=w.next_start_frame)`
→ `animate(rig, "jump", start_frame=a.next_start_frame)` → `render_frames` check
→ `save_project`.

**Short cinematic clip (Higgsfield-style)**
`create_human` → `auto_rig_humanoid(rig_type="rigify")` → `set_material`
→ `w = animate(rig, "walk", cycles=3)` → `animate(rig, "wave", start_frame=w.next_start_frame)`
→ `set_lighting("sunset", subject=[mesh])`
→ `camera_shot(subject=[mesh], shot="wide", move="drone_reveal", start_frame=1, end_frame=40)`
→ `camera_shot(..., shot="full", move="tracking_side", start_frame=41, end_frame=96)`
→ `camera_shot(..., shot="medium", move="crash_zoom", start_frame=97, end_frame=134)`
→ `render_frames(camera="scene")` check → `render_video(quality="draft", wait=True)`
→ `render_video("final.mp4", quality="final")` → poll `render_status`.

**Mocap on your character**
`auto_rig_humanoid(mesh, rig_type="rigify")` → `import_mocap("dance.bvh", rig)`
→ `render_frames` → `export_asset("hero_dance.glb")`.

**Rig a model someone gives you**
`new_scene` → `import_model(path)` → `scene_info` (stand on Z=0, face -Y, ~real height;
fix with `transform_object`) → `estimate_landmarks` → `auto_rig_humanoid`
→ test pose → `render_views`.

**Inspect a model**
`new_scene` → `import_model(path)` → `scene_info` → `render_views`.

## Known limitations
- Procedural bodies are mannequins: no fingers, face, clothes or hair.
- Slight creasing around neck/shoulders when the head or arms move a lot.
- Landmark estimation assumes a standard humanoid; creatures/quadrupeds are not
  supported yet.

## Roadmap (tools not available yet — say so instead of improvising)
- Phase 6: AI providers (text/image → 3D, image → video); MPFB realistic humans

## For agents editing this repo
- `engine/` runs inside Blender's bundled Python (has `bpy`); never import `bpy` in
  `mcp_server/`. Add an engine command with `@command("name")` in
  `engine/commands/*.py`, then a matching tool in `mcp_server/server.py`.
- Test end-to-end with `.venv/bin/python tests/e2e_smoke.py`.
