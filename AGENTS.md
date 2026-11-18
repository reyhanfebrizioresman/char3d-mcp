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
- Look: `cinematic_look`, `render_style`, `render_preview`, `render_views` (`engine_name="eevee"` for textures)
- Realistic humans (MPFB): `mpfb_assets` (categories + installed packs),
  `create_realistic_human` (optional CC0 packs, beard, seeded outfit)
- Face: `list_expressions`, `set_expression`, `auto_expression`, `lip_sync` (phoneme/word detail), `auto_blink`
- Audio & voice: `add_audio`, `auto_sfx`, `duck_music`, `list_audio`, `remove_audio`, `transcribe_audio`,
  `list_voices`, `text_to_speech`, `lip_sync_audio`, `talk_motion`, `talk_gestures`,
  `ai_text_to_speech` (legacy free HF Space)
- Dialog: `dialog`, `stage_dialog`, `script_to_scene` (live dialog coverage, guest seating, outfits + hair/cloth motion)
- Characters & rigs: `create_human`, `estimate_landmarks`, `auto_rig_humanoid`,
  `validate_rig`, `list_bones`, `set_pose`
- Hands: `set_hand_pose` (relaxed, open, palm, beat, point, fist, thumbs_up, peace, three,
  four, ok, grip)
- Animation: `list_animations`, `apply_pose`, `animate`, `walk_path`/`turn_to` (static obstacle avoidance), `import_mocap`,
  `retarget_animation`, `lock_feet`, `secondary_motion` (hair/loose clothes), `clear_animation`, `render_frames`
- Film: `list_camera_moves`, `camera_shot` (visibility + composition), `list_shots`, `delete_shot`, `set_timeline`,
  `list_lighting_presets`, `set_lighting`, `cinematic_look`, `set_material`, `add_subtitles`,
  `remove_subtitles`, `add_transition`, `add_title`, `list_graphics`, `remove_graphics`,
  `render_options`, `render_video`, `render_status`, `cancel_render`
- Sets & props: `set_environment`, `add_prop`, `clear_environment`, `sit_on`, `stand_up`,
  `hold_prop`, `release_prop` (indoor + city_street, park, cafe_terrace, beach)
- Interactions: `interact` (handshake, hug, high_five, fist_bump, handover, pat_shoulder)
- Weather: `set_weather` (clear, rain, snow, fog, wind; saved procedural animation)
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
`create_realistic_human(name, gender, age, race, muscle, weight, height, hair, clothes,
beard=None, outfit=None, seed=0)`
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
- Install optional CC0 packs with `scripts/install_mpfb_packs.sh` (all 12), or pass
  pack names, e.g. `scripts/install_mpfb_packs.sh shirts01 pants01 hair01`.
  Cached archives are reused; recorded sizes/checksums are in `scripts/mpfb_packs.tsv`.
- List everything with `mpfb_assets()`: `assets` groups skins, hair, beards/moustaches,
  eyes, eyebrows, eyelashes, teeth, tongue, clothes and proxies; `packs` lists installed
  members per pack. Existing names/lists remain usable. `clothing_categories` groups
  clothes by category; `clothing_metadata[name]` gives category, gender, display name,
  tags and z_depth. Hair/skin/eyebrow/eyelash parameters accept installed names.
- Examples (optional packs must be installed): tops `namuhekam_male_polo_shirt`,
  `toigo_basic_tucked_t-shirt`, `toigo_fisherman_sweater`; bottoms `cortu_cargo_pants`,
  `toigo_wool_pants`, `toigo_tiered_mini_skirt`; dresses `toigo_shift_dress`,
  `toigo_halter_dress_midi`; suits `toigo_female_suit`, `toigo_male_suit_3`;
  shoes `toigo_flats`, `toigo_ankle_boots_male`; hats `jujube_newsboy_cap`, `joepal_xmas_cap`;
  glasses `spamrakuen_sagerfrogs_glasses_01`, `toigo_round_glasses_leopard`.
  All go in `clothes`, including hats/glasses. `beard="wdg_scruffy_beard"` or
  `"rehmanpolanski_moustache_viking"` selects facial hair (also usable in clothes).
  Facial hair is discovered in clothes or separate beards/moustaches directories.
- Hair examples: system `ponytail01`, `bob01`, `short02`; hair01 `faydaen_hair_1`,
  `toigo_inverted_bob`, `toigo_curled_under_bob`. Skin examples:
  `toigo_light_skin_female_freckles`, `toigo_light_skin_male_ginger`;
  `skin="auto"` keeps the system age/gender/ethnicity matches. Alternatives include
  eyebrows `eyebrow001`, `eyebrow012` and eyelashes `eyelashes01`, `eyelashes04`.
- `outfit="casual"|"formal"|"sport"|"summer"|"winter"` chooses compatible installed
  top+bottom (or dress/full suit) + shoes, plus a winter hat; `seed=0` makes the choice
  repeatable for the same catalog/gender. Names/tags declaring male/female are respected;
  unmarked items are treated as unisex. Explicit `clothes` (including `[]`) overrides
  the preset. `warnings` reports unavailable categories or overlaps (two tops, suit+top,
  two shoes, etc.) without rejecting explicit combinations. Presets use name/tag style
  hints and available fallbacks, not a clothing collision solver. Hats may clip hair;
  broad skirts and extreme joint bends may intersect. Check posed Eevee views.
- MPFB proxy interpolation can leave gaps on some skeletons (e.g. 10 vertices in
  `faydaen_hair_1` on Mixamo). Only unweighted part vertices are filled from the nearest
  weighted vertex on that part (body fallback if the whole part lacks weights);
  authored nonzero weights and delete groups stay intact. `weights_repaired` reports
  counts per mesh. This does not repair intersecting geometry or clothing design.
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
beat, point, fist, thumbs_up, peace, three, four, ok, grip. Pair with arm poses, e.g. `apply_pose(rig,
"point_forward")` + `set_hand_pose(rig, "point", side="right")`; `keyframe=True, frame=N`
to animate. Mannequins from `create_human` have no fingers.

