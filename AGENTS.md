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
- Realistic humans (MPFB): `mpfb_assets`, `create_realistic_human`
- Face: `list_expressions`, `set_expression`, `lip_sync`, `auto_blink`
- Audio & voice: `add_audio`, `list_audio`, `remove_audio`, `transcribe_audio`,
  `lip_sync_audio`, `talk_motion`, `talk_gestures`, `ai_text_to_speech` (free HF Space)
- Characters & rigs: `create_human`, `estimate_landmarks`, `auto_rig_humanoid`,
  `validate_rig`, `list_bones`, `set_pose`
- Hands: `set_hand_pose` (relaxed, open, palm, beat, point, fist, thumbs_up, peace, ok)
- Animation: `list_animations`, `apply_pose`, `animate`, `import_mocap`,
  `retarget_animation`, `lock_feet`, `clear_animation`, `render_frames`
- Film: `list_camera_moves`, `camera_shot`, `list_shots`, `delete_shot`, `set_timeline`,
  `list_lighting_presets`, `set_lighting`, `set_material`, `render_video`,
  `render_status`, `cancel_render`
- Models from elsewhere: `prepare_model`
- AI (fal.ai paid / Hugging Face Spaces free): `ai_status`, `ai_text_to_3d`,
  `ai_image_to_3d`, `ai_image_to_video`, `ai_text_to_video`, `ai_job_status`, `ai_cancel_job`
- `run_blender_python` exists only when the server runs with `CHAR3D_ALLOW_PYTHON=1`.
  Prefer dedicated tools; if you must use it, keep scripts small and set `result`.

## Characters
`create_human(style=...)` makes a smooth mannequin body (no clothes, hair or face
details yet). Proportions by `style`: realistic 7.5 heads, heroic 8, stylized 6,
cartoon 4.5, chibi 3. `build` 0.7–1.4 = slim–heavy. Keep `arm_angle` 35 (A-pose) when
the character will be rigged.

## Realistic humans (MPFB / MakeHuman, CC0)
`create_realistic_human(name, gender, age, race, muscle, weight, height, hair, clothes)`
builds a textured human (skin, eyes, eyebrows, eyelashes, optional hair/clothes) that is
**already rigged** with MPFB's hand-made weights — do NOT run `auto_rig_humanoid` on it.
- gender 0 = female … 1 = male; age in years; muscle/weight/height/proportions 0..1;
  race weights like `{"asian": 1}`. `skin="auto"` matches age/gender/ethnicity.
- The armature is `<name>_rig`. `rig="game_engine"` (default; 53 Unreal-style bones
  `pelvis, spine_01, upperarm_l, calf_l…`, best for games/glTF) or `rig="rigify"` (full
  animator rig with face controls, ~930 bones, ~9 s to build; limbs set to FK). Also
  "mixamo", "default", "cmu_mb". `apply_pose`, `animate`, `import_mocap`,
  `retarget_animation` work on all of them.
- `face=True` (default) loads ARKit face shapes + visemes and adds teeth/tongue.
- Use the **armature** as the subject for framing/lighting:
  `camera_shot(subject=["Maya_rig"])`, `set_lighting(subject=["Maya_rig"])`,
  `render_preview(objects=["Maya_rig"])` (frames body + hair + clothes together).
- Hair: afro01, bob01 (black), bob02 (platinum blonde), braid01 (black), long01
  (dark auburn), ponytail01 (brown), short01/short04 (black), short02/short03 (brown).
  Clothes: male_casualsuit01-06, male_elegantsuit01, male_worksuit01,
  female_casualsuit01-02, female_elegantsuit01, female_sportsuit01, shoes01-06,
  fedora01, fedora_cocked. Full list: `mpfb_assets`.
- ~1.5–3.5 s to build; ~19k vertices + clothes. Use Eevee to see skin/clothes; workbench
  shows untextured grey. glTF export with textures is ~20 MB per character.
- MPFB weights use up to ~7 influences per vertex; game engines limited to 4 may need
  a weight-limit step on import.
- Use `create_human` (mannequin) for stylized/blockout work or when MPFB is missing
  (`mpfb_assets` errors → tell the user to run `scripts/install_mpfb.sh`).

## Hands
`set_hand_pose(character, shape, side)` poses the fingers on any rig with finger bones
(MPFB game_engine/mixamo/rigify, Mixamo, Rigify human); curl axes are derived from the
hand geometry, so shapes look the same on every skeleton. Shapes: relaxed, open, palm,
beat, point, fist, thumbs_up, peace, ok. Pair with arm poses, e.g. `apply_pose(rig,
"point_forward")` + `set_hand_pose(rig, "point", side="right")`; `keyframe=True, frame=N`
to animate. Mannequins from `create_human` have no fingers.

