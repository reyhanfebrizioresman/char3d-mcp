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
- Face: `list_expressions`, `set_expression`, `auto_expression`, `lip_sync` (phoneme/word detail), `auto_blink`
- Audio & voice: `add_audio`, `duck_music`, `list_audio`, `remove_audio`, `transcribe_audio`,
  `lip_sync_audio`, `talk_motion`, `talk_gestures`, `ai_text_to_speech` (free HF Space)
- Dialog: `dialog`, `stage_dialog`
- Characters & rigs: `create_human`, `estimate_landmarks`, `auto_rig_humanoid`,
  `validate_rig`, `list_bones`, `set_pose`
- Hands: `set_hand_pose` (relaxed, open, palm, beat, point, fist, thumbs_up, peace, three,
  four, ok)
- Animation: `list_animations`, `apply_pose`, `animate`, `walk_path`, `turn_to`, `import_mocap`,
  `retarget_animation`, `lock_feet`, `clear_animation`, `render_frames`
- Film: `list_camera_moves`, `camera_shot`, `list_shots`, `delete_shot`, `set_timeline`,
  `list_lighting_presets`, `set_lighting`, `set_material`, `add_subtitles`,
  `remove_subtitles`, `add_transition`, `add_title`, `list_graphics`, `remove_graphics`,
  `render_options`, `render_video`, `render_status`, `cancel_render`
- Sets & props: `set_environment`, `add_prop`, `clear_environment`
- Walkable ground: `add_terrain`, `clear_terrain`
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
- MPFB weights use up to ~7 influences per vertex. For Unity/Unreal/glTF games use
  `export_asset("hero.glb", objects=["Maya_rig"], max_influences=4)`: keeps the N largest
  deform-bone weights and normalizes them on temporary mesh copies. The scene stays
  unchanged; the result reports `vertices_limited`. Default `None` keeps existing export
  behavior. Any positive integer is supported on skinned meshes; non-bone groups stay intact.
  Existing glTF modifier defaults can leave MPFB helper geometry visible after re-import;
  this also occurs without `max_influences`.
- Use `create_human` (mannequin) for stylized/blockout work or when MPFB is missing
  (`mpfb_assets` errors → tell the user to run `scripts/install_mpfb.sh`).