## Interactions
`interact(a, b, kind, start_frame=None, prop=None, approach=True, hold_seconds=None,
side="right")` bakes two-character contact on basic/Rigify mannequins and MPFB
game_engine/Rigify humans, including mixed heights. None appends after **both** rig
actions. Earlier body keys are retained. Contact uses world-space two-bone arm IK
and rig-aware fingers (mannequins skip fingers), with blended reach/retraction and
heads looking toward the partner.
- Kinds: `handshake` (three pumps, grip), `high_five` (raised open palms),
  `fist_bump` (knuckles), `hug` (both arms around upper back), `pat_shoulder`
  (first character's selected hand on the nearer shoulder), `handover`.
- Approach walks the second character to a height-scaled comfortable distance and
  turns both partners, using static obstacle avoidance. Only the partner is excluded
  from route obstacles to permit contact. Shoulder pats stage side by side. The first
  partner waits as needed. `moved` lists walks/turns and frames. `approach=False`
  keeps placement and rejects unreachable contact before keying. A direct route that
  would pass through the partner first walks around them (partner as an obstacle)
  before the final close step. Partners already closer than the comfortable distance
  (>= 25 cm, e.g. right after a hug) stay put instead of turning to walk away.
- Heads turn toward the partner as yaw (<= 55°, pats 70°) then pitch (-30..+22°),
  never rolled; eyes cover larger gaps. Hugs look past the partner's shoulder, and
  after a hug both take a short two-step shuffle back (~0.2 m each, 0.75 s, foot lock
  with forced contacts) to talking distance; `frames.step_back` reports it.
- For handover, first `hold_prop(a, cup, hand="right")`, then
  `interact(a, b, "handover", prop=cup)`. At contact the stepped live attachment
  switches to a bone-parented palm helper on b, preserving the prop world transform.
  Historical attachments remain evaluable on earlier frames and export as sampled
  glTF animation. Released props can be held again at/after release. One prop per hand.
- `frames` contains `approach` (range or None), `reach`, `contact`, `release`, `end`;
  `next_start_frame` chains the next performance. `hold_seconds` overrides the hold
  (0..30 s). Most reaches/retractions blend over 0.45 s; handovers use deliberate
  2 s reaches/retractions to keep prop travel continuous. `contact_error_m` measures
  palm/knuckle errors against a shared point;
  hugs, pats and handovers measure against their back/shoulder/grip sites (handover
  grips are separated for the prop). `contact_samples` gives actual/target positions.
  Hug `penetration_m` samples chest ellipsoids and arm capsules. These proxies do not
  guarantee mesh or clothing collision clearance.
- Script directions: `[Sari dan Dimas bersalaman]`, `[Dimas berjabat tangan dengan Sari]`,
  `[mereka berpelukan]`, `[Sari tos dengan Dimas]`, `[Sari memberikan buku kepada Dimas]`,
  and English shake hands/hug/high five/fist bump/hands the book to. `they`/`mereka`
  requires exactly two declared characters. Dict: `{"do":"interact", "who":"Sari",
  "with":"Dimas", "kind":"handshake"}`; optional prop/approach/hold_seconds/side.
  Script handovers create/pick up known procedural props as needed. Contacts survive
  the later speaking gesture pass. Each contact beat gets a side-on `full` two-shot
  (`<prefix>InteractNN`), same side as the active dialog camera, cutting back to the
  dialog coverage at its next shot.
- Inspect Eevee front three-quarter and side views at contact and during reach.
  Extreme proportions, tight clothing and nearby furniture may intersect; there is
  no dynamic collision, cloth or full-body contact solver.

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
See **Voices (TTS)** for automatic/selectable speech. `sound` controls Foley separately
from the `voice` speech switch.
- `auto_sfx(characters=None, kinds=None, surface="auto", volume=1.0, seed=0,
  frame_start=None, frame_end=None, clear=False)` adds original procedural Foley after
  body animation. Defaults to footsteps, sit (including stand) and ambience; add `"cloth"`
  for movement rustles, or request individual kinds. None characters selects visible rigs.
  Footsteps sample evaluated heel/ball/toe bones using `lock_feet`'s contact detector;
  already-planted feet stay silent. Step gain follows measured gait/swing speed. Sit/stand
  use saved seat-transition events, with a sustained hip-drop fallback for imported motion.
  Seat sounds include cloth and chair creak/thump; sofas are softer.
  `surface`: wood, concrete (tile alias), carpet, grass, gravel, sand, or auto (downward
  ground ray → `char3d_surface`/`c3d_surface`, material/object name → environment fallback).
  Stored environment presets choose quiet office/studio/classroom/living-room beds, street
  rumble, park chirps, cafe murmur or beach waves. Ambience loops seamlessly at about
  -30 dBFS RMS before global fades and the volume multiplier, covering the requested range.
  WAVs are deterministic 48 kHz mono 16-bit PCM, cached by SHA-256 content under
  `imports/sfx/generated/`; no external samples, downloads or network. Each step varies
  pitch, level, grain texture and onset by up to 10 ms; strip frames match touchdowns.
  Results list `counts`, `touchdowns`, and `strips` with kind, character, frame/end, path,
  hash, gain and surface. Reruns replace owned strips for selected characters/kinds in
  range; `clear=True` only removes them (all kinds if omitted). Cropped ambience edits
  retain the portions outside the range. Voice/music/manual sfx are preserved; `duck_music`
  ignores generated sfx. Scene range/current frame and character animation are preserved.
  Imported contacts and hip-drop inference are heuristic: crouches can resemble sitting;
  initial contacts are intentionally silent. Static walkable geometry only; no acoustic
  propagation, shoe/material simulation or collision solver. Rerun after editing motion.
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
  `tts = text_to_speech("Selamat datang!", engine="piper", language="id")` →
  `lip_sync_audio(rig, tts.path, text="Selamat datang!", timing="text", language="id")` → `set_expression(rig, "smile", 0.45, frame=1,
  keyframe=True)` → `set_lighting("studio")` → `camera_shot(shot="close_up",
  move="push_in")` → `auto_blink(rig)` → `talk_motion(rig)` → `talk_gestures(rig)` →
  `add_subtitles()` (optional captions) → `render_video` (use `shot="medium"` when gestures
  should be seen).
- `transcribe_audio` gives text + word times without animating.

## Voices (TTS)
`scripts/install_tts.sh` installs Piper + Edge packages and the Indonesian Piper voice.
Select only one with `scripts/install_tts.sh piper` / `scripts/install_tts.sh edge`.
Models live in `~/.local/share/char3d/tts/` (override `CHAR3D_TTS_DIR`); the installer
verifies recorded byte sizes and SHA-256 in `scripts/tts_voices.tsv` and reuses cached
files. Tools never download models. Missing models report the exact install command.

- **piper** (default): offline CPU. Runtime piper-tts 1.8 is GPL-3.0. The
  [news_tts model card](https://huggingface.co/rhasspy/piper-voices/blob/main/id/id_ID/news_tts/medium/MODEL_CARD)
  belongs to an MIT-labelled repository but its dataset link is unclear; treat this
  Indonesian voice as **personal use**, pending clarification. One Indonesian speaker
  exists (median F0 ~257 Hz, female). Casting shifts it to a typical speaking F0 for
  the character's gender/age (adult men ~125 Hz, older men ~115 Hz, women ~215 Hz,
  children ~270 Hz; seed adds ±0.6 semitone) with numpy TD-PSOLA, plus a formant shift
  of ~28% of the pitch shift (≤3.5 semitones) so men also get a longer vocal tract.
  These are signal transforms of one speaker, not separately trained voices; deep male
  shifts stay intelligible (Whisper round-trips) but sound less natural than Edge.
  Rate uses Piper `length_scale`; pitch shifting preserves its duration. Other Piper `.onnx` +
  `.onnx.json` pairs can be placed under `tts/piper/`; multi-speaker IDs use `#speaker`.
- **edge**: online, explicit only. `edge:id-ID-ArdiNeural` / `edge:id-ID-GadisNeural`
  supply Indonesian male/female voices; `list_voices(engine="edge")` refreshes other
  languages with a static fallback. **Text goes to Microsoft**. This is an unofficial
  API that can change or fail; edge-tts is LGPL-3.0. No offline engine ever falls back
  to Edge. Online results include a `privacy` note, including cache hits.
- **f5**: optional local cloning; **not installed by default**. `scripts/install_tts.sh
  f5 --yes` prints the size/license before installing a large CPU PyTorch environment
  (roughly 3 GB), >=1.35 GB Indonesian checkpoint, vocabulary and vocoder. The
  [Indonesian fine-tune](https://huggingface.co/anantoj/f5-id-v1) is Apache-2.0, while
  [upstream base weights](https://github.com/SWivid/F5-TTS#license) are CC-BY-NC
  (**non-commercial**). Dependencies are separate in `requirements-f5.txt`; use a
  Python/PyTorch version supported by F5 if the current interpreter has no wheels.
  Register `tts/f5/voices/Ana.json` with `{"voice_reference":"my_voice.wav",
  "reference_text":"Exact reference transcript", "language":"id", "gender":"female"}`.
  Relative references resolve beside that JSON. Use only the user's own voice or a
  voice they have permission to use. All model/vocoder files and transcripts must
  exist locally; inference does not auto-download a model or ASR weights.
- **chatterbox**: explicit online wrapper of the existing free Hugging Face Space
  (MIT, tiny GPU quota, may queue/fail, **no Indonesian**). Use `chatterbox:ms` only
  when Malay is acceptable. Text is sent to Hugging Face/ResembleAI. The existing
  `ai_text_to_speech` job API remains unchanged.

`list_voices(language="id")` reports installed engines, licenses, privacy, install hints
and voices. The default catalog and all casting are offline; explicitly requesting
`engine="edge"` refreshes its list. `text_to_speech(text, voice=None, engine="piper",
language="id", rate=1.0, pitch=0.0, gender=None, output=None)` returns `path` relative to
`imports/`, `duration_s`, `engine`, `voice`, `cached`, and online `privacy`. `rate` is a
0.5..2 multiplier; `pitch` is -12..12 semitones relative to the raw voice. `output`
optionally copies the cached WAV to another `.wav` path inside `imports/`.
All engines normalize to 48 kHz mono 16-bit PCM, target active RMS ~-18.4 dBFS with
a -1 dBFS peak ceiling, short fades and 40 ms silence pads. Peak limiting can reduce
RMS for high-crest audio. Cache keys cover engine/version/model, voice, exact text,
language, rate, pitch and DSP version under `imports/audio/tts/`.

`script_to_scene(..., voice=True, tts_engine="piper")` casts deterministically per
character from gender, age and seed. Explicit `voice`/`pitch`/`rate` override the
profile. Text: `ANA (perempuan, 28, suara: edge:id-ID-GadisNeural): Halo!` or English
`voice: ...`; `suara berat` / `suara tinggi` (deep/high voice) shift the cast pitch by
-3 / +3 semitones (`pitch_offset`); an explicit `pitch` replaces the cast pitch. Dict:
`{"id":"Ana", "gender":0, "voice":"piper:id_ID-news_tts-medium", "pitch":1, "rate":1.05}`.
Both script and dialog also accept `voices={"Ana": {"voice":"edge:id-ID-GadisNeural",
"pitch":1, "rate":1.05}}`; dialog keys are rig/speaker names and may include age/gender.
`build=False` reports `voices` with engine/voice/pitch/rate/online without synthesis,
audio reads or network. Builds report `generated_files`, `cache_hits`, `timings.tts`.
Existing recorded audio takes priority. Missing/failed TTS warns and keeps mouth motion;
no build fails solely for missing TTS, and no other backend is tried implicitly.
Generated text uses voiced-interval word timing (not acoustic forced alignment), so
captions, expressions, gestures, listeners and music ducking share the speech timeline.
The web UI asks for consent before sending text online and can play cached WAVs.

## Dialog (2–4 characters)
`dialog(lines, ...)` performs a whole conversation in one call. `lines =
[{"speaker": "Ana_rig", "audio": "audio/a1.wav"}, {"speaker": "Budi_rig", "text": "..."}]`
(audio = real voice with Whisper timing and sound on the timeline; text = mouth only
by default, or real synthesized speech with `voice=True, tts_engine="piper"`;
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
  speaker (`shot` size) cut 4 frames before they speak, on the same side of the live
  head-to-head action line (initially -Y; 180° rule);
  `singles`, `two_shot`, `none` (then frame it yourself with `camera_shot`).
Gaze samples the live posed head of each target at every keyed frame, including
pelvis turns and seated height. Targets beyond 70° also receive a small chest turn
(up to 45°); root/legs stay intact. Dialog opens heads 18° toward the camera side
(35° on the opening line for establishing coverage) so both faces fit a two-shot;
eyes track the remaining angle. Singles are baked
after this performance, from the actual face direction beside the current eyeline,
following moves and keeping the same side of the current head-to-head action line.
Run body clips (animate, walk) BEFORE `dialog` (it keys head/eyes/arms on top); add
`add_subtitles()` afterwards for captions of every speaker. `talk_motion(look_at=...,
listen_to=...)` exposes the same gaze/listening for hand-made scenes. Check with
`render_frames([...], camera="scene", engine_name="eevee")` at a frame inside each line.
- `body_language=True` optionally adds emotion-aware torso/shoulder/head movement under
  speech gestures, including subtle sad/surprised listener reactions. `dialog` defaults
  to False; `script_to_scene` defaults to True. Explicit line `emotion` wins; otherwise
  the local sentence-emotion matcher supplies it. Routes and seated legs are preserved.
- Whisper model: `tiny` by default (~75 MB, downloaded once). Set
  `CHAR3D_WHISPER_MODEL=base` or `small` for harder audio (accents, noise).

## Script → scene
`script_to_scene(script, name=None, environment=None, lighting="studio", camera="mixed",
subtitles=True, language="auto", seed=0, build=True, sound=True, body_language=True, voice=True,
tts_engine="piper", voices=None, look=None)` composes the existing tools into
a complete scene for 1–4 characters. `build=False` returns a deterministic normalized
`plan` (characters, beats with `estimated_frames`, warnings) without changing the scene,
reading audio or transcribing it. Frame estimates use the current scene fps; walking
and audio estimates are approximate. `seed` selects default outfits and procedural motion.

`look="golden_hour"` or a `SUASANA:` / `LOOK:` / `MOOD:` header applies atmosphere
**after** lighting, cameras and weather. `look` accepts a preset string or the
`cinematic_look` options dict. Explicit arguments override headers; `"none"` opts out.
`build=False` reports the resolved `plan.look` without any effects. No look/header
keeps the existing rendering behavior and cost; `plan.recommended_look` only suggests
`golden_hour` outdoors or `studio_film` indoors.

The text format accepts Indonesian and English:
```text
JUDUL: Pagi di Studio
LOKASI: podcast_studio
ANA (perempuan, 28, rambut bob): Halo semuanya, selamat datang!
BUDI (laki-laki, 35, rambut pendek, kasual): Terima kasih, Ana.
[Budi duduk di kursi]
[Ana melambai]
ANA: Apa kabar hari ini?
```
`TITLE`/`LOCATION` are aliases. Declare speakers with `NAME (descriptors): text`;
later lines can use `NAME: text`. Names/references match without case sensitivity.

Outdoor locations accept jalan/jalan kota/street → city_street, taman/park → park,
kafe/cafe → cafe_terrace, pantai/beach → beach. Optional `CUACA:` / `WEATHER:` accepts
hujan/rain, salju/snow, kabut/fog, berangin/wind, cerah/clear (also dict `weather`).
Weather is applied after final cameras/lighting, before hair/cloth baking. Parse-only
reports it without changing the scene; scripts without weather keep the old plan format.

Descriptors recognize gender, age, hair (bob, short/pendek, long/panjang, ponytail/ekor
kuda, braid/kepang, afro), outfits, facial hair, accessories or exact MPFB catalog names.
Outfit descriptors: kasual/casual; formal/jas/resmi/elegant; olahraga/sport;
musim panas/summer; musim dingin/winter/jaket/coat. Gaun/dress/rok/skirt selects
summer for females. A literal `suit` still selects the system elegant suit.
Jenggot/brewok/beard/kumis/moustache requests a deterministic installed beard or
moustache; kacamata/glasses and topi/hat select installed accessories.
Dict characters accept `outfit="casual"|"formal"|"sport"|"summer"|"winter"`,
`beard="catalog_name"` or `beard=True`, and `accessories=["glasses", "hat"]`.
Without explicit `clothes`, an outfit uses the installed picker, seeded with
`seed + character_index * 101` (zero-based). Explicit `clothes`, including `[]`,
overrides it. Pack hair/clothes names are preserved in parse-only plans as
unverified, then checked against `mpfb_assets()` during building. Exact text pack
names are deferred in the plan's `assets` list until their type is known.
Missing optional items produce warnings; outfits fall back to installed system suits.
Unknown descriptor words and stage directions produce warnings, not guesses.
Directions: `[Budi walks to 1, -1]`, `[Budi jalan ke kursi]`, `[Budi sits on the chair]`,
`[Budi berdiri]`, `[Ana holds a cup in the left hand]`, `[Ana menunjuk]`,
`[Ana melihat Budi]`, `[pause 1 second]` (or `[jeda 1 detik]`).

Motion directions also accept `[Ana menangis]`, `[Budi tertawa]`, `[Ana sedih]`,
`[Budi marah]`, `[Ana gugup]`, `[Ana berjoget]` / `[Ana menari tradisional]`,
`[Budi berlutut]`, `[Ana berbaring]`, `[Budi bangun]`, `[Ana duduk di lantai]`,
`[Ana mengetik]`, `[Budi minum]`, `[Ana menelepon]`, `[Budi membaca buku]`,
`[Ana mengangkat bahu]`, `[Budi bertepuk tangan]`, `[Ana membungkuk]` and
`[Budi meninju Ana]`, with English equivalents. Required cups/phones/books are
created and held through `hold_prop`; typing adds a seat and nearby desk/laptop when
needed. A directed
punch turns toward its partner and times a stylized recoil; it is not contact IK.
Dict `gesture` beats accept `bpm`, `cycles`, `speed`, `amplitude`, and kneel `phase`.
Unknown directions still warn. Explicit motion beats retain their arms/head through
the later dialog layers. Use `body_language=False` to disable inferred body emotion.

For explicit control, use a dict:
```python
script = {"title": "Morning", "environment": "office",
          "characters": [{"id": "Ana", "gender": 0, "age": 28, "hair": "bob01"},
                         {"id": "Budi", "gender": 1, "race": {"asian": 1}}],
          "beats": [{"say": "Ana", "text": "Selamat pagi!", "emotion": "happy"},
                    {"do": "walk", "who": "Budi", "to": [0.85, 0]},
                    {"do": "sit", "who": "Budi", "on": "chair"},
                    {"say": "Budi", "text": "Terima kasih."}]}
```
Speech can include `audio="audio/line.wav"` (relative to imports/). The MCP process
uses local Whisper when available; otherwise supplied text follows voiced intervals,
or audio-only mouth motion is used. Text alone synthesizes speech when the chosen TTS
is installed (`voice=True` by default); otherwise a warning preserves mouth motion.
Use `voice=False` for silent text animation. `sound=True` separately adds procedural
effects and ambience. See **Voices (TTS)** for casting, per-character overrides and privacy.
Without word times, captions are disabled with a warning; silent cast members keep
their base expression and listener motion without requiring their own speech.
Other dict beats: `stand`, `hold` (`prop`, `hand`), `gesture`/`pose` (`name` from the
clip/pose library), `look` (`at` character/object/camera or XY/XYZ), `pause` (`seconds`),
and `{"title": "Later", "subtitle": "...", "seconds": 2}`.

Body beats chain on one timeline before speech and expressions; blinks, gaze and
gestures are baked before final dialog coverage. Explicit camera glances sample
provisional cameras, replaced by final coverage afterwards. Lighting samples the
final body motion, then hair and loose clothing are baked last. Skirts/dresses get cloth motion automatically; tight garments
and short hair are skipped normally, including characters with no eligible parts.
Speech after a walk/sit waits for the action's end. Staging uses `stage_dialog`; generic
seat names pick a free environment seat or add a chair. Generic seats that hide
the sitter behind a peer from the main camera side, or
face over 90° away from the nearest peer, are replaced with a guest chair on clear
conversation floor facing the peer. Placement checks furniture/character footprints
and a reachable approach. Builds report the choice in `warnings` and
`plan.guest_chairs`; parse-only plans do not inspect or place scene furniture.
Exact seat object names are always honored, with gaze/cameras adapting instead.
Other known prop kinds are created as needed. MPFB missing uses rigged
mannequins, with timing/audio/captions and gestures but no face, hair or clothes.
The result includes `characters` (id → `{rig, mesh, realistic}`), actual beat `frames`,
`lines`, `shots`, `duration_s`, `warnings`, and `timings` in seconds. `camera="none"`
creates one wide camera so the scene is still renderable, without dialog cuts.
Existing objects are retained; character names are made unique. Environment selection
replaces the managed set as usual. Nothing is saved, exported or rendered automatically.
`sound=True` runs `auto_sfx` for this cast after animation, adding footsteps, sit/stand
and ambience; `sound=False` skips generation. Results include `sfx.counts` and strip
paths/times/hashes. Parse-only mode never writes sound files or changes the timeline.

Recipe: `new_scene()` → `script_to_scene(script, build=False)` →
`script_to_scene(script, language="id")` →
`render_frames([line.start + 5, ...], camera="scene", engine_name="eevee", size=512)` →
inspect the frames → `save_project("morning.blend")` → `render_video(quality="draft", wait=True)`.
Limits inherit the component tools: no obstacle/desk/arm collision avoidance, static
seats, one held prop per hand, rule-based text pronunciation and approximate text/audio alignment.
Outfit/accessory selection does not solve garment/hair/seat intersections; inspect posed Eevee frames.
Declare characters before using them; invalid references fail with a clear error.

## Sutradara AI (idea → script)
`director_status()` reports offline/API/Claude Code availability, configured yes/no,
model, privacy and billing, without a request or Blender. `direct_scene(idea,
generator="auto", language="id", duration_s=30, characters=None, style=None,
look=None, location=None, seed=0, consent=False)` returns a detailed Markdown
`brief`, editable text `script`, character metadata, parse-only `plan`, warnings
and suggested `build_options`. It never builds, renders or starts Blender.
**Agents should prefer writing scripts themselves**; this tool is for the web UI
and quick drafts. Then edit → `script_to_scene(..., build=False)` → build as usual.

- `offline`: free, local keyword/scenario rules (Indonesian + English input),
  deterministic by seed; 1–4 characters, indoor/outdoor sets, all looks/weather,
  relations/age/gender and seeded dialogue. It uses templates, not a language model;
  review how well the draft matches the idea. `language="ms"` warns that offline
  dialogue uses Indonesian templates. English drafts need a local English TTS voice.
- `claude_cli`: online via Claude Code and the owner's Claude subscription,
  personal use. Requires `consent=True`; uses subscription quota, no char3d per-call
  USD charge. Discovery: `CHAR3D_CLAUDE_BIN` → PATH → newest Desktop bundled CLI at
  `~/.config/Claude/claude-code/<version>/<hash>/claude`. Status checks existence,
  not login. If needed, run `claude` once in a terminal and log in (use the discovered
  full path if it is not on PATH). Headless generation has no tools, strict empty
  MCP config, safe mode, no persistence, temporary empty cwd, stdin prompt, 5 min
  timeout; it never launches the char3d MCP server recursively. API credential env
  vars are removed from this subprocess so this route uses subscription auth.
- `claude`: online paid Anthropic Messages API; requires `consent=True` and local
  SDK credentials (env API key/auth token or SDK profiles). Put `ANTHROPIC_API_KEY=...`
  in `~/.config/char3d/env`, then restart MCP/UI; launchers already source it.
  Never log, persist, return or display credentials. Default `claude-opus-5-5`,
  override `CHAR3D_DIRECTOR_MODEL`; adaptive thinking stays on, effort defaults to
  medium (`CHAR3D_DIRECTOR_EFFORT`). SDK 2.10 structured JSON + cached stable system
  prompt + server-side default refusal fallbacks. No temperature or token thinking
  budget. Maximum output 16000 tokens/request, 180 s timeout, no automatic retries.
  `usage`/`cost_usd_estimate` include the optional repair. Opus 5.5 list prices:
  input $4/output $20 per MTok, cache write 5m $5/read $0.20 per MTok. Typical drafts
  roughly $0.05–$0.25; one full 16000-token output is $0.32 plus input, and repair
  can double requests. Model overrides still use this labelled Opus estimate;
  actual account pricing may differ. [Official pricing](https://platform.claude.com/docs/en/about-claude/pricing).
- `auto`: CLI first when available **and consent=True**, then configured API with
  consent, otherwise offline with a note. Explicit online without consent is
  rejected. Online failure/refusal/truncation falls back to offline with a visible
  warning; it never switches from failed CLI to paid API. `requested_generator`
  retains the attempted service and `privacy` states the transmission to Anthropic.

All generated scripts are checked by `engine.script_plan.parse_script` without
Blender. Online drafts with parser errors/unknown directions/descriptors get one
repair round; unresolved errors produce a valid offline draft, unresolved parser
warnings remain visible. Network/subprocess work stays in `providers/director/`,
with a small registry like TTS. No network code goes in `engine/`.

The brief includes logline, mood, look/palette/light, weather/dressing, cast/outfit/
voice, blocking, timed shot suggestions, pacing and sound/music mood. Text builds
only supported headers, dialogue and directions. Detailed shot moves, costume
colors, extra dressing and music remain manual art direction; scripts use standard
mixed coverage, local Piper voice hints and installed seeded outfits. Runtime is
approximate. Cinematic look, collision and TTS limits above still apply.

Studio's **Sutradara AI** panel above the script editor offers examples/options,
explicit Anthropic consent with API estimate or subscription quota, progress,
**Prompt sutradara** / **Naskah char3d** tabs, copy/apply and recoverable previous
editor text/settings. Director jobs run outside the Blender queue/lock. The HTTP
adapter also requires `confirm_external=True` for an online request.

Verify: `.venv/bin/python tests/test_director.py` (prints `DIRECTOR UNIT OK`, no
network/Blender), `tests/test_webui.py`, `tests/test_tts.py`, `tests/test_cinematic.py`,
`tests/test_phonemes.py`. Real UI smoke: `CHAR3D_PORT=9989 CHAR3D_WORKSPACE="$PWD/output"
.venv/bin/python tests/webui_smoke.py --ui-port 8789`. Real offline pipeline:
`CHAR3D_PORT=9989 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python tests/director_e2e.py`.
With UI on 8789, `node tests/director_ui.cjs` captures dark/light desktop/mobile
states in `output/director_screens/`. Keep 9876 untouched; stop isolated test servers.

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
### Extended motion scores
`list_animations()` reports category, duration at 24 fps, looping, description,
`required_props`, `required_seat`, and dance beats. All entries below are also poses.

| category | clips |
|---|---|
| body language (loops) | sad, angry, nervous, happy, excited, tired, confident, shy, bored |
| reactions (one shot) | laugh, cry, shrug, startle, surprised, facepalm, thinking, sigh, clap, bow, nod_agree, disagree, point, beckon, cover_mouth, arms_crossed |
| everyday actions | kneel, lie_down, get_up, sit_floor, type, drink, eat, phone_call, read_book, look_around, stretch, pick_up |
| dance (loops, four beats) | dance_casual, dance_energetic, dance_traditional |
| stylized fight (one shot) | punch, kick, block, dodge, hit_react, fall_down |

`animate(rig, "dance_casual", bpm=90, cycles=2)` synchronizes four-beat phrases to
30..240 BPM (default dance period is 64 frames at 24 fps). `speed` multiplies cadence.
`kneel` supports `phase="full"` (down/hold/up), `"down"`, `"hold"`, `"up"`.
`lie_down`/`sit_floor`/`fall_down` end on the floor; `get_up` reverses the floor transition.
Grounding measures evaluated skin/clothing. Typing requires `sit_on` and preserves its
lower body; nearby laptop/desk geometry supplies hand targets. `drink`, `phone_call`,
`read_book` require a held native `add_prop` cup/phone/book, in either hand. Existing grip constraints keep
the cup upright and fingers wrapped. `eat` is pantomime; `pick_up` reaches without attaching
an object. Dance uses explicit stepped contacts with foot IK.
Hand contacts are corrected after palm orientation; MPFB teeth, lashes and brows calibrate
mouth/eye/forehead targets (mannequins use proportional face locations). Dance rounds its
whole phrase once to avoid accumulated BPM drift; `cycle_frames_exact` reports its period.
`clear_animation` removes action/NLA animation while preserving structural rig drivers;
new motions select FK controls on Rigify before solving contacts.
There is no collision/cloth solver; large skirts, extreme builds and furniture can still
intersect. Traditional dance is an
original general hand-led phrase, not a reconstruction of a named regional tradition.

### Core animation and navigation
Works on **any humanoid rig**: char3d `basic`, char3d `rigify`, and imported skeletons
with common naming (Mixamo `mixamorig:LeftArm`, CMU BVH `LeftUpLeg`, Unreal `thigh_l`,
...). Non-basic rigs are driven through a hidden proportion-matched basic rig and a
world-space retarget, so the same pose/clip looks the same everywhere. Rigs whose rest
pose has bent elbows (MPFB/MakeHuman rest with forearms ~45° forward) are normalised to a
straight A-pose arm first, so `relaxed`/walk arms hang at the sides on every rig.
Rigs may be moved, turned or uniformly scaled with `transform_object` at any time:
stored build landmarks are re-fitted to the current joints, proxies are authored
facing the char3d front, and the motion is turned back to the rig's heading, so clips
look the same and `walk` advances along the character's facing (any yaw, e.g. 35°).

- `apply_pose(armature, pose)` — library: rest, t_pose, relaxed, wave, cheer,
  point_forward, hands_on_hips, thinking, crouch, sit, fight_stance, run_pose.
  `keyframe=True, frame=N` to build pose-to-pose animation.
- `animate(armature, clip, start_frame, cycles, speed, amplitude, in_place)` — clips:
  idle (96 f), walk (32 f/cycle, moves forward −Y), run (18 f), wave (36 f),
  cheer (30 f), jump (40 f, one-shot), nod, head_shake (30 f). 24 fps.
  **Chain** clips with `start_frame = previous["next_start_frame"]`.
- **Floor routes and turns** — `walk_path(armature, points, clip="walk", start_frame=None,
  speed=1.0, face_end=None, avoid="auto", ignore=None)` walks/runs from the current position through absolute world
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
  static obstacle avoidance is described below; feet use flat contacts rather than heel/toe rolls.
  Calls are limited to 1000 targets / 24000 frames; split longer routes and chain them.
- **Static obstacle avoidance** — `walk_path(..., avoid="auto", ignore=None)` snapshots
  evaluated visible mesh footprints at the start frame, including furniture and other
  characters. A 5 cm, eight-connected A* grid inflates obstacles by evaluated
  shoulder/hip radius plus 5 cm clearance; line-of-sight shortcuts feed the existing
  route/terrain/footstep code. Unsafe curve corners use stepping turns. `"auto"`/`True`
  only change intersecting routes; a clear route retains exactly the old keys.
  `avoid=False` preserves the old route. `turn_to` accepts the same options and checks
  the stationary body envelope without moving the root.
  - Ground, invisible/helper geometry, the walking rig/its descendants and actively
    held props are excluded. Only the local ankle-to-head slice (0.05..1.7 m) counts.
    Walkable tops stay free; adjacent terrain height jumps over 0.25 m form obstacles.
  - `ignore=["Env_chair"]` excludes the named object and descendants, for example when
    approaching a chair before `sit_on`. Use the actual root returned by `add_prop`.
    XY targets remain numeric; there is no automatic seat-object target resolution.
  - Blocked targets move to the nearest free cell with `warnings`. A start inside the
    clearance margin (e.g. staged behind a desk) first steps straight out to the nearest
    free cell (<= 0.6 m, with a warning). Starts deeper inside obstacles or
    unreachable targets raise before baking (including in `"auto"` mode). The search
    extends 3..10 m beyond the route and is limited to one million cells; split very
    large routes. Existing animation is preserved on planning errors.
  - Results add `avoided`, `detours` (rerouted user segments), `path_points` (including
    start), `body_radius_m`, `clearance_m` (minimum sampled root distance to raw mesh
    footprints/terrain edges), `planning_seconds`, and `warnings`. Clearance is null
    without obstacles or with avoidance disabled. Curved-only corrections count as a
    detour too. Obstacles are conservative convex slices per evaluated mesh, static at
    start; this does not solve moving-character, hand, foot, or arbitrary limb collisions.
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

## Secondary hair & cloth motion
`secondary_motion(character, parts=["hair"], frame_start=None, frame_end=None,
stiffness=0.5, damping=0.5, gravity=1.0, wind=None, clear=False)` bakes spring motion
onto extra deform bones. Run it **last**, after body clips, routes, mocap and talk_motion;
rerun after changing those animations. Range defaults to the scene (inclusive); include
~1 s after the body stops for settling. Existing body/face keys are preserved.
- Ponytail/braid: one four-bone chain; long/bob: up to five geometry-derived chains.
  Hair vertices below the attachment blend from head to chain bones; scalp and other
  meshes keep their weights. MPFB game_engine/Rigify and basic/Rigify mannequin rigs
  with a skinned mesh named/grouped with a hair hint are supported. Short/afro and
  missing/insufficiently long hair are reported in `skipped`.
- `parts=["hair", "clothes"]` adds eligible garments; use a garment's exact object or
  asset name to bake/clear only that garment. Geometry below the hips and farther
  than the tight-fit threshold from the legs identifies loose hems. Tight trousers,
  shirts, footwear (nothing near the waist) and short/missing loose regions are
  reported in `skipped` without chains.
- Skirts, dresses and below-waist jacket/coat tails get up to 12 angular chains of
  four `cloth_XX_YY` bones. Only connected loose garment regions are reweighted;
  the top blends from the original hip/thigh weights, and body/other garments stay
  intact. Finalize topology before setup. Open coats keep gaps in their chain ring.
- Bones `hair_XX_YY` and `cloth_XX_YY` are reused, deform enabled, in the hidden
  `Secondary motion` bone collection. Normal glTF/FBX export includes their baked rotations:
  `export_asset("hair.glb", objects=["Maya_rig"], max_influences=4)`.
- `stiffness` / `damping` are 0..1; higher values return to the groom faster / reduce
  oscillation. `gravity` >= 0 is an elastic style control (reduced effective gravity
  preserves the authored groom). `wind=[x,y,z]` is constant world-space acceleration.
  Results include `bake_seconds`, tip offsets and sampled collider clearance in meters.
  `garments` lists each simulated object, chain count, bones and the same metrics;
  garment tip offsets measure lag from the collision-constrained elastic drape.
  This lets a skirt settle over a held bent leg instead of measuring that static
  drape as perpetual motion.
- Reruns replace only owned keys in the requested range. `clear=True` removes them
  (partial clears hold identity inside the range); reusable bones/weights remain.
  Geometry/topology should be finalized before the first bake.
- Cloth uses conservative body-fitted thigh/shin capsules and outward enclosure
  constraints (a stepping leg stays inside the skirt), with adjacent tip spacing
  constraints. Horizontal thighs bend the front/side target drape over the lap.
  Run `sit_on` before baking; inspect a side render of the seated hem.
- Limits: these are short elastic skin chains, not material-accurate fabric.
  Head/neck/shoulder/back capsules are conservative proxies fitted inside the rest
  groom. Collisions constrain chain centers with thickness at sampled segment points,
  not every surface vertex; no exact body-mesh, arm, seat/prop or full self-collision. Extreme
  poses, existing mesh intersections and very wide hair cards can still clip. Bakes
  start at rest at the range start, so a partial bake can change continuity there.
  Uniform rig scale, translation and rotation are supported; nonuniform scaling/shear
  is not modeled as physical hair/cloth. At most 24000 frames per call.
- Check the rest shape and moving side view with `render_frames(..., view="right")`;
  save the project after baking. Example: `animate("Maya_rig", "run", cycles=3)` →
  `secondary_motion("Maya_rig", frame_end=100)` → `render_frames([2, 8, 25, 78],
  objects=["Maya_rig"], view="right", size=512)`.
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
  Speed and cadence adapt locally: level ground/platforms keep natural travel speed,
  ramps slow with slope, and only stairs use tread-limited, quicker short walking steps.
  `clip="run"` runs on level ground/ramps and blends to walking around stairs. Speed
  transitions are smooth; finishing turns/gathering use their own cadence. The result
  reports `terrain.gait` (`walk`, `run` or `run/walk`) and bake seconds. Flat scenes
  without walkable meshes retain the existing gait and keys.
- `lock_feet(rig, terrain=True)` (default) detects contacts relative to local ground and
  pitches/locks the sole on slopes. `terrain=False` uses only `floor`. Automatic foot lock
  in `animate`/mocap also queries terrain, but does not plan root elevation or safe treads:
  use `walk_path` for stairs. Run foot lock after body animation, before speaking layers.
- Results include `ground_heights` per contact, `max_penetration_m` and
  `min_swing_clearance_m` in meters, measured at heel/ball/toe sole landmarks. Swing
  clearance excludes the two frames adjacent to liftoff/touchdown (clearance approaches
  zero there); penetration includes every frame. These are skeletal sole measurements,
  not collision checks on every deformed shoe vertex.
- Limits: no jumping between levels; obstacle planning blocks height jumps over 0.25 m. Use rises <=0.20 m for
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
  microphone, laptop, plant, lamp, screen, bookshelf, sofa, whiteboard, bench, stool,
  cup, phone, book or handheld_microphone. Units are meters,
  rotation_z is degrees (0 faces -Y); scale is independent of characters. Location is the
  floor/base center: desk height 1.02 m, coffee table 0.43 m; put microphones/laptops at
  desktop Z. Optional screen_image works here too. Move the returned root to move all parts.
- Practical lights survive `set_lighting`; `clear_environment()` removes only owned
  furniture/lights and unused owned data, preserving characters, cameras and lighting rigs.
  Set calls replace prior sets/props. The central -Y camera path is open; backdrops are
  open at the front/sides/top, designed for frontal medium/wide shots. Static furniture
  does not follow walking characters or solve hands/desk collisions or arbitrary
  camera orbits. Use explicit character subjects for lighting and camera framing.
- Recipe: `set_environment("podcast_studio", subject=["Maya_rig"])` →
  `set_lighting("studio", subject=["Maya_rig"])` →
  `camera_shot(subject=["Maya_rig"], shot="wide", angle=8)` →
  `render_frames([1], camera="scene", engine_name="eevee")`. Inspect the result.

**Sitting & holding** — `sit_on(character, seat, start_frame=None, transition_frames=20,
seat_index=0, hands="thighs")` seats basic, Rigify and MPFB characters on furniture roots
or any of their parts. Chair/sofa/bench/stool builders store local seat centers, surface,
front and floor metadata, so moved/rotated/scaled furniture works. Sofa and bench have
two positions (`seat_index=0/1`, sofa cushion top 0.46 m); an unmarked mesh uses its
highest surface and index 0. Set roots enumerate their seat positions too.
- Buttock contact is measured on the evaluated body/clothes; shared two-bone IK plants
  flat feet. The character turns toward the seat front and blends back/down from the
  current pose, then holds through scene end. None appends after the rig's action.
  `hands`: thighs, lap, armrests (requires seat metadata), none (keeps arm posture).
  Layer `talk_motion`, `talk_gestures` and `set_hand_pose` afterwards; hips/legs stay seated.
  `stand_up(character, start_frame=None, transition_frames=20)` stands in front of the
  saved seat. Results report frames, contact error, IK error and baking time.
- `add_prop("cup"/"phone"/"book"/"handheld_microphone")` makes original low-poly props
  in real-world sizes, with their origin at the grip. Omit location to spawn at the most
  recently created visible rig's right palm (origin if there is no rig).
  `hold_prop(character, prop, hand="right", start_frame=None, end_frame=None, grip="auto", upright=None)`
  places the grip in the palm and poses fingers. Left/right work; mannequins have no
  fingers. None start uses the current frame; None end keeps the attachment live, including
  arm animation added later; an end frame releases on the following frame.
- `upright=None` automatically levels cups against world +Z and gives handheld microphones
  a 12° lean toward the palm/mouth. Phone/book and other kinds keep the rigid grip;
  `True` opts in, `False` opts out. A live wrist constraint layer levels the palm frame
  while keeping its yaw, instead of moving the grip away from the hand. Finger constraints
  keep the chosen grip over later `talk_gestures`/`set_hand_pose`; release restores the
  underlying wrist/finger animation. Body keys stay intact. Cup handles leave space for
  curled fingers and the wrist; check front and side close-ups.
- `release_prop(character, prop, frame, place_at=None)` keeps the release world transform,
  or places the grip at world XYZ. It remains static, without gravity. Blender keeps a
  keyed live constraint; export temporarily samples world transforms each frame, including
  release, then restores scene actions/constraints. Exporting the character includes its
  held props; glTF receives transform animation, not a constraint or physics simulation.
- Limits: static level seats and one flat floor; mesh fallback uses the highest vertices
  (not arbitrary concave seats). No obstacle, clothing, armrest/desk collision or automatic
  seat occupancy solving. Very high/low seats can exceed limb reach. Prop pickup/release
  intervals must be sequential; a new hold can start at/after the previous release. Use one held
  prop per hand at a time. Upright holds own wrist roll/flex; extreme arm poses can require
  a pronounced wrist bend or still intersect the body/prop. There is no arm/prop collision
  solver or automatic elbow lift; choose a suitable arm pose for drinking/raised microphones.

## Weather
`set_weather(kind="clear", intensity=0.5, wind=None, seed=0)` replaces owned weather.
- `rain` creates looping streaks, dims/desaturates the outdoor sky and lowers managed
  ground roughness. `snow` creates slowly drifting low-poly flakes. Both use one
  geometry-node modifier with deterministic seeded instances and saved Scene Time
  animation, visible in Eevee/workbench and separate-process draft/preview video.
- `fog` is a bounded low-density scattering volume in Eevee, with exponential distance
  attenuation; workbench does not render volumetric fog. `wind` sets wind only.
- `wind` is a world-space XYZ acceleration in m/s², bounded to ±100 per component.
  Omitted wind chooses a gentle drift (stronger for wind weather). `secondary_motion`
  uses this value when its own wind is omitted; explicit wind overrides it. Rebake
  secondary motion after changing weather. Existing bakes are not modified automatically.
- Particle/fog coverage is the union of all shot cameras' near frusta (24 m depth),
  sampled over camera travel. It refreshes on still rendering, save_project and video
  snapshot creation. Set cameras before weather; distant scenery stays precipitation-free.
  Counts are capped at 2,200 rain streaks / 1,200 flakes, independent of world size;
  very dispersed shots spread this budget thinly. No particle collisions, accumulation,
  splashes or fluid simulation. Wind drifts particles, without a gust simulation.
- `clear` removes owned meshes/modifiers/materials/node groups and restores ground
  roughness, sky and sun; it preserves characters, cameras and user materials. Replacing
  or clearing an outdoor environment also clears its weather and restores the prior world.

**Outdoor sets** — `set_environment("city_street"|"park"|"cafe_terrace"|"beach")`
uses the existing subject-foot anchoring, height scaling, variant seed and theme rules.
Original low-poly streets/facades/car, park trees/paths, cafe furniture/awning and
beach/palms/waves extend at least 30 m behind the cast; ground extends hundreds of
meters at adult scale for wide/drone shots. Ground has `char3d_walkable` tags, furniture
is visible to static obstacle avoidance, and bench/cafe/deck-chair seats support sit_on.
Deck chairs have level pads and slightly reclined backs; sit_on uses its standard upright
seated pose. The sea has gentle static procedural waves, without water physics.
Outdoor sets install a procedural horizon-to-zenith world gradient and one SUN.
`set_lighting("noon"|"sunset"|"overcast"|"night")` drives sun elevation/energy and sky,
keeps character key/fill lights and suppresses the extra lighting ground. Other light
presets retain their character lights with a noon outdoor sky. Explicit subjects are
recommended for camera and lighting. Outdoor sets use a 128 MB shadow pool and half
shadow resolution for CPU previews. Clear/replace restores the previous world and
shadow settings, including after save/open. `CHAR3D_OUTDOOR_VISUALS=1` enables all
outdoor stills in the smoke test; numeric checks, precipitation workbench checks and
the weather draft always run.

**Lighting** — `set_lighting(preset, subject, follow="auto")`: studio, soft, dramatic, sunset, noon,
overcast, night, neon, silhouette, horror. Adds a large ground plane indoors by default and
switches the scene to Eevee. `rotate` spins the rig of lights around the subject.
Call **after body animation** (`walk_path`, `animate`, `sit_on`) so it can sample the
whole scene range; rerun after changing motion. `follow="auto"` follows horizontal
travel > 0.43 x standing height (~0.75 m for a human); `True` follows any motion,
`False` keeps the old static placement. Local lights follow the smoothed union bounds'
XY center and ground height, with a stable standing scale through stairs/sitting.
SUNs, ground, world and environment practical lights stay static. Results include
`follow` (actually used), `travel_m` and `keys` (location sample count).
Use character subjects for character exposure; adding large static props changes the
union center/scale and can put lights behind scenery that casts shadows on the cast.
`set_material(objects, color, roughness, metallic, emission_strength)` for quick looks.

When a cinematic look is active, existing and future character shots get live head/eye
focus at render time (including dialog/script coverage). `depth_of_field=None` follows
the look; explicit `False` opts a shot out and explicit `True` keeps its own `f_stop`.
Without a look, None has the same behavior as the former False default.

**Shots** — `camera_shot(subject, shot, move, start_frame, end_frame, angle, elevation,
intensity, handheld, roll, depth_of_field, avoid_occlusion="auto")`:
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
- `avoid_occlusion="auto"` (also `True`) raycasts evaluated visible meshes at the
  start/middle/end and about every 0.5 s. It checks each subject's posed face/eyes,
  head/chest and, for wider sizes, body bounds. Subject meshes, descendants, active
  held props, ground and hidden geometry are excluded; other characters can block
  singles, while every subject in a two-shot is excluded.
- Blocked faces or excessive foreground trigger a deterministic search: pedestal
  up first, then small azimuth changes, then closer positions past the occluder.
  Each candidate fits aim and lens to the original projected eye/head-top/chest
  landmarks. Seated bounds that place eyes outside the upper-third band define
  their unobstructed design by translating those targets to a 1/3 eye line,
  retaining their relative size. Candidates allow ±4% of frame height/width for
  headroom/eye position and ±15% for head-to-chest projected height.
- Acceptance requires face occlusion <= 5%, clear eyes for close-ups, face samples
  inside the frame, and foreground coverage <= 25% (close_up, medium_close, medium;
  also extreme_close_up) or <= 35% for wider sizes. Coverage uses a 24x14 ray grid,
  ending at the nearest subject's eye-depth plane. Subject geometry uses the same
  exclusions as face rays. Camera positions inside scenery/subject bounds or
  across walls are rejected; dialog preserves the current action-line side.
- If no candidate passes, try exactly one wider size (close_up → medium_close →
  medium → medium_full; extreme_close_up → close_up), with the same checks. If
  that fails, keep the original camera and return a `warning`. Frontal unobstructed shots
  retain exactly the original transform/lens keys; `False` retains original framing.
  Dialog singles additionally require composition even if face/foreground are clear,
  so bounds-based seated framing cannot leave the eyes against the frame edge.
- Face orientation is checked with the live anatomical head frame: a face angle
  over 75° triggers adjustment (larger azimuth candidates are tried for turned
  faces), or a warning if no safe view passes. Frontal unobstructed shots retain
  their exact original keys. Results add `face_angle_before` and `face_angle`
  (worst sampled degrees) alongside geometric occlusion fractions.
- Results include `occlusion`: worst sampled face fraction `before`/`after`,
  `adjusted`, body fractions, `sample_frames`, timing `seconds`,
  `frame_coverage_before`/`frame_coverage_after`, `face_screen` (sampled normalized
  eye positions, top-left origin), `subject_scale` (sampled head-to-chest height
  relative to the design), and `shot_size` used (also at the top level).
  Dialog/script shot results include the same report. Inspect with Eevee after
  changing later animation. Visibility and foreground coverage are sampled, with
  approximate face landmarks; thin objects/grid gaps and brief crossings between
  samples may be missed. Own hair/held props can still cover the face.

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

## Cinematic look

`cinematic_look(preset="golden_hour", intensity=1, haze=None, god_rays=None,
bloom=None, dof="auto", particles=None, grade=None, sun=None, clear=False)` stores
`scene["char3d_cinematic_look"]` JSON. It never permanently edits world, lights,
materials, camera DOF, compositor or render settings. Lit previews/views/frames and
preview/final/Cycles movies copy the required datablocks and apply effects only
inside a `finally`-protected render context. Clear/`none` removes the JSON; strength
zero and workbench bypass the entire look. Save/open and separate-process video
snapshots retain the JSON and rebuild procedural effects without downloads.
These are char3d render settings; opening the blend in an unrelated Blender session
does not automatically install the rendering context.

| preset | direction |
|---|---|
| golden_hour | low warm sun, long shadows, warm aerial haze, teal-orange separation |
| sunset | very low orange sun, pink sky, warm rim and gentle glow |
| misty_morning | cool pastel light, denser haze concentrated near the ground |
| blue_hour | blue twilight, warm practicals and soft bloom |
| night | cool moon key, dim blue airglow, warm practicals and light fog |
| overcast_soft | diffuse daylight, restrained saturation and subtle haze |
| dreamy | pastel, lifted blacks, stronger bloom and sparse floating dust |
| epic | directional sunlight, stronger shafts, contrast and vignette |
| studio_film | subtle indoor haze, practical glow, film grade and mild grain |
| none | original scene appearance |

Aliases include `jam emas` / `sore keemasan`, `senja` / `matahari terbenam`,
`pagi berkabut`, `jam biru`, `malam`, `mendung lembut`, `mimpi`, `epik`, `film studio`.
The UI supplies representative color swatches, not prerendered thumbnails.

Order: body/dialog performance → set/environment → `set_lighting` → cameras →
`set_weather` → `cinematic_look` → inspect Eevee → save/render. Later lighting,
weather, set and camera edits remain valid because overrides are rebuilt per render.
Indoor sets retain their world and never acquire an outdoor sun. Office window
lights can project through existing mullions; stage spots produce their own beams.
Other indoor rooms use subtle key/practical volume contribution. Outdoors uses the
Sky Texture's physical scattering model, matched to the directional sun. At night
the solar sky is below the horizon; a separate blue hemisphere supplies airglow
and the directional key represents moonlight above the horizon.

- `intensity` is 0..1. `haze` is scattering density in inverse meters, 0..0.1;
  `False` disables it and `True` retains the preset density. `god_rays` and `bloom`
  accept 0..1 or booleans. `sun={"elevation":8,"azimuth":220}` overrides degrees
  (azimuth 0 = -Y, 90 = +X). Existing face key/fill are balanced against the sun.
- Haze uses a bounded scattering volume, with reduced density within about 1.2 m
  of the live head (including walking/seated poses); stage uses a smaller 0.45 m
  clear zone so practical beams remain visible around the performers. Eevee uses
  8 px tiles, 32 depth steps and a 25 m indoor /
  65 m outdoor range; epic enables volume self shadows with 8 shadow samples.
  Shadow-casting sun/spots/window lights create actual volume shafts, not image
  overlays. Volume shadow quality and visibility depend on existing occluders.
- Weather rain/snow/wind retain their saved motion, wet-ground state and sky
  dimming. Weather `fog` owns the scattering volume and replaces look haze to avoid
  double fog. Clearing the look never clears weather or changes its saved settings.
- `dof="auto"` tracks the live anatomical eye plane through a head-bone constraint
  on singles. Two-shots sample the current speaker and use a short smooth rack;
  cuts choose the incoming speaker's focus. F-stops range from 2.8 for close-ups
  through 4 for medium to 11/16 for wides. Explicit shot `depth_of_field=True`
  retains its f-stop; explicit False opts out. `dof="off"` disables only automatic
  focus. Existing/user-authored camera DOF is preserved. No look leaves the old
  shot behavior unchanged.
- `particles="dust"|"pollen"|"petals"|"embers"` or
  `{"kind":"petals","count":100,"seed":17}` adds cheap geometry-node instances
  in camera coverage. Count is 0..500. Positions and Scene Time motion are seeded
  and work in background renders without handlers or simulation caches. Only
  dreamy enables particles by default; other looks have none.
- `grade` reuses render-style exposure, contrast, saturation, temperature, tint
  and teal-orange primitives. It also accepts `lifted_blacks` (0..0.2), `vignette`
  (0..1), `grain` (0..0.03), `chromatic_aberration` (0..0.02). Bloom uses compositor
  Glare/Fog Glow (Eevee Next has no built-in bloom). Mild lens dispersion is opt-in.
  Film grain appears by default only in studio_film (or an active render style).
- Stacking is one compositor pass: look grade supplies the base; active
  `render_style.grade` keys take precedence, including that style's defaults. Noir also suppresses inherited color casts
  unless its own grade explicitly requests them.
  Exposure/contrast/saturation are not multiplied twice. Bloom, vignette, lifted
  blacks and grain use the larger requested amount, once. Style material/outline
  overrides and letterboxing still work. User compositor graphs are copied and
  extended upstream; originals stay intact;
  titles/subtitles remain downstream, with their original colors.

`render_options` returns `cinematic_look` and `look_cost_factor`. The product of
style/look cost factors affects estimates and the calibration denominator, so
learning a styled movie cannot count either effect twice. Draft uses 1.0.
Blender 5.2 timestamped `Video append frame` logs and legacy `Fra`/`Time` logs
both supply progress and per-frame speed learning; the first cold frame is excluded.

Measured CPU Eevee, 960×540, 16 samples, two clothed MPFB humans, same close-up camera.

| look | studio s/frame | vs none | park s/frame | vs none | estimate factor |
|---|---:|---:|---:|---:|---:|
| none | 35.9 | 1.00× | 38.9 | 1.00× | 1.00× |
| golden_hour | 40.7 | 1.13× | 46.9 | 1.21× | 1.35× |
| sunset | 46.0 | 1.28× | 43.2 | 1.11× | 1.35× |
| misty_morning | 42.0 | 1.17× | 48.9 | 1.26× | 1.40× |
| blue_hour | 51.4 | 1.43× | 36.5 | 0.94× | 1.50× |
| night | 45.6 | 1.27× | 60.5 | 1.55× | 1.65× |
| overcast_soft | 40.1 | 1.12× | 47.5 | 1.22× | 1.30× |
| dreamy | 40.9 | 1.14× | 47.7 | 1.23× | 1.45× |
| epic | 41.3 | 1.15× | 48.5 | 1.25× | 1.50× |
| studio_film | 36.5 | 1.02× | 33.5 | 0.86× | 1.30× |

Factors retain conservative preset floors and a margin over the larger measured ratio.
They do not assume that a look will be faster when one measured scene happened to be cheaper.
Cold starts were 59–99 seconds in these batches and are listed separately in the raw samples.
Full-resolution samples include allocation/PNG cost and vary with shared CPU load.
Raw timings: `output/cinematic_benchmark.json`; all-preset sheet: `output/cinematic_sheets/all_presets.png`.

Reproduce the saved two-person MPFB scenes, contact sheets, measurements and clips:
`CHAR3D_PORT=9988 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python
 tests/cinematic_visuals.py --sets --bench --movies`. Tests use installed CC0 assets
and 8 render threads, with no downloads. Each timing includes temporary setup,
restoration and PNG output. A 320 px warm-up precedes two timed 960×540 frames;
the warm-up is excluded, but any size-specific allocation is included. Shared CPU load,
set complexity, resolution and camera placement affect relative cost. This is
atmosphere/art direction for existing sets, not richer foliage, clouds or water.
Wide shots retain deep focus; exaggerated close-ups, unsuitable hair, very dense
user fog or custom camera rigs can still need manual art direction. The look does
not export to glTF; export scene geometry separately if needed.

## Render styles
`render_style(style="none", strength=1.0, outline=None, grade=None, letterbox=None)`
stores JSON in `scene["char3d_render_style"]`; it survives save/open and background
video snapshots. It never edits original materials, modifiers, world or view settings.
Lit `render_preview`, `render_views`, `render_frames(camera="scene")` and preview/final/
cycles videos apply temporary overrides, restored in `finally` even on render failure.
`none` removes the config and uses the original render path with identical pixels;
`strength=0` bypasses everything. Draft/workbench retains its existing appearance.

- `anime` / `toon` (alias): three lighting bands multiplied by each Principled
  material's existing base color/texture; alpha follows its original texture graph.
  Nested shader groups (including MPFB skin) are copied recursively for the render.
  Opaque meshes receive thin, reversed, expanded silhouette shells with backface
  culling. Alpha hair cards, eyes, brows, lashes and mouth inserts skip shells to
  preserve readable features. Hair keeps its alpha and receives the same light ramp.
  `outline=False` skips shells. A same-camera Eevee trial of Freestyle on/off
  produced identical pixels (24.7 vs 32.2 s at 512 px), so it did not provide
  outlines here. Hulls work in Eevee without line art's Grease Pencil setup.
  They add silhouette geometry without tracing
  every texture edge; this favors predictable cost and readable faces. Thin/open
  meshes can show seams; outline width is 1.2 mm before object scaling at strength 1.
  Cycles uses Toon BSDF instead of Eevee's Shader-to-RGB ramp.
- `clay`: uniform warm, rough clay with the scene's soft lighting/shadows; alpha masks
  remain active. Custom shaders without a Principled node keep their shading.
- `film`: AgX with contrast, subtle fog glow, vignette and animated deterministic grain.
  `grade={"teal_orange": True}` enables a subtle split tone; `letterbox=True` adds
  2.39:1 bars (or pass an aspect 1..4). Bars and grading precede titles/captions.
- `noir`: high contrast monochrome, stronger grain and vignette.
- `vintage`: warm faded color, softer contrast, raised blacks, grain and light vignette.

`grade` overrides exposure (-8..8 stops), contrast/saturation (0..3, neutral 1),
temperature/tint (-1..1, neutral 0). `strength` is 0..1. Styles replace the previous
config; omitted options use the new preset's defaults. Grade affects the picture,
while subtitles/titles retain their original colors and layout. User compositor graphs
are copied and extended without editing the originals; style configuration does not export to glTF.

`render_options` reports `render_style` and `style_cost_factor`; the same factor
is included in estimates and removed from machine-speed learning to avoid counting
style cost twice. Measurements and inspected close/medium views can be reproduced
with `CHAR3D_PORT=9980 .venv/bin/python tests/render_style_visuals.py`; results go to
`output/render_style_benchmark.json` and `output/render_style_contact_sheet.png`.

Measured CPU Eevee at 960×540 / 16 samples on the same MPFB podcast close-up;
mean of two warmed stills, including override setup/restoration and PNG output:

| style | seconds/frame | vs none | estimate factor |
|---|---:|---:|---:|
| none | 34.8 | 1.00× | 1.00× |
| anime, outlines on | 41.7 | 1.20× | 1.20× |
| clay | 29.3 | 0.84× | 1.00× |
| film | 32.2 | 0.93× | 1.10× |
| noir | 33.2 | 0.96× | 1.05× |
| vintage | 32.9 | 0.94× | 1.05× |

These measurements used llvmpipe with 8 rendering threads on a shared CPU. Cold
shader compilation is excluded; relative costs vary with scene/shader complexity.
Estimates conservatively retain overhead for the looks that happened to be cheaper
in this scene. Anime without outlines uses 1.05×; explicitly enabling outlines on
another look adds 0.20 to its factor. Draft always uses 1.00×.

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

**Cinematic dialog with automatic focus**
`script_to_scene("LOKASI: park\nSUASANA: jam emas\nANA (perempuan, 28): Indah sekali!\nBUDI (pria, 30): Mari bersama.")`
→ `render_frames([12, 32, 55], camera="scene", engine_name="eevee", size=512)`
→ inspect faces and a wide → `save_project("golden_dialog.blend")`
→ `render_options("preview")` → choose resolution → `render_video(..., resolution="540p")`.
For an existing conversation: finish lighting/cameras/weather, then call
`cinematic_look("studio_film")` indoors or `cinematic_look("golden_hour")` outdoors.
`cinematic_look(clear=True)` returns to the source scene without undoing its animation.

**Short cinematic clip (Higgsfield-style)**
`create_human` → `auto_rig_humanoid(rig_type="rigify")` → `set_material`
→ `w = animate(rig, "walk", cycles=3)` → `animate(rig, "wave", start_frame=w.next_start_frame)`
→ `set_lighting("sunset", subject=[mesh])`
→ `camera_shot(subject=[mesh], shot="wide", move="drone_reveal", start_frame=1, end_frame=40)`
→ `camera_shot(..., shot="full", move="tracking_side", start_frame=41, end_frame=96)`
→ `camera_shot(..., shot="medium", move="crash_zoom", start_frame=97, end_frame=134)`
→ `cinematic_look("golden_hour")` (after optional `set_weather`)
→ `render_frames(camera="scene", engine_name="eevee")` check → `render_video(quality="draft", wait=True)`
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

## For agents editing this repo
### Web UI
- `./run_webui.sh` serves the local Starlette studio at 127.0.0.1:8765;
  `--port` / `CHAR3D_WEBUI_PORT` overrides it. Source lives in `webui/`.
- The UI discovers schemas with `mcp.list_tools()` and calls `mcp.call_tool()`;
  reuse this adapter, never duplicate engine behavior or import `bpy` here.
- Frontend is buildless vanilla ES modules; three.js r160 and its MIT license are
  vendored. Runtime assets must remain offline. External AI generation needs consent.
- Run `CHAR3D_PORT=9981 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python
  tests/webui_smoke.py` (starts UI on 8781), `tests/test_webui.py`, and the existing
  `tests/test_phonemes.py`. `tests/webui_e2e.py` exercises a running UI on 8781.
  Keep 9876 untouched; shut down the isolated test engine when finished.

- `engine/` runs inside Blender's bundled Python (has `bpy`); never import `bpy` in
  `mcp_server/`. Add an engine command with `@command("name")` in
  `engine/commands/*.py`, then a matching tool in `mcp_server/server.py`.
- Test end-to-end with `.venv/bin/python tests/e2e_smoke.py` and the offline AI pipeline
  with `.venv/bin/python tests/e2e_ai_mock.py` (local fake fal.ai, no key or network).
- `tests/e2e_outdoor_state.py` checks saved weather and user-world restoration across
  save/open/clear; run it on an assigned experiment port after the main suites.
- `providers/` runs in the MCP server process (network); never call the network from
  `engine/`. Never log or persist API keys.