## Facial animation
Works on `create_realistic_human` characters (face=True) and any mesh with ARKit
blendshapes (e.g. VRoid/AI models). Pass the armature (`Dan_rig`) or the body mesh.
- `set_expression(character, expression, strength)`: neutral, smile, big_smile, laugh,
  sad, angry, furious, surprised, fear, disgust, smirk, wink_left/right, eyes_closed, pout,
  kiss, thinking, shout, sleepy, look_left/right/up/down, tongue_out. Fine-tune with
  `units={"jawOpen": 0.3, "browInnerUp": 0.5}` (ARKit names from `list_expressions`).
- Performance over time: call `set_expression(..., frame=N, keyframe=True)` repeatedly;
  each holds the previous face until N - transition_frames, then blends.
- `lip_sync(character, text, start_frame)`: mouth shapes from text (no audio is
  produced). ~14 chars/s. Combine with a light expression (smile 0.5) for life.
- `auto_blink(character)`: natural blinks over the scene range — always add it to any
  shot where the face is visible for more than ~2 s.
- Check faces with `camera_shot(shot="close_up" or "extreme_close_up")` +
  `render_preview(camera="scene", engine_name="eevee")` — workbench can't show skin.
- Expressions and lip sync are shape keys: they export to glTF as morph targets.

## Voice & audio lip sync
- `lip_sync_audio(character, audio, start_frame)` — mouth follows a real recording and the
  audio is placed on the timeline (render_video then outputs AAC sound). Timing modes:
  `whisper` (local speech recognition, exact word times, any language — default when
  installed), `text` (spread a given transcript over the voiced parts), `audio` (shapes
  guessed from the sound alone, speaker-adaptive). Result includes `transcript`.
- Audio paths are relative to `imports/` (e.g. `"audio/line1.wav"`) or absolute;
  wav/mp3/flac/ogg/m4a all work.
- No recording? `ai_text_to_speech(text, language)` makes one (free Chatterbox Space;
  23 languages, **no Indonesian — use "ms"**; anonymous daily GPU quota is small, an
  HF_TOKEN raises it). `voice_reference` imitates a voice: only the user's own voice or
  one they have permission to use. Then `lip_sync_audio` with the job's `audio` path.
- Always pair speech with `auto_blink`, a light `set_expression` (smile 0.4–0.5) and
  `talk_motion`, and frame with `close_up`/`medium` so the face is visible.
- `talk_motion(character)`: nods on stressed words, head drift + phrase tilts, brow
  flashes, eye saccades and "thinking" glances, eyes toward the shot camera. Layered:
  body animation is kept. **Order matters** — body clips (`animate`, mocap) →
  `set_expression` → `lip_sync_audio` → `camera_shot` → `auto_blink` → `talk_motion`
  last (it reads the audio/lip sync and the camera; `animate` afterwards over the same
  frames would overwrite the head; `set_expression(clear=True)` afterwards resets eye gaze
  at its frame).
- `talk_gestures(character, style)`: speaking posture + beat / open-palms / sweep / point
  gestures timed to stressed words; arms relax to the base animation in pauses. Styles:
  calm, presenter (default), energetic; `hands="right"` for one-handed talkers. Layered on
  the arm (and finger) bones only (works with any body clip underneath). Fingers follow
  each gesture (relaxed → beat half-fist / open palm / index point) on rigs with fingers. Frame with `medium` or
  `medium_full` so hands are visible.
- Recipe — talking presenter: `create_realistic_human` → `animate(rig, "idle")` →
  `lip_sync_audio(rig, "audio/line.wav")` → `set_expression(rig, "smile", 0.45, frame=1,
  keyframe=True)` → `set_lighting("studio")` → `camera_shot(shot="close_up",
  move="push_in")` → `auto_blink(rig)` → `talk_motion(rig)` → `talk_gestures(rig)` → `render_video`
  (use `shot="medium"` when gestures should be seen).