## Hands
`set_hand_pose(character, shape, side)` poses the fingers on any rig with finger bones
(MPFB game_engine/mixamo/rigify, Mixamo, Rigify human); curl axes are derived from the
hand geometry, so shapes look the same on every skeleton. Shapes: relaxed, open, palm,
beat, point, fist, thumbs_up, peace, three, four, ok. Pair with arm poses, e.g. `apply_pose(rig,
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
- `lip_sync(character, text, start_frame, language="auto", detail="phoneme")`: timed
  phonemes from text (no audio is produced), ~14 chars/s. Combine with a light smile.
  `language="id"`/`"ms"` uses Indonesian/Malay spelling (ng, ny, sy, kh, c/j, ai/au/oi,
  word-final k as a glottal stop; unmarked e uses a schwa/clear-e heuristic, é is clear).
  `"en"` uses English letter-to-sound rules plus common-word exceptions. Auto/None
  compares lexicon hit rates for the whole utterance; ties/unknown text use id.
  For short or mixed-language lines, choose the language explicitly.
- Phonemes are distributed **inside each word's start/end** using relative durations
  (longer vowels, shorter stops and final consonants). Smooth mouth targets anticipate
  o/u/w rounding, fully close m/b/p even in quiet audio, and make f/v lip-teeth contact.
  ARKit-only characters get approximate jaw/lip controls if Microsoft visemes are absent.
  `detail="word"` restores the old letter mapping and timing. Results include `language`,
  `detail`, and `phonemes`: `{word, phoneme, viseme, start, end, frame}` in scene frames;
  `frame` is the peak, or null when the phoneme is shorter than an available video frame.
  Example: `lip_sync("Dan_rig", "Mama buka pintu", language="id")`, then inspect the
  returned m/b/p, o/u and a peaks with `render_frames(camera="scene", engine_name="eevee")`.
  This is rule-based pronunciation and estimated timing, **not acoustic forced alignment**;
  irregular English words, Indonesian e and diphthong/hiatus ambiguities remain approximate.
- `auto_expression(character, frame_start=None, frame_end=None, base="smile",
  base_strength=0.35, intensity=1.0, language="auto", cues=None)`: sentence emotions
  from stored word times, after `lip_sync` or `lip_sync_audio` with text/Whisper timing.
  Local Indonesian/Malay + English lexicon: joy, sad, surprise, anger, fear/worry,
  thinking; phrases and suffixes, nearby negation ("tidak senang" suppresses joy),
  `!` boosts and `?` adds a questioning brow. `language`: auto (both), id, ms or en.
  Emotions arrive ~0.2 s before each sentence, hold, then relax toward the base in
  pauses; range defaults to the scene. `base_strength` 0..1; `intensity` >=0 scales
  inferred emotions, leaving the base and explicit cues at their chosen strengths.
  Replaces only brow/eye/cheek/nose and smile/frown-corner keys in the range; jaw,
  mouth articulation/visemes, blinks and gaze remain intact. `auto_blink` can run
  before or after; run `auto_expression` before `talk_motion` for its brow accents.
  Result `sentences` lists sentence → emotion/expression/strength → speech frames,
  keyed peak/hold `frames`, and `relax_frame` (None when the gap is too short).
  Force with `cues=[{"frame": 48, "expression": "sad", "strength": 0.7}]`: replaces
  the containing sentence, or holds ~0.6 s without words; out-of-range cues are ignored.
  Cues also preserve articulation/blink/gaze channels (e.g. a `surprised` cue never
  opens the jaw). Audio-only lip sync has no words: supply cues or use text/Whisper.
  This is a small lexicon, with local negation only; sarcasm/context are not understood.
  Example: `lip_sync(rig, "Senang sekali! Sayang sekali. Wah, ternyata hebat!")` →
  `auto_expression(rig)` → `auto_blink(rig)` → close-up Eevee `render_frames`.
- `auto_blink(character)`: natural blinks over the scene range — always add it to any
  shot where the face is visible for more than ~2 s.
- Check faces with `camera_shot(shot="close_up" or "extreme_close_up")` +
  `render_preview(camera="scene", engine_name="eevee")` — workbench can't show skin.
- Expressions and lip sync are shape keys: they export to glTF as morph targets.

## Voice & audio lip sync
- Background music: set the timeline first, then
  `add_audio("audio/music.wav", kind="music", volume=0.4, loop=True, fade_in=0.5, fade_out=1)`.
  `kind` is voice (default), music or sfx; it is saved on each sound strip. Music loops
  repeat to the current scene end (last repeat trimmed); fades in seconds span the whole
  track, not each repeat. Result `strips` lists all repeats; `strip` is the first.
- Run `duck_music(music_strip=None, amount_db=-12, attack=0.15, release=0.4)` after adding
  speech: music drops by the given dB relative to its original volume. Attack seconds
  lead speech and release seconds follow it. Speech is the union of unmuted voice-strip
  spans (legacy untagged strips count as voice) and all `char3d_words` lip-sync word times;
  gaps <= 0.5 s merge. Split voice strips at long silent pauses for music to recover there.
  Sfx/music do not count as speech. None ducks all music; a strip name selects its entire
  loop group. Fades remain; rerunning replaces that music's volume keys without cumulative
  attenuation. Rerun after changing speech; recreate loops if extending the timeline.
- `lip_sync_audio(character, audio, start_frame)` — mouth follows a real recording and the
  audio is placed on the timeline (render_video then outputs AAC sound). Timing modes:
  `whisper` (local speech recognition, exact word times, any language — default when
  installed), `text` (spread a given transcript over the voiced parts), `audio` (shapes
  guessed from the sound alone, speaker-adaptive). Whisper/text use phonemes automatically
  with `language="id"`/`"ms"`/`"en"` or auto/None as above; `detail="word"` keeps legacy
  behavior. Audio-only stays acoustic (`detail="audio"`), without pronunciation guesses.
  Whisper results include `transcript`; all word times remain available to subtitles and
  gestures. `transcribe_audio` still supports other Whisper languages independently.
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
- **Meaning gestures** (`semantic=True`, default): words with a meaning get an iconic gesture
  instead of a beat — numbers satu..lima / one..five (fingers counted, palm forward),
  saya/I (hand on chest), kamu/you (palm-up offer), ini/itu/this/that (point), besar/semua/big
  (wide hands), kecil/small (pinch), tidak/bukan/no (palms-down wipe), bagus/hebat/great
  (thumbs up), mungkin/apa/why (palms-up shrug), tunggu/stop (palm out), naik/turun/up/down,
  bersama/kita/together, pikir/ide/think (point at temple), cinta/terima kasih/love (hands on
  heart). Indonesian/Malay + English, suffixes like -nya/-lah/-kan are stripped. Needs word
  times: `lip_sync(text)` or `lip_sync_audio` with whisper/text timing store them on the
  face mesh (audio-only timing has none → beats only). Numbers always show; frequent words
  (saya, kamu, ini, itu, apa, kita) are used sparingly so the talker doesn't mime every word.
  The palm is turned with a twist shared by forearm and wrist. Result `semantic` lists
  word → gesture → frame. Force a gesture with
  `cues=[{"frame": 48, "gesture": "two"}, {"frame": 90, "gesture": "big", "hold_seconds": 0.8}]`
  (works without speech too); `semantic=False` for beats only.
- Recipe — talking presenter: `create_realistic_human` → `animate(rig, "idle")` →
  `lip_sync_audio(rig, "audio/line.wav")` → `set_expression(rig, "smile", 0.45, frame=1,
  keyframe=True)` → `set_lighting("studio")` → `camera_shot(shot="close_up",
  move="push_in")` → `auto_blink(rig)` → `talk_motion(rig)` → `talk_gestures(rig)` →
  `add_subtitles()` (optional captions) → `render_video` (use `shot="medium"` when gestures
  should be seen).
- `transcribe_audio` gives text + word times without animating.

## Dialog (2–4 characters)
`dialog(lines, ...)` performs a whole conversation in one call. `lines =
[{"speaker": "Ana_rig", "audio": "audio/a1.wav"}, {"speaker": "Budi_rig", "text": "..."}]`
(audio = real voice with Whisper timing and sound on the timeline; text = mouth only;
optional per line `pause_s` / `delay_s`). It:
- stages the cast (`stage_dialog`: left→right in order, facing each other, cheated 35°
  toward the camera; `layout` angled / face_to_face / side_by_side, `distance` m;
  `stage=False` keeps your placement),
- lip-syncs the lines back to back (`gap_s` apart) and tags each voice strip with its
  speaker, so `talk_motion` / `talk_gestures` react only to the character's own voice,
- gaze: everyone looks at whoever talks, the talker at the person they answer; listeners
  give small nods on the talker's stressed words; blinks; base `expression` (smile 0.3);
  an idle clip on rigs without animation; `gestures` per speaker (None = off),
- cameras (`camera`): `mixed` = two-shot for the first line, then a clean single of each
  speaker (`shot` size) cut 4 frames before they speak, all from the -Y side (180° rule);
  `singles`, `two_shot`, `none` (then frame it yourself with `camera_shot`).
Run body clips (animate, walk) BEFORE `dialog` (it keys head/eyes/arms on top); add
`add_subtitles()` afterwards for captions of every speaker. `talk_motion(look_at=...,
listen_to=...)` exposes the same gaze/listening for hand-made scenes. Check with
`render_frames([...], camera="scene", engine_name="eevee")` at a frame inside each line.
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
world-space retarget, so the same pose/clip looks the same everywhere. Rigs whose rest
pose has bent elbows (MPFB/MakeHuman rest with forearms ~45° forward) are normalised to a
straight A-pose arm first, so `relaxed`/walk arms hang at the sides on every rig.

- `apply_pose(armature, pose)` — library: rest, t_pose, relaxed, wave, cheer,
  point_forward, hands_on_hips, thinking, crouch, sit, fight_stance, run_pose.
  `keyframe=True, frame=N` to build pose-to-pose animation.
- `animate(armature, clip, start_frame, cycles, speed, amplitude, in_place)` — clips:
  idle (96 f), walk (32 f/cycle, moves forward −Y), run (18 f), wave (36 f),
  cheer (30 f), jump (40 f, one-shot), nod, head_shake (30 f). 24 fps.
  **Chain** clips with `start_frame = previous["next_start_frame"]`.
- **Floor routes and turns** — `walk_path(armature, points, clip="walk", start_frame=None,
  speed=1.0, face_end=None)` walks/runs from the current position through absolute world
  XY targets in meters, e.g. `walk_path("Maya_rig", [[0, -2], [2, -2], [2, 0]],
  face_end="camera")`. Ordinary corners use a smooth curve through the targets; duplicate
  consecutive points are ignored. Body yaw is limited to 100°/s, tight bends shorten steps
  and slow down, and corners sharper than 100° stop for an in-place stepping turn.
  Cadence and natural travel speed scale together with `speed` (0.1..4). Foot IK holds
  each support foot's world position **and rotation** throughout its contact, including
  turns. Two gathering steps finish in a still standing pose.
  `face_end` optionally faces an XY/XYZ point, object name or `"camera"`, sampled when the
  final turn begins. `turn_to("Maya_rig", "camera", start_frame=None)` turns in place
  by the shortest angle with alternating steps, then stands. Targets at the root's XY
  position leave its heading unchanged; `"camera"` requires a scene camera/shot.
  Both tools support basic, Rigify and MPFB rigs through the same proxy as `animate`;
  `start_frame=None` appends after the rig's existing action (otherwise scene start).
  Results include `frames`, `next_start_frame`, `distance_m`, `duration_seconds`, and
  `foot_lock.contacts`. Check `render_frames(..., view="top")` with waypoint markers
  for the route and `view="three_quarter"` for steps. Z follows walkable terrain (see below);
  no obstacle avoidance; feet use flat contacts rather than heel/toe rolls.
  Calls are limited to 1000 targets / 24000 frames; split longer routes and chain them.
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
- **Crossfades** — chained clips (`animate`, `import_mocap`, `retarget_animation`)
  blend in from the pose the rig has at `start_frame - 1`: automatic length 4–18 frames
  from the size of the change (walk→run ≈ 6, walk→wave ≈ 14, reported in `crossfade`),
  `blend_frames=N` to force, `0` for a hard cut. During a blend into a standing clip the
  planted foot stays put and the other finishes its step; feet stay planted for the rest
  of that clip. The first clip on a rig has nothing to blend from.
- Known limits: in_place walks keep their treadmill sliding by design; a crossfade holds the previous
  clip's last pose (it does not keep playing the old clip underneath).

## Walkable terrain
`add_terrain(kind, location=[x,y,z], rotation_z=0, width=1.2, length=None,
height=None, steps=None, name=None)` makes stairs, ramp, platform or step geometry in
`char3d_terrain`. Location is the base at the near edge, width is centered on local X,
and length extends along local -Y. Stairs/ramp rise toward the far end. To descend,
rotate 180° and put the low entrance at the far end of the route. Stairs default to
5 steps, 0.17 m rise, 0.28 m tread; height/steps/length determine rise and tread.
Platforms and single steps have flat tops. `clear_terrain()` removes owned geometry
and unused owned data, preserving characters, scenery and the environment stage.
- Meshes carry `char3d_walkable=True`; tag other static mesh surfaces to include them.
  Ground queries snapshot evaluated world-space geometry into a BVH once per bake and
  raycast downward, with the base Z floor as fallback. Only upward surfaces above that
  floor count; bridges use the highest surface. Moving/deforming terrain is not supported.
- `walk_path` derives Z from XY: smoothed root elevation, a small uphill lean, whole-sole
  tread placements, ramp pitch and swing arcs raised above the swept terrain by >=3 cm.
  Terrain uses shorter, slower walking steps, including when `clip="run"` is requested;
  the result reports the effective terrain gait and bake time. Flat scenes without
  walkable meshes retain the existing gait and keys.
- `lock_feet(rig, terrain=True)` (default) detects contacts relative to local ground and
  pitches/locks the sole on slopes. `terrain=False` uses only `floor`. Automatic foot lock
  in `animate`/mocap also queries terrain, but does not plan root elevation or safe treads:
  use `walk_path` for stairs. Run foot lock after body animation, before speaking layers.
- Results include `ground_heights` per contact, `max_penetration_m` and
  `min_swing_clearance_m` in meters, measured at heel/ball/toe sole landmarks. Swing
  clearance excludes the two frames adjacent to liftoff/touchdown (clearance approaches
  zero there); penetration includes every frame. These are skeletal sole measurements,
  not collision checks on every deformed shoe vertex.
- Limits: no obstacle avoidance or jumping between levels. Use rises <=0.20 m for
  adult human rigs and treads long enough for the full sole (normally >=0.28 m). Keep
  routes away from side edges; no whole-sole landing within 0.35 m raises an error.
  Very steep ramps, large drops, oversized feet and terrain turns in confined treads
  may exceed leg reach. Stage tops are also tagged walkable.

## Film: cameras, lighting, video
**Sets & props** — `set_environment(preset, subject=["Maya_rig"])` replaces the current
managed set (including added props) with procedural furniture and practical lights:
podcast_studio, classroom, office, stage, living_room, news_desk. Everything lives in
`char3d_env`, with clearly named parts and one transformable root. No downloads; original
low-poly geometry and simple materials, suitable for CPU Eevee.
- Sets anchor at the subject's feet and scale to its height; `scale=1.0` is the default
  multiplier. None = visible characters/geometry, or a 1.75 m reference at origin in an
  empty scene. Characters are never moved/posed. Podcast/news place a standing presenter
  behind the desk; the stage is raised by lowering its surroundings (top at the foot plane).
  The lighting ground is lowered with the stage and restored when the set is cleared.
- `variant=0` is a deterministic seed; odd values mirror side decor. `color_theme` accepts
  warm/cool/neutral or RGB overrides, e.g. `{"accent": [0.1, 0.5, 0.8]}` (wall/fabric too).
- `screen_image="slides.png"` uses a local image from imports/ (or an absolute path) on
  screens, laptop displays and whiteboards; upright UVs, stretched to fit. Otherwise,
  screens/boards show original geometric graphics. User images retain their own license.
- `add_prop(kind, location=[x,y,z], rotation_z=0, scale=1)` adds chair, desk, table,
  microphone, laptop, plant, lamp, screen, bookshelf, sofa or whiteboard. Units are meters,
  rotation_z is degrees (0 faces -Y); scale is independent of characters. Location is the
  floor/base center: desk height 1.02 m, coffee table 0.43 m; put microphones/laptops at
  desktop Z. Optional screen_image works here too. Move the returned root to move all parts.
- Practical lights survive `set_lighting`; `clear_environment()` removes only owned
  furniture/lights and unused owned data, preserving characters, cameras and lighting rigs.
  Set calls replace prior sets/props. The central -Y camera path is open; backdrops are
  open at the front/sides/top, designed for frontal medium/wide shots. Static furniture
  does not follow walking characters or solve seating, hands/desk collisions or arbitrary
  camera orbits. Use explicit character subjects for lighting and camera framing.
- Recipe: `set_environment("podcast_studio", subject=["Maya_rig"])` →
  `set_lighting("studio", subject=["Maya_rig"])` →
  `camera_shot(subject=["Maya_rig"], shot="wide", angle=8)` →
  `render_frames([1], camera="scene", engine_name="eevee")`. Inspect the result.

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

**Subtitles** — `add_subtitles(style)` turns on captions; `render_video` then burns them in
(a short Video Sequencer pass after the frames, ~0.1 s/frame) and writes an `.srt` next to the
MP4. `render_frames(camera="scene")` draws them too, so check the look there first.
- Words come automatically from `lip_sync` / `lip_sync_audio` word times (every speaker).
  Without a lip-synced character: `lines=[{"text": "...", "start": 0.5, "end": 2.8}]`
  (seconds from the scene start) or `audio="audio/vo.wav"` (local Whisper, placed at
  `start_frame`).
- Styles: `tiktok` (default; 1–3 big words, the spoken word highlighted yellow, pop-in,
  lower third — social/vertical video), `karaoke` (a line with the current word highlighted),
  `classic` (plain 1–2 line film subtitles). Tune with `position` (bottom, lower_third,
  center, top), `size`, `color` / `highlight_color` (RGB 0..1), `uppercase`, `max_words`,
  `font` (a .ttf/.otf path; default a bold system sans).
- Captions break at sentence ends, pauses > 0.6 s and long clauses. Calling `add_subtitles`
  again replaces the settings; `remove_subtitles` or `render_video(subtitles=False)` skips them.

**Video graphics** — titles and shot transitions share the subtitle Video Sequencer pass
(including draft renders), stored in the .blend as scene JSON. They keep the movie's frame
count and audio timing. Captions are drawn above titles; color fades cover everything.
- `add_transition(shot="Shot2", kind="crossfade", duration_s=0.5, name="cut")` blends
  into the named **incoming** shot; alternatively pass `at_frame=73` (its cut frame).
  Crossfades start at the cut and render extra **outgoing camera handles** over the incoming
  shot's first frames, then dissolve those handles in the compose pass. Both views show
  the same scene times; no offset/replayed movie frames or timeline shortening. Body
  animation continues; cameras whose keys stop at the cut hold the last transform/lens.
  Extra render cost is approximately duration × fps frames per crossfade.
- `kind="fade_black"` / `"dip_black"` (aliases) or `"fade_white"` dip through a solid
  color at the cut, with the duration centered on it. `kind="fade_in"` / `"fade_out"`
  need no target and fade from/to black at the scene start/end. Transitions must fit
  the adjacent shots/scene and cannot overlap; stale shot references fail at render time.
- `add_title("Maya", subtitle="Presenter", start_s=0.5, duration_s=3,
  style="lower_third", name="speaker")` draws a name + role on a translucent bar.
  `style="center"` gives a centered title card; `"corner"` puts it at top left.
  Times are seconds from the **scene** start, including when rendering a cropped range.
  Tune `size`, `color`, `background_color` (RGB 0..1), `background_opacity` (0..1), and
  `font` (local TTF/OTF). Long text wraps/shrinks to fit. `animation="slide"` (tags)
  or `"fade"` (center) enters/exits over `animation_s=0.3`, clamped for short titles;
  `"none"` is static. Text uses blf; rectangular bars use numpy-filled image pixels.
- Reuse `name` to replace a graphic; `list_graphics()` lists configs;
  `remove_graphics(name="speaker")` removes one, `remove_graphics(all=True)` removes all.
  Captions remain controlled by `remove_subtitles` / `subtitles=False` independently.
- `render_frames(camera="scene")` shows animated titles (hide with `graphics=False`).
  Transitions are video-only: inspect a draft's frames to check the dissolve/fade.
  Graphics are baked into MP4, not exported as glTF geometry or animation.

**Video** — `render_video(path, quality, resolution)` runs in a separate Blender process and
returns `job_id` + `estimate`; poll `render_status(job_id)` (progress, ETA). Measured on this
machine (960×540): draft ≈ 0.1 s/frame (clay, for timing), preview ≈ 2.7 s/frame (Eevee; ~4 s
with a clothed MPFB character + hair). final at 1920×1080, 64 samples: ≈ 48 s/frame with an
MPFB character (~10× preview, ≈ 4.5 h for a 15 s clip). Always do a draft first.
- **Let the user choose the resolution** before every preview/final/cycles render: call
  `render_options(quality, vertical)` — it lists 480p, 540p, 720p, 1080p, 1440p, 4k with the
  size and estimated total time for *this* scene — and ask the user to pick (show 3–4 sensible
  options with their times, e.g. 720p / 1080p / 1440p for final). Then
  `render_video(quality=..., resolution="<choice>")`. Don't start a render longer than ~10 min
  without that answer.
- Render speed depends on the machine (a GPU can be 10–50× faster than the CPU-only numbers
  above). The engine learns it per machine: every finished `render_video` stores the median
  frame time (`learned_speed` in `render_status`) in `~/.cache/char3d/render_speed.json`
  (override with `CHAR3D_RENDER_CALIB`). If `render_options` reports
  `machine_speed.measurements == 0` for that engine, call it with `calibrate=True` (one 480p
  test frame of the scene, ~5–20 s) before showing the times to the user.
- `resolution` renders at exactly that size for any quality; without it, preview/draft use
  half the scene size and final the full scene size. `width`/`height` for custom sizes.
- Vertical video: `vertical=True` (e.g. 1080p → 1080×1920). Output is H.264 MP4, 24 fps
  unless `set_timeline(fps=...)`.

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
→ `render_options("final")` → user picks a resolution
→ `render_video("final.mp4", quality="final", resolution="1080p")` → poll `render_status`.

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

## For agents editing this repo
- `engine/` runs inside Blender's bundled Python (has `bpy`); never import `bpy` in
  `mcp_server/`. Add an engine command with `@command("name")` in
  `engine/commands/*.py`, then a matching tool in `mcp_server/server.py`.
- Test end-to-end with `.venv/bin/python tests/e2e_smoke.py` and the offline AI pipeline
  with `.venv/bin/python tests/e2e_ai_mock.py` (local fake fal.ai, no key or network).
- `providers/` runs in the MCP server process (network); never call the network from
  `engine/`. Never log or persist API keys.