- `transcribe_audio` gives text + word times without animating (e.g. for subtitles).
- Whisper model: `tiny` by default (~75 MB, downloaded once). Set
  `CHAR3D_WHISPER_MODEL=base` or `small` for harder audio (accents, noise).

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
- **Foot lock (foot IK)** — planted feet stay still on the floor: contacts are detected
  (near the floor and not travelling ahead of the hips), the foot rolls heel → toe
  without slipping, never sinks into the floor, swinging feet keep ~2 cm clearance, and
  the legs are re-solved with 2-bone IK (hips lowered a little only when a leg can't
  reach). Automatic in `animate` for walk/run/jump (not with `in_place`) and in
  `import_mocap`; the result has `foot_lock.contacts` per foot. Turn off with
  `foot_lock=False`. For anything else keyed on a rig (retarget_animation, set_pose
  keys, older scenes) run `lock_feet(rig)` afterwards; force contacts with
  `contacts={"L": [[10, 27]], "R": [[1, 11]]}` or tune `height_tolerance` /
  `speed_tolerance` (m/s) / `floor`. Run it after body clips, before talk_motion /
  talk_gestures (those only touch head/arms, so the order there doesn't matter).
- Check motion with `render_frames([1, 9, 17, 25], view="right", objects=[mesh])`
  (side view for walking/running, three_quarter for gestures).
- Chained clips continue from where the previous one ended (no snapping back to
  the start position).
- `export_asset("hero.glb")` includes the animation; `export_asset("walk.bvh",
  objects=[rig])` writes motion only.
- Known limits: clips blend by hard cuts, not crossfades (a foot that is mid-step at a
  cut can pop); in_place walks keep their treadmill sliding by design; stairs/uneven
  ground are not supported (one flat floor height).

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

## AI generation (external services)
- **Only use `ai_*` generation tools when the user explicitly asks for AI generation** —
  they upload the prompt/image to a third party. Check `ai_status` first.
- `provider`: `"fal"` = paid fal.ai (needs FAL_KEY, fast, reliable); `"hf"` = FREE public
  Hugging Face Spaces (no key; may queue, hit the daily ZeroGPU quota, or be offline —
  a free HF_TOKEN raises the quota); `"auto"` (default) = fal when configured, else hf.
  If the user wants free only, pass `provider="hf"` explicitly.
- Free (hf) model recipes, pick with `model=`: image→3D `hunyuan3d` (default, untextured,
  fastest), `hunyuan3d-textured`, `trellis`, `stable-fast-3d`; image→video `ltx`
  (default), `wan`; text→video `ltx`; text→image `flux-schnell`. Free video clips are
  short (ltx ≤ 8 s, wan ≤ 5 s) and lower resolution.
- If a free Space fails (quota/offline), say so and offer another recipe, waiting, or
  fal — don't silently switch to the paid provider.
- All generation runs as background jobs: start → `ai_job_status(job_id)` every ~10 s.
  Stages: concept image → 3D model / video → download → import → prepare → rig.
- `ai_text_to_3d(prompt, name, character=True)`: the prompt is wrapped to ask for a
  full-body A-pose character on a plain background (better for rigging). Props: set
  `character=False` (no rig, no height normalisation).
- `ai_image_to_3d(image)`: local path or URL; best with one full-body subject in A-pose.
- After a 3D job: `render_views` the mesh. If it faces backwards, re-run
  `prepare_model([mesh], rotate_z=180)` and `auto_rig_humanoid` again. AI meshes are
  messy: check `validate_rig` and a test pose before animating.
- `ai_image_to_video(image, prompt)`: Higgsfield-style shots from a still. Typical
  combo: build the scene in char3d → `render_preview(camera="scene", engine_name="eevee",
  width=1280)` → `ai_image_to_video(that_path, "slow push in, wind in the hair")`.
- fal models are defaults that may change on fal.ai; override with `model=` and
  `extra_input={...}` using the field names from the model's fal.ai page.
- `prepare_model(objects, height, max_faces, rotate_z)` is also the way to clean any
  downloaded/marketplace model before rigging.

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
- `create_human` bodies are mannequins: no fingers, face, clothes or hair (use
  `create_realistic_human` for those).
- Slight creasing around neck/shoulders when the head or arms move a lot.
- Landmark estimation assumes a standard humanoid; creatures/quadrupeds are not
  supported yet.

## Roadmap (tools not available yet — say so instead of improvising)
- MPFB: more asset packs (hair/clothes)
- Phoneme-level forced alignment (word-level today)
- Crossfades between clips; foot IK on stairs / uneven ground
- Face rig / lip sync

## For agents editing this repo
- `engine/` runs inside Blender's bundled Python (has `bpy`); never import `bpy` in
  `mcp_server/`. Add an engine command with `@command("name")` in
  `engine/commands/*.py`, then a matching tool in `mcp_server/server.py`.
- Test end-to-end with `.venv/bin/python tests/e2e_smoke.py` and the offline AI pipeline
  with `.venv/bin/python tests/e2e_ai_mock.py` (local fake fal.ai, no key or network).
- `providers/` runs in the MCP server process (network); never call the network from
  `engine/`. Never log or persist API keys.
