# char3d — agent guide

This repo is a 3D character engine driven through MCP. A headless Blender process
(`engine/`) does the work; `mcp_server/` exposes it as tools. Use the **char3d** MCP
tools — do not try to launch Blender yourself.

## Conventions
- Units: meters. Z is up. Characters stand on Z=0 and **face -Y** (the "front" view).
- A human character is ~1.6–1.9 m tall. Check `dimensions` in `scene_info`.
- Object names are case-sensitive and unique; always take them from `scene_info`.
- A freshly started engine already holds an empty scene, the same as `new_scene()`
  (no factory cube, camera or light).
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
- Face: `list_expressions`, `set_expression`, `auto_expression`, `face_life`, `lip_sync` (phoneme/word detail), `auto_blink`
- Audio & voice: `add_audio`, `auto_music`, `auto_sfx`, `duck_music`, `list_audio`, `remove_audio`, `transcribe_audio`,
  `list_voices`, `text_to_speech`, `cancel_tts`, `lip_sync_audio`, `talk_motion`, `talk_gestures`,
  `ai_text_to_speech` (legacy free HF Space)
- Dialog: `dialog`, `stage_dialog`, `script_to_scene` (live dialog coverage, guest seating, outfits + hair/cloth motion)
- Characters & rigs: `create_human`, `estimate_landmarks`, `auto_rig_humanoid`,
  `validate_rig`, `list_bones`, `set_pose`
- Hands: `set_hand_pose` (relaxed, open, palm, beat, point, fist, thumbs_up, peace, three,
  four, ok, grip)
- Animation: `list_animations`, `apply_pose`, `animate`, `walk_path`/`turn_to` (static obstacle avoidance), `walk_approach` (BVH walk-and-stop), `press_button`, `import_mocap`,
  `retarget_animation`, `lock_feet`, `resolve_collisions`, `secondary_motion` (hair/loose clothes), `clear_animation`, `render_frames`
- Film: `list_camera_moves`, `camera_shot` (visibility + composition), `list_shots`, `delete_shot`, `set_timeline`,
  `list_lighting_presets`, `set_lighting`, `cinematic_look`, `set_material`, `add_subtitles`,
  `remove_subtitles`, `add_transition`, `add_title`, `layout_overlays`, `list_graphics`, `remove_graphics`,
  `render_options`, `render_video`, `render_status`, `cancel_render`, `resume_job`
- Multi-scene films: `script_to_film`, `film_info`, `open_film_scene`,
  `film_render_options`, `render_film` (shared `render_status` / `cancel_render`)
- Sets & props: `set_environment`, `add_prop`, `clear_environment`, `sit_on`, `stand_up`,
  `hold_prop`, `release_prop` (indoor + city_street, park, cafe_terrace, beach)
- Interactions: `interact` (handshake, hug, high_five, fist_bump, handover, pat_shoulder)
- Weather: `set_weather` (clear, rain, snow, fog, wind; saved procedural animation)
- Walkable ground: `add_terrain`, `clear_terrain`
- Nature: `nature_catalog`, `add_nature`, `clear_nature` (original seeded generators)
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
- `hair_color="auburn"` (black, dark_brown, brown, auburn, red, blonde, grey or an sRGB
  triple) tints realistic hair and brows on private material copies. Base colour
  becomes target x texel luminance / median, so strand/root-tip variation stays; the
  highlight is softened. Realistic builds with `face=True` also lift fringe strands that
  hang over the eye window (bob01 covered one eye); `fringe_lift_m` reports the lift.
  Other grooms are untouched. Realistic grooms longer than 17 cm (bob, long) also get a
  slightly off-centre, wandering crown parting (about 4 mm side shift, 3 mm wave, side
  chosen by `seed`; the same rest offset on every shape key, `c3d_parting_offset_m` on
  the hair object) and a `c3d_parting` point mask (crown down to the front hairline) that
  the enhanced hair shader uses to darken colour, specular and grazing sheen along the
  parting roots; `hair_color` reapplies that shadow after its luminance cap, which
  otherwise saturated bright crown strands. Short crops keep their crown. Rebuild
  existing characters to receive these changes.
- `skin_tone="light"|"medium"|"dark"` (or linear RGB) rebalances the enhanced skin
  texture toward that tone, keeping its local features. With `race` unset and
  `skin="auto"`, it also starts from the closest scan (light caucasian, medium asian,
  dark african) instead of the default mixed phenotype's dark scan, which brightened
  to orange. The phenotype stays mixed; explicit race/skin choices win.
- `outfit="casual"|"formal"|"sport"|"summer"|"winter"` chooses compatible installed
  top+bottom (or dress/full suit) + shoes, plus a winter hat; `seed=0` makes the choice
  repeatable for the same catalog/gender. Names/tags declaring male/female are respected;
  unmarked items are treated as unisex. Explicit `clothes` (including `[]`) overrides
  the preset. `warnings` reports unavailable categories or overlaps (two tops, suit+top,
  two shoes, etc.) without rejecting explicit combinations. Presets use name/tag style
  hints and available fallbacks. The later collision pass constrains eligible loose garments;
  the picker itself does not fit collisions. Hats/hair, broad skirts and extreme bends
  may still intersect or produce skipped conflicts. Check posed Eevee views.
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
- Use `create_human` (mannequin) for blockout work or when MPFB is missing
  (`mpfb_assets` errors → tell the user to run `scripts/install_mpfb.sh`).

## Stylized characters

`create_realistic_human(..., style="realistic"|"anime"|"cartoon"|"chibi")`
uses MPFB for all four styles. The default realistic path is unchanged. Anime is
6.75 heads, cartoon 4.75, chibi 2.8, measured scalp-to-chin (hair is excluded). These
are original proportions/materials, not designs from existing characters/studios.
Stylized builds freeze the phenotype, deform every relative facial target and
fitted hair/clothing mesh together, transform rest bone endpoints, and re-fit
stored landmarks. MPFB weights, fingers, ARKit/visemes and rigs remain native.
For Rigify, proportions are fitted on its metarig before generating the rig's
length-dependent mechanisms; the generated rest face is checked against the mesh.
`game_engine` and FK `rigify` support the usual pose, walk, seat, interaction,
speaking gesture, blink/lip-sync and GLB paths. Do not auto-rig them again.

Eyes are enlarged with their lids/lashes and have an original code-generated
iris/pupil/highlight atlas. Closed blink targets recess the eye inserts behind
the lids (native continuous morphs, with no visibility/alpha switches). The full
upper lid margin is calibrated onto the lower contour in the blink target,
including both canthi; the review checks the 3D gap and sampled eye occlusion.
Eye width and height use independent monotone remaps, with lower eye placement,
a larger forehead and reduced lower face/nose. Anime has a softly pointed chin;
cartoon/chibi have rounder cheeks/chins. Native skinned ink ribbons follow the
upper/lower lid morphs; simple thin brows replace photographic alpha strands.
The short styles rebalance leg/torso heights and shorten arms/hands/feet with
actual shoulder/wrist anchors. One C1 height map spans torso, neck and head;
the neck width blend excludes shoulders. Chibi uses 82% of the MPFB stature to
shorten torso and limbs together while retaining 2.8 heads; other styles retain
the source stature. Choose a proportionate low chair for its short lower legs.
Stylized cheeks/forehead receive fixed rest smoothing on every target while
preserving the eye/lip rims. A bounded static contour fill rounds the cheek/jaw
notch; the same offset is added to every relative target. A saved two-level render
subdivision smooths the head/upper neck; creased non-head edges retain the body surface. Viewport/export retain
original HM08 topology with smooth normals, native weights and morphs. Native
brow ribbons replace overlapping alpha cards. Teeth/tongue are fitted behind the
lip plane; smile corner lift is stronger. With trousers, covered shoe uppers are
removed consistently from every shoe shape key. Inspect other footwear/outfits.
Hair uses packed binary cutout alpha,
also portable to GLB, rather than stochastic intermediate strand opacity.
`tests/toon_polish.py --case f_anime` (also f/m × all four styles) records actual
eye/head/face ratios, blink and A/O/M/B/P lip gaps. `--sheet` composes the rendered
female/male front/three-quarter comparison. Use port 9971 and one case at a time.
Skin uses flat sampled albedo with soft UV blush and no pores;
hair retains a reduced cutout mask and broad clump values. Generic stylized
`bob01`/`bob02` requests choose installed `toigo_curled_under_bob` (system
`ponytail01` fallback); `short01` chooses `culturalibre_hair_02` (`short04`
fallback); generic `short02` chooses installed `culturalibre_hair_05`
(`short04` fallback; CC0, culturalibre/swift502), with the requested asset's
pigment retained. Results report the actual
asset and a warning. Explicit look recipes retain their hair asset. A local
fringe lift clears the eye window on both paths, including photo/look replay.
Stylized scalp cards keep their neutral facial-unit deltas so a blink cannot
pull the fringe over the brow; head-bone weights and secondary motion remain.
Clothes retain 128 px simplified albedo/prints; their dominant pigment is sampled
inside the material's actual UV islands, excluding unused atlas margins.
These PBR textures/materials export without downloading
assets. The result recommends `render_style("anime")`; it never changes global
render style. `animated_film` also works. Rest deformation is not an MPFB macro
editor: recreate the character to change its phenotype/style afterwards.
GLB carries proportions, skinning, morphs and flat textures; outlines/cel bands
remain Blender scene render effects.
Toon skin samples fitted cheek UVs and captures the realistic scan exposure
reference before MPFB macro baking. A common RGB scalar normalizes the portable
PBR albedo; cel shaders retain half the log exposure correction in temporary
shader copies. There is no red-channel cap, additive skin emission or fixed pink
mix. Cheek variation changes value only. The bounded dark-pigment lift and anime
shadow band retain readability. Animated-film uses an albedo-relative scalar fill,
gentler face-form gradient and shorter, weaker facial AO. Both enhanced realistic
and toon skin use the same colour path when a toon render look is requested.
Temporary skin pigment/coverage passes preserve pigment hue/saturation through
the default scene grade while retaining its shaded value; they are removed after
rendering, including on failure. Explicit artistic colour-grade overrides win.
Normal realistic PBR rendering, global exposure/lights and other materials remain
unchanged. Photo/look pigment bypasses scan normalization because it already
contains the source illumination.
The face's silhouette shell omits the internal bridge so it cannot draw a deep
nose stroke. Rebuild existing characters for geometry, hair and texture changes;
rerendering an old packed blend alone retains its old meshes/assets. Head render
subdivision increases Eevee cost; exported base topology remains native HM08.
For animated-film faces, a cheek-supported rest-depth surface rounds the nasal
bridge/tip and supports the lips without the inherited nasolabial grooves. A
front-surface ray query preserves the depth of hidden nostril/oral linings; every
relative target receives the same rest offset. A common neutral-space gain then
reduces excessive native forward/back mouth and cheek articulation, and bounds the
smile's oversized corner pull/lift. That Round 5 correction keeps vowel/bilabial
X/Z articulation native; Round 6 replaces the mouth-contour articulation below.
Eyelid rims retain their exact
positions and blink motion. This affects stylized builds only, including their
portable morphs; realistic geometry/materials and the global film shader stay
unchanged. Rebuild existing characters to receive it.
Round 6 adds a convex lower-face rest support shared by the body and fitted
parts/relative targets. Narrow neutral eyelids are opened to 0.13 head heights;
their iris atlas is centered on the opening, with the full blink recalibrated.
Vowel rims use round A/O contours and topology-based delta diffusion through
the lips/jaw; smiles have an explicit upward corner curve. Oral lining keeps a
separate dark PBR material. Full-rim M/B/P closure supplements the older central
gap probes. Four native combination morphs cancel lid squints at full blink;
their simple drivers remain saved in Blender and are sampled in glTF animation.
No vertices, weights or existing shape-key names are replaced.
Rebuild existing characters for these changes; opening an old blend retains its
saved rest geometry and targets.
Stylized anime/animated-film renders temporarily transfer masked custom normals
from a head-bone-following ellipsoid (anime: vertically elongated, so normals stay
nearly horizontal and the cel terminator follows the key's horizontal angle down the
face edge instead of darkening the lower cheeks/jaw). Anime skin/clothes use one key-direction
threshold, avoiding multi-light/cast-shadow camouflage; animated-film skin uses
a broad continuous key gradient. Realistic characters keep their existing shaders.
Hair shares its pigment response across both styles, with a soft cutout edge and
smoothed frontal card boundaries; explicit look recipes retaining the authored
short02 cap can still read as a helmet. The normal proxy, modifier and vertex group are removed
after rendering, including on failure; GLB retains the actual rest geometry and
native morphs, without this temporary normal field. Techniques were informed by
the owner's MIT blender-agent-skills NPR, facial-shapekeys and hair references;
their scripts are not run by char3d.
`tests/toon_round6.py --case before|after --resume` records matched six-person,
three-angle, two-look/style portraits (256 px, 8 Eevee samples). The before
fixture loads the pinned c7720c9 toon/render-style source, not current stylization.
`--case articulation --phase before|after` checks native gaps and renders the
mouth/blink row; `--case colour` repeats the Round 4b colour/realistic identity
contract. Evidence and metrics are under `output/toon_round6/`; port 9971 only.
Use `--case looks --phase before|after` for all nine cinematic presets plus
studio; `--case hair` for the audited catalog's realistic pigment references,
and `--case check` for sheets/contracts. `--all-characters --measure-only` with
`articulation` compares native gaps, topology, weights, bones and contact metadata
across the six saved builds. The lower-lid wall can still show a small crescent
during strong squints; the backface shading guard softens it, without replacing
the authored MPFB socket topology.
Silhouette measurements use continuous edge-plane sections of the native control
mesh at 35/55 degrees; reduced upper-hull deficit does not imply a perfectly convex
rendered contour. Shadow measurements use one shared cheek/lower-jaw mask,
excluding the union of both builds' projected eye/mouth rims and silhouette edges.
Native camera correspondences validate its perspective replay. Broad feature-
inclusive measurements and mask overlays remain in the evidence for inspection.
Hair hue/saturation assertions cover the audited ponytail01/short02 assets;
the eye-safe replacement bob additionally records its warmer PBR-highlight hue
mismatch as a diagnostic. Anime/animated-film retain the same dark bob pigment.
Round 7 slides lower-socket expression deltas with the lid; iris/gaze and native
blink channels remain. Native blink/wink guards cancel smile/brow separation,
with a bounded closed-lash depth fit. A rounded graded mouth pocket, single upper
tooth band and low red-brown tongue replace the detailed inserts (hidden with
portable alpha). These skinned, column-sampled meshes retain native targets,
packed textures and `tongueOut`; photo recolouring preserves their palette.
Cartoon/chibi receive a common chin/upper-neck rest offset on every target,
preserving body topology, head endpoints and weights. Skin retains its Round 4b
response: a warm hue/value trial breached the dark floor and was rejected.
Realistic PBR stays unchanged. `tests/toon_round7.py` captures pinned d92d70d
portraits at 512 px, expressions, socket-ID passes, articulation and asset QA.
Use only 9971/workspace `output/`; reference scripts are not run. Small outer-eye
dimples, some segmented closed-lid ink, oblique lip rims and card clumps remain.
The bob's existing near-black film grade is recorded separately, with unchanged
baseline RGB required; ponytail/short-hair colour bounds remain strict.
Rebuild characters for these changes; HM08 is not a replacement facial sculpt.
`tests/toon_round5.py` captures ab28f51-equivalent `--case before` snapshots (the
correction is disabled only inside that test fixture), then `--case after`,
`articulation`, `colour` and `check`. The contract covers Caucasian/Asian/African
scans, female/male, front/three-quarter at 512 px under studio-film lighting.
It checks projected narrow-shadow contrast in fixed nose/nasolabial ROIs,
with a separate upper-bridge/glabella diagnostic and a retained nose-tip check,
unchanged eyelid rims and X/Z contours, vowel/bilabial gaps, and the Round 4b colour
contract with pixel-identical realistic references. Surface diagnostics exclude
masked helpers and camera-occluded linings, and record adjacent-normal variation,
signed Laplacian depth and deterministic short-range BVH occlusion. Evidence is
under `output/toon_round5/`; use port 9971, one owned engine, workspace `output/`.
`tests/toon_round4.py` records the lighting/colour matrix, five-angle alpha-aware
eye visibility, 512 px facial checks, garment colour comparisons and podcast
stills. Use only port 9971, with one owned engine at a time.
`tests/toon_round4b.py` compares actual Caucasian/Asian/African scans in realistic,
anime and animated-film studio-film portraits. It checks hue within 0.04 turns,
saturation at least 0.75 of realistic, tone gaps above 0.02 Y-prime, and a dark
anime cheek above 0.33. `--case native` verifies packed-material replay, preservation
of existing AOVs and an explicit monochrome override. Results are under
`output/toon_round4b/`; use `--case before|after|garments` then `--case check`.
Keep `face=True` for facial animation; a stylized `face=False` build must be
recreated rather than loading unfitted facial targets onto its frozen proportions.

Descriptors accept `gaya anime` / `anime`, `kartun` / `cartoon`, `chibi` and
`realistis` / `realistic`. Dict characters accept `style`. A `GAYA: anime` or
`STYLE: anime` scene defaults otherwise unspecified characters to anime bodies;
an explicit character style wins. An explicit scene render-style argument wins
over the header. Other scene render styles keep realistic body defaults.

Inspect front/right/back/three-quarter and posed faces. Extreme heads, existing
garment designs, hats and very tight clothes can intersect; this is continuous
rest deformation, not clothing remeshing or collision simulation. MPFB's target
inventory remains available for articulation; it cannot produce arbitrary anime
topology or independent hand-drawn facial linework. Full blinks and mouth opening
are measured in the isolated checks, alongside actual rendered posed meshes.

## VRM import (optional add-on)

Script actors accept `{"id":"Nara","vrm":"vrm/model.vrm"}` or
`NARA (vrm: model.vrm, perempuan, 27): Halo!`. Paths stay under imports/;
bare names prefer imports/vrm/. Parse-only reads embedded title/author/licence
without importing (missing/invalid metadata is unverified). Gender/age override
voice hints; absent hints warn. Wardrobe/hair/outfit changes warn and are ignored;
films reuse the same native actor. Never prepare or auto-rig it.
`dialog(characters=[{"id":"Nara","vrm":"model.vrm"}, ...], lines=[...])`
can cast directly; line speakers use the declared ids.
Native hair/skirt spring bones bake through secondary_motion, preserving weights.
Combined VRoid meshes use Body Skin for pelvis contact and body-proxy fitting;
native loose-cloth chains also receive bounded scene/seat collision constraints.
Lit VRM rendering uses authored MToon pigment/shade/rim/cutout/cull parameters,
including style none; anime sharpens bands and animated_film softens them with
outlines off by default. Overrides restore originals for mixed casts/export.
VRoid whole-face presets are region-masked in semantic aliases so eye reactions
do not move lips; original targets stay intact. A temporary head-following
normal field flattens anime face shading (ellipsoid for film), without changing
exported normals. Anime uses 0.2 of the face's horizontal normal spread so a side
key never splits the face down the nose. Hair materials lift their shade 30% toward
the lit colour and scale value 1.25x so black/purple clumps stay readable.
Bone-based gaze aliases respect declared VRM inward/outward/up/down limits.
VRoid faces with per-region Fcl_EYE/BRW/MTH keys bind smile, squint, wide-eye,
brow and frown units directly to those authored shapes (closed MTH_Fun smile with
EYE_Joy happy eyes, BRW_Surprised, BRW_Sorrow, MTH_Sorrow); other VRMs keep masked
presets. Rebuild/re-import the actor to receive them.
Credits include embedded declarations; each model's licence and permission remain
the user's responsibility. Test only on port 9976, workspace output/:
`tests/test_vrm_actors.py`, `tests/e2e_smoke.py --vrm-actors-only`.

`import_model("avatar.vrm")` supports VRM 0.x and 1.0 through the installed
[VRM Add-on for Blender](https://vrm-addon-for-blender.info/en-us/scripting-api/).
Missing installations report `scripts/install_vrm.sh`; runtime never downloads.
The installer prints version/URL/size/licence, asks confirmation, and verifies
the TSV SHA-256/bytes before using a ZIP. `--dry-run` is read-only/offline;
`--install` also runs Blender's extension installer (stop engines first).
Recommended extension: 4.10.5, 1,649,936 bytes, MIT OR GPL-3.0-or-later.
Metadata/source URLs are recorded in `scripts/toon_assets.tsv`.

The adapter reads declared humanoid bone assignments (including fingers), saves
semantic maps, and builds native char3d expression/viseme aliases from authored
morph binds. This supports `apply_pose`, animation/navigation/mocap, hands, facial
expressions, lip sync, blinks, talk motion and face life, within the model's own
channel inventory. Bone-based VRoid eye looks are baked to gaze morphs when
authored look expression binds are absent. Five vowels approximate consonants. Combined Blink cannot
provide independent winks. Missing expressions are not fabricated; material/UV
binds remain VRM metadata. Native simulation stays disabled; secondary_motion
bakes deterministic spring motion.
Inspect facing and rig mapping after import. Keep the imported rig; do not run
`prepare_model` (which deliberately removes rigs) or auto-rig it.

**VRM models carry their own licences. The user is responsible for permission to
use each model**, independently of the add-on's software licence.

## Face from a photo (optional local ONNX models)

`face_from_photo(character, image, strength=1, texture=None, consent=False)` fits
eleven paired MPFB head/chin/eye/nose/mouth/brow modifiers against local 66-point
OpenSeeFace landmarks. It requires `consent=True`: use only your own face or a
person who gave permission. JPEG/PNG must already be under workspace `imports/`;
paths and symlink targets outside it are rejected, including an `imports/` folder
that resolves outside the workspace. No photo is uploaded. Blender
decodes it; a short subprocess uses the existing host numpy/onnxruntime CPU, with
no torch, OpenCV or Pillow. Transient decoded arrays/landmarks are created only
inside imports and cleaned after success/failure. Saved .blend/GLB assets retain
the fitted appearance and optional generated texture; delete those separately
if removing the likeness. The original photo is never copied to another path.

Install explicitly with `scripts/install_face_landmarks.sh`: OpenSeeFace
`mnv3_detection_opt.onnx` (568,302 bytes) and `lm_model0_opt.onnx` (1,902,521 bytes),
both BSD-2-Clause, pinned to commit `50c09741897010faad721a218b2bbe14ecad6251`.
The owner-verified SHA-256 values and byte sizes are recorded in
`scripts/toon_assets.tsv`. `--dry-run` prints the plan without network/writes.
Models default to `~/.local/share/char3d/face`; `CHAR3D_FACE_MODEL_DIR` overrides
it. Workspace `models/face` is a fallback when the shared files are absent.
`CHAR3D_FACE_PYTHON` overrides the host Python.
Runtime missing-file errors give the installation hint and do not fetch models.

Use a neutral, level, frontal photo with one well-lit unobscured face; slight yaw
is supported. The bounded weak-perspective fit estimates yaw/pitch and reports
projected pixel RMSE and modifier values. OpenSeeFace model0 uses 66 confidence
planes and two 66-plane logit offset blocks on a 28×28 grid, decoded in numpy. Unseen 3D
depth remains the MPFB prior; it is not a scan or an identity guarantee. Colour
patch estimates can be biased by lighting, glasses, dark pupils or a background
above the hairline. `strength=0` leaves appearance unchanged. For realistic
characters, `texture=None` projects a softly masked photo into face UVs, keeping
eyes and mouth interior from the model. For stylized characters it defaults off
and transfers restrained shape traits plus skin/hair/eye pigment instead. Explicit
`texture=True` enables projection on either style. Existing weights and facial
animation deltas remain; inspect blinks/lips and refit hair after large transfers.
Photo pigment and projected RGB bypass the original scan's exposure correction;
they already include the photo's lighting. GLB preserves the projected skin atlas
and recoloured iris with its explicit eye UVs. It cannot undo illumination baked
into a photograph or infer hidden facial depth.
Photo fitting keeps generated Rigify mechanisms at their original rest skeleton;
large edits can need manual facial control/pivot adjustments. Morph articulation
and re-fitted skin/contact landmark metadata are retained.
Use original HM08 MPFB topology. Reapply after replacing/restoring materials.

The result includes `traits` with provenance: geometry is fitted, pigment is
estimated, and hair/glasses/beard catalog choices are provided or retained.
These two ONNX models do not identify hairstyles, glasses or beards. Supply
`traits={"hair":"bob01", "beard":null, "glasses":"catalog_name"}` to preserve
those choices explicitly; supplied assets must already be installed. Optional
`traits.colors_srgb` overrides skin/hair/iris pigment with finite sRGB triples.

`result.look` is a versioned JSON recipe with phenotype, style, paired face
modifier values, colours, catalog traits, fitting order and seed. Rebuild it with
`create_realistic_human(name="Again", look=result["look"], style="anime")` or a
script dict character `{"id":"Again", "look":recipe}`. Explicit style wins;
wardrobe, location and rig remain caller choices. Photo textures are stored as
hashed generated atlases under workspace `imports/face_looks/`; recipes refer to
those workspace files rather than embedding or uploading photos. Keep those
atlases when replaying textured looks in the same workspace. Numeric-only looks
have no source-image dependency. `face=True` is required for recipe face fitting.

`likeness_score`/`likeness` compare re-detected 66-point geometry from a neutral
local rerender with the input landmarks, after similarity alignment and
interocular normalization: `100*exp(-normalized_mean_error/0.20)`. This is a
geometric review score, **not identity verification or a calibrated probability**.
The result includes detection status/confidence, and returns null when the model
cannot reliably re-detect the fitted face. The review restores scene visibility,
cameras, pose, shape values and animation slots, and uses the existing render
context to limit RAM. A high score does not identify an individual or establish
that the single-view modifier values are unique or physically correct.

Verify only on **9971**, workspace `$PWD/output`, one owned engine at a time:
`tests/test_toon.py` prints `TOON UNIT OK`; `tests/e2e_smoke.py --toon-only`
builds all styles, measures actual eyelid rims/mouth morphs, walks/seats/speaks,
checks GLB morph/skin animation, descriptors and inspected Eevee stills.
Offline deterministic tests still mock optional interfaces.
`tests/toon_round3.py --face-case 0` (also 1/2) exercises the installed ONNX models
on our own synthetic portraits; `--vrm` exports our original MPFB avatar through
the installed add-on and imports both VRM 0.x and 1.0. No test downloads assets.

## Character materials

`create_realistic_human(..., materials="enhanced")` is the default, including
script/film builds and characters used in dialog. `materials="mpfb"` retains the
original MPFB shaders. Existing characters use
`upgrade_materials("Maya_rig", quality="enhanced", skin_tone=None,
skin_detail=1.0, hair_detail=1.0)`; the body name also works.
`quality="mpfb"` restores the original material datablocks, slot links and inactive
object overrides, removing owned attributes and unused shader copies. Upgrade is
idempotent. Restore before changing a character's material slots/topology.

- Skin keeps its original color/alpha/normal textures and UV graph. Automatic
  scatter parameters sample facial texture texels in linear color, independent of
  gender/ethnicity. `skin_tone="light"|"medium"|"dark"` or linear RGB overrides
  scatter/reflectance tuning and rebalances the texture's colour per channel toward
  the tone (local features stay). Red scatters
  farther than green/blue, over about 0.85–1.05 mm. T-zone oil, softer cheeks,
  restrained lip/lid darkening and cheek/nose/ear/knuckle warmth use fitted rest
  masks. Bright scans use a stronger monotone portrait normalization, preserving
  texture detail and tone order while keeping dark scans unchanged. A restrained rosy undertone
  applies to light skin. This is an artistic exposure calibration for char3d's
  lights, not a measurement of biological reflectance; global exposure/presets
  stay unchanged. Cinematic renders apply less of that correction under their
  already-dimmed face keys (temporary scalar values, restored even on failure
  and baked into video snapshots). Child pores are softer; elders retain wrinkles.
  The known default 5% global MPFB red mix is replaced by localized warmth; custom
  mix colors/strengths and the original material remain intact.
- Eyes keep their iris/vein textures, with warm sclera, soft upper-lid shading and
  an opaque wet coat (IOR 1.336), stronger moisture on the lower eye, a normal-based
  corneal cap, dark limbal ring and radial detail. The red default brown atlas is
  desaturated/balanced to natural brown; other eye textures keep their hue.
  A head-parented point supplies a clean catchlight: nominally 20 W, scaled with
  eye size, linked only to that character's eyes, zero diffuse/volume contribution,
  no shadows. It is native saved data and is removed by restore/excluded from glTF.
  This is still one surface, without refractive cornea/iris or tear geometry.
  DOF naturally softens the catchlight.
- Hair keeps authored alpha edges with Eevee DITHERED (legacy HASHED) rendering;
  head-hair alpha is remapped 0.22..0.62 -> 0..1 so faint card texels no longer
  dither into a grey stipple over the neck/cheeks (brows/lashes keep raw alpha),
  a height-based root/tip gradient, UV strand variation, restrained sheen and thin
  scattering. Brow/lash undertones follow the hair texture. Principled anisotropy
  is used where supported; strand normals/sheens approximate it in Eevee.
  Coily/afro cards use a rougher, less directional highlight to reduce bright seams.
  No geometry shells, animated noise or refraction are added.
- Clothing names/categories choose cotton, denim, wool, knit, silk or leather
  roughness/sheen and meter-scaled micro normals. Authored maps remain. Wool fuzz
  is sheen, not fibers. A combined suit mesh uses one inferred fabric per material;
  individual garments give more control. Glasses, teeth and tongue are preserved.
- `skin_detail` and `hair_detail` accept 0..2 (default 1). Zero removes added pore
  or strand variation. Rest-space attributes follow skinning and face morphs,
  without world-space texture swimming. Save/open and separate-process video
  snapshots retain native materials without Python handlers or downloads.
- glTF export temporarily uses a bake-free PBR graph: original base/alpha and
  normal images, skin reflectance factor and tuned scalar roughness (or authored
  roughness maps). `material_fallback` reports lost
  SSS, procedural masks/microdetail, corneal/iris shading, the eye-linked light
  and hair sheen/anisotropy.
  Scene material graphs are restored even on export failure. `.blend` keeps all
  detail; the portable fallback does not bake procedural effects.

`render_options.materials_cost_factor` is 1.15 for enhanced characters, weighted
by the fraction of MPFB characters upgraded (not environment material count).
Draft is 1.0; full-strength clay/anime shader replacement is 1.0. The factor is
multiplied into estimates and divided out of machine learning once, alongside
style/look/nature factors. Actual CPU costs depend on framing and alpha coverage.

Measured after review corrections: CPU llvmpipe, two clothed MPFB characters,
512×288 / 16 Eevee samples, four Blender threads and `LP_NUM_THREADS=4`,
no look/style. ABBA order; every timed frame follows a 320×180 warm-up.
Two samples per material include render setup/restoration and PNG output.

| framing | MPFB s/frame | enhanced s/frame | ratio |
|---|---:|---:|---:|
| close-up | 28.57 | 24.57 | 0.860× |
| medium | 50.76 | 41.83 | 0.824× |
| wide | 43.39 | 33.05 | 0.762× |

Shared CPU load causes substantial absolute variation: MPFB close-up bookends
were 14.67 and 42.46 s. These paired results meet the medium ≤1.25× budget;
they do not establish a universal speedup or comparable absolute times between
framings. Keep the conservative 1.15 estimate factor. Raw samples/warm-ups:
`output/material_review_v2/benchmark.json`. Shader cache: `output/mesa_cache/`.

Verify only on **9971**, workspace `$PWD/output`, one owned Blender at a time:
`tests/test_materials.py` → `MATERIALS UNIT OK`;
`tests/e2e_smoke.py --materials-only` / `--mpfb-only`;
isolated `--render-style-only --serial-video` and `--cinematic-only --serial-video`.
`tests/materials_review.py --stills --bench --clip` reproduces the current
seven-person, five-light close/extreme-close matrix and movie through MCP.
Use `--cast`, `--looks`, `--shots`, `--qualities` and `--reuse` for resumable batches.
`--engine cycles --tag cycles` checks Cycles; `--film --tag film` uses film style
with f/8 eye-plane DOF. The earlier `tests/materials_visuals.py` also covers
medium framing, six fabrics and proxy repairs.

Current evidence: `output/material_review_v2/`; `metering.json` defines
unobscured Lina forehead/cheek ROIs. `luminance.json` reports mean sRGB RGB,
encoded Rec.709 Y-prime and decoded linear luminance from original PNGs.
The revised pooled Y-prime values are studio 0.638, soft 0.660 and misty 0.591
(target 0.55–0.70); earlier enhanced values were 0.838, 0.856 and 0.793.
The harness explicitly sets square scene dimensions and asserts frame sizes;
the preview MCP wrapper currently drops null height for scene cameras.
Video checks prepare through `render_video`, stop the editor, then run its
native snapshot worker. The 36-frame, three-second talking clip decodes;
distinct static frames have MAE 0.0 for full image, hair and skin.

Canonical current close/extreme-close sheets: `output/material_sheets/`;
movie: `output/renders/materials_talking_3s.mp4`. Earlier sheets, including the
older medium-shot matrix, are archived in `material_sheets/iterations/review_v1/`.
See `output/skin_result.md` for all measured results, paths and inspected limits.
No dynamic cloth/hair collision or fiber/vascular simulation is implied.

## Hands
`set_hand_pose(character, shape, side)` poses the fingers on any rig with finger bones
(MPFB game_engine/mixamo/rigify, Mixamo, Rigify human); curl axes are derived from the
hand geometry, so shapes look the same on every skeleton. Shapes: relaxed, open, palm,
beat, point, fist, thumbs_up, peace, three, four, ok, grip. Pair with arm poses, e.g. `apply_pose(rig,
"point_forward")` + `set_hand_pose(rig, "point", side="right")`; `keyframe=True, frame=N`
to animate. Mannequins from `create_human` have no fingers. The collision pass
preserves finger keys; it does not resolve individual finger contacts.

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
  bounded baked collision repair (see **Collision pass**) preserves contact targets.
  There is no dynamic full-body or material-accurate cloth solver; inspect remaining skips.

## Collision pass

`resolve_collisions(characters=None, frame_start=None, frame_end=None, parts="all",
clearance=0.01, max_iterations=8, report_only=False)` measures and repairs baked
performances in meters. None characters selects visible humanoid rigs; a body/rig
name list selects a subset, with other visible humanoids still acting as colliders.
Ranges are inclusive, at most 24000 frames. Parts accepts all, arms, props, legs,
torso, clothes, or a list. Clearance is 0..0.1 m; iterations is 1..32.

- Evaluated rest skin fits posed head/chest/abdomen/pelvis ellipsoids and neck/limb
  capsules, including hands/feet. Basic, Rigify, MPFB and recognizable humanoid rigs
  use their measured dimensions and bone frames, including stylized proportions.
  Uniform rig scale is supported. Adjacent shoulder/armpit envelopes may overlap
  naturally and are excluded from self upper-arm/torso checks.
- Static visible furniture, desks, tables, armrests, laptop parts and terrain use
  evaluated triangle BVHs at the first frame. Closed meshes use parity for inside;
  open surfaces are two-sided. Held props use deterministic surface samples plus
  envelopes for other hands, including historical live attachment owners.
- Arms/props first receive small wrist-target push-outs and outward/up elbow poles,
  using the shared two-bone IK with hierarchy-level batching. Wrist world orientation
  and finger keys remain. Knees can change pole while ankle position/rotation stays
  fixed. Chest offsets are capped at 3 cm and compensate both wrist targets. Hips,
  roots, soles, seat anchors, face/lip keys, attachments and camera are retained.
  Elbows retain authored high poses; newly raised elbows stop within 5 cm of the
  shoulder (also capped by measured height) to preserve natural phone/face contacts.
- Corrections have anticipatory, quintic .2 s shoulders and ease around protected
  contacts. Wrist/elbow corrections over 8% of measured height, unreachable targets,
  constraint residuals and root/seat conflicts are skipped with reasons. Saved heart,
  temple/chin, lip/ear, keyboard/book and paired interaction contact intervals protect the wrist;
  elbows can still change. Sparse authored curves outside the range keep their
  original Bezier segments. New body authoring invalidates overwritten contact records.
  An evaluated IK failure, increased penetration or a new held-prop jump rejects
  the character's physical correction over the whole interval, retaining the original
  continuous performance and reporting the rejection rather than inserting a pop.
- Loose garments re-bake their owned elastic chains with scene BVHs and posed peer/
  arm colliders, retaining the last cloth stiffness/damping/gravity/wind settings
  separately from hair. Sampled
  evaluated garment vertices independently report remaining scene penetration.
  The final leg enclosure has priority when furniture and body constraints conflict;
  remaining garment/furniture intersections are reported for restaging.
- Results contain per-character/part counts, maximum penetration before/after (m),
  corrected frame lists, grouped skipped conflicts (frames/reasons), displacement
  limit skips, wall-stage timings and total CPU time. Counts are sampled point/collider
  pairs inside the clearance shell, including near contacts, not triangle counts;
  penetration maxima measure physical overlap. Final metrics re-read the baked poses.
  report_only changes no keys, contact metadata, garment setup, project or camera.

Automatic after talk_gestures, action animate (including type/drink), interact,
sit_on, dialog and script_to_scene; each accepts collisions=False. Orchestrators
run once after performance; script cloth bakes once in this final pass. Re-run after
later pose/attachment/furniture edits. review_scene adds sampled precise static-BVH
and body-envelope checks; fix=True batches one bounded pass for the affected cast.

Limits: body envelopes and discrete samples are approximations, not exact continuous
mesh contact or full-body dynamics. Fingers, hair/furniture contact, moving furniture,
nonuniform rig scale, exact garment surfaces and full cloth/self collision are not
solved. Existing deep intersections, pinned garment regions, extreme mixed heights,
protected contacts and unsuitable seat placement can remain. Inspect the explicit
skips and side/three-quarter Eevee images; a clean proxy result does not guarantee
that every rendered vertex clears. No network, downloads, handlers or physics caches.

Verify only on **9970**, workspace `$PWD/output`, one owned Blender at a time:
`tests/test_collide.py` prints `COLLIDE UNIT OK`; `tests/e2e_smoke.py --collide-only`
checks faults, invariants and a 720-frame/two-MPFB CPU benchmark. Resume faults with
CHAR3D_COLLIDE_RESUME=interactions|cloth|bench; bench reuses its saved input project.
`tests/collide_visuals.py` renders saved before/after Eevee pairs without loading MPFB's
builder. Results/sheets: output/collide/; full record: output/collide_result.md.
Regression selectors: --interaction-only, --secondary-only, --script-only,
--review-only --serial-video and --motion-only --motion-bake-only. Optional
CHAR3D_COLLIDE_SHAPE_ONLY=1 uses <=384 px workbench for regression stills; material
collision evidence is rendered separately by collide_visuals. Keep 9876 untouched,
never install into the shared .venv, and shut down the owned engine after checks.

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
- `face_life(character, frame_start=None, frame_end=None, intensity=1, seed=3,
  listen_to=None, clear=False)` adds deterministic micro-expressions, held gaze and
  micro-saccades, varied full/half blinks, eyelid follow, listener smiles/brows and
  subtle chest/shoulder breathing. Run after expressions, speech, gaze and cameras;
  rerun after editing these layers. `listen_to` is a rig name or list. Saved sentence
  emotions from `auto_expression`, phrase rhythm and camera cuts inform the score.
  Without word times, its own voice/viseme envelope supplies phrase rhythm; this
  creates no transcript or subtitle words.
  `talk_motion(..., life=1)` enables it; dialog/script/film builds enable it by default.
  Pass `life=0` to opt out, or `face_life(..., intensity=0)`/`clear=True` to remove just
  this layer in the requested range. Intensity is 0..2. Seeded reruns replace keys.
  Owned `__c3d_life_` relative morphs preserve original viseme, face, body and arm
  curves. Shared multi-slot Actions are scoped to each mesh's own slot.
  Mouth micro-motion is suppressed during words and active articulation,
  including m/b/p closures. Linear samples avoid overshoot. Breathing is a tiny
  rest-space morph on body/clothes, carried by existing skinning, not bone edits.
  Native morph animation survives save/open and video snapshots. Optional authored
  `pupilDilate`/`pupilSmall` targets receive slight light adaptation; stock MPFB has
  neither, so eyeball scale stays intact. Reactions are local heuristics, not a
  psychological model; custom NLA/driven face controls can require manual blending.
- `auto_blink(character)`: natural blinks over the scene range. Use it or `face_life`
  whenever the face is visible for more than ~2 s. New builds use one life schedule;
  manual scenes retain authored blinks, with a one-second refractory gap for added blinks.
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
  lead speech and release seconds follow it. Audible voice regions respect strip trims;
  gaps <= 0.5 s merge so the bed recovers in longer pauses. Legacy untagged strips
  still count as voice. Word timing is used where the speaker has no matching strip.
  Unreadable or retimed voice strips use their visible timeline span.
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
  `medium_full` so hands are visible. A bounded collision pass runs afterwards by default;
  collisions=False disables it. Semantic heart/temple contacts retain their wrist targets.
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

## Background music

`auto_music(mood="auto", duration=None, tempo=None, key=None, intensity=0.6,
seed=0, volume=0.35, follow_cuts=True, follow_emotion=True, sections=None,
fade_in=1.0, fade_out=2.0, clear=False, backend="auto")` composes an original offline score, adds
an owned `kind="music"` strip, then runs `duck_music` (-12 dB under speech).
Duration defaults to the inclusive scene range; it does not extend the timeline.
Reruns replace only generator-owned music; clear removes only those strips.
Manual music/voice/Foley stay intact. Save/open retains the score and volume keys.

`backend="auto"` (default) uses installed GeneralUser GS 2.0.3 through
TinySoundFont offline rendering; `backend="soundfont"` requires it, and
`backend="synth"` selects the original numpy instruments. Auto falls back to synth
when the font or renderer is absent. No runtime downloads or PyAudio playback.
Install explicitly with `scripts/install_soundfont.sh` (asks confirmation; `--yes`
accepts): 32,319,396-byte bank + license, verified sizes/SHA-256 in
`scripts/soundfonts.tsv`, tinysoundfont 0.3.7 `--no-deps`. `CHAR3D_SOUNDFONT`
overrides the bank path. `CHAR3D_MUSIC_PYTHON` overrides the compatible renderer
Python (default repository `.venv/bin/python`); Blender uses a short subprocess
because its bundled Python has a different native-extension ABI. The installed
bank license permits private and commercial music creation.

The GM arrangements use guitar/piano, strings, woodwinds, brass, choir/pads,
mallets, acoustic/fingered bass and MIDI channel 10 drums. Intro/A/B/outro dynamics,
voice-led inversions, bass approaches, answering melodies, pickups/fills at form
changes/cuts, and 20 Hz CC11 expression complement velocity humanization and CC7.
`renderer` reports actual backend, bank hash and zero-based GM programs, retained
in saved scene metadata and film reports. SF spectra are measured independently
from numpy; sampled flute/nylon guitar need not match a synth's high-band ratios.


Moods: happy/ceria, warm/hangat, sad/haru/sedih, romantic/romantis,
tense/tegang, mysterious/misterius, epic/epik, calm/tenang, playful/lucu,
nostalgic/nostalgia, dreamy and nusantara. Nusantara uses original pentatonic
pelog/slendro-inspired equal-tempered subsets, metallophone/bell and low gong
timbres; it does not reconstruct regional tunings, repertoire or ensembles.
Auto uses saved sentence/beat emotions (including explicit expression cues), then
cinematic look, weather and location. Golden hour suggests warm; night mysterious;
rain nostalgic. Inference is a small local lexicon, with the same limits as
`auto_expression`. Camera cuts/title starts receive quiet tonal accents without
changing tempo; emotion peaks shape swells/drops. Ending cues resolve to tonic.

`tempo` is 40..180 BPM; `key` e.g. `D minor`, `F# major`; intensity is 0..1.
`sections=[{"frame":49,"name":"reveal","intensity":0.8}]` adds dynamic accents.
Result includes sections/frames, accents, mood/key/tempo, content hash/path,
measured loudness and timings. The fallback numpy synthesis uses additive/FM keys, band-limited
strings/pads, Karplus–Strong plucks, bass, bells and short filtered percussion;
there are no downloaded samples, AI services or stored melodies.
Keys cycle through all twelve tonics across moods and seeds, with octave folding
to comfortable registers. Moods also choose their lead, note density, bass pattern,
drum feel and mix levels. Strings use 2x polyBLEP, FM uses 4x reconstruction, and
plucks resolve the delay/loss loop's modal poles instead of undersampling narrow
resonances on an FFT grid. A flat 14 kHz passband retains natural air; the 14–16 kHz
transition is an antialias guard, not a blanket timbre low-pass. The bass is G1..Bb2
with controlled sub-30 Hz energy. Mastering leaves this instrument balance intact.
48 kHz stereo 16-bit PCM lives under `imports/audio/music/generated/` by SHA-256
of PCM. Mastering targets about -16 LUFS before strip volume/fades/ducking, with
4x sinc-estimated true peak <= -1 dBFS. K weighting and absolute/relative gates
are BS.1770-like, not a certified meter. Pure `compose(..., loop=True)` + `render`
supports periodic tails/reverb and seamless endpoints (explicit tempo requires
whole four-beat bars); the scene tool writes one
duration-matched cue. Duration is limited to 600 seconds per composition.

Scripts/films default to `music="auto"`; `MUSIK:` / `MUSIC:` headers choose a mood,
`otomatis`/`auto` or `tanpa`/`none`. `music=None` disables generated music globally;
an explicit mood overrides headers. `sound=False` controls Foley separately.
Parse-only plans report `plan.music` (request/mood/tempo/key) without rendering.
Film scenes keep preview scores in their blends. `render_film` replaces those in
temporary snapshots with a global score through cards/cuts: adjacent equal moods
share one composition when key/tempo/seed/intensity/volume also match; changed
settings or moods crossfade around a cadence. Film speech
is ducked on its final global timeline. Manual scene music remains in the clips.
Re-render after editing timing/emotions/cameras; no adaptive audio plays at runtime.
This is a compact rule-based accompanist, not an orchestral or cultural simulation.

Verify: `tests/test_music.py` → `MUSIC UNIT OK`; `--demos` writes every 30 s mood
to `output/music_demos/` with `metrics.json` and score JSONs.
`--demos --soundfont` writes the same twelve 30 s cues to `output/music_demos_sf/`;
metrics include backend and render seconds. Isolated checks:
Spectra use the first 20 seconds of the decoded WAV, mono `(L+R)/2`, Hann FFT:
power below 120/30 Hz, above 2/4/8/16 kHz, air 8–16 kHz and centroid. Tests also
measure folded aliases inside the audible band, against an uncorrected saw;
near-zero energy above 16 kHz by itself does not prove low aliasing.
`CHAR3D_PORT=9975 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python
tests/e2e_smoke.py --music-only` (low-resolution workbench film + PyAV AAC checks).
Use `--audio-only` / `--auto-sfx-only` with `CHAR3D_AUDIO_CLAY_ONLY=1` for audio
regressions without Eevee. Shut down the isolated engine after checks.
The same clay flag makes `--film-only` use low-resolution workbench checks.
`CHAR3D_AUDIO_NO_ASR=1` keeps synthetic-vowel audio checks offline and lighter;
supplied-word/phoneme timing remains covered without loading Whisper.

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
- **f5**: optional, natural offline Indonesian cloning with a single persistent
  JSON-lines subprocess in `~/.local/share/char3d/f5-venv/bin/python` (override
  `CHAR3D_F5_PYTHON`). Torch never enters the MCP/Blender process. `cancel_tts()`
  stops/reaps it and releases RAM; next use restarts it. Timeout is 600 s per
  operation (`CHAR3D_F5_TIMEOUT`), with clear offline/missing-file errors.
  `scripts/install_tts.sh f5` asks confirmation (`--yes` accepts) and uses a
  separate CPU venv, never the MCP venv. Recorded model/vocoder bytes and SHA-256
  are in `scripts/f5_assets.tsv`: 1,348,431,976-byte Indonesian checkpoint,
  54,365,991-byte Vocos weights and 461-byte config, plus a 11,255-byte vocabulary
  bundled with pinned f5-tts. Already cached Vocos files are usable read-only.
  All inference runs with HF_HUB_OFFLINE=1 and blocked network sockets; supplied
  transcripts avoid Whisper/ASR downloads. WAV decoding uses libsndfile because
  optional torchcodec can have incompatible FFmpeg/CUDA libraries. Text chunks run
  serially on the shared model/cache, with native torch CPU threading underneath.

  Code is [MIT](https://github.com/SWivid/F5-TTS/blob/main/LICENSE), the
  [Indonesian finetune](https://huggingface.co/anantoj/f5-id-v1) is labelled
  Apache-2.0, and upstream base weights are CC-BY-NC: personal/non-commercial use.
  Bundled package example clips are not used: their speaker/recording permissions
  are not separately established by the code license. Builtin `f5:female_adult`,
  `f5:male_adult`, `f5:elder`, `f5:child` references are generated from our installed
  Piper output at first synthesis, cached inside workspace imports (no home writes).
  These are synthetic variants of one speaker, not four trained speakers, and keep
  Piper news_tts's personal-use limitation. Catalog/parse-only never generate them.
  Casting selects gender/age-tagged refs and applies only small pitch variation.

  For your own/permitted voice, record a clean mono WAV, 8–12 seconds, one speaker,
  quiet room, normal pace, no music/reverb/clipping; transcribe every spoken word.
  Use `text_to_speech("Halo!", engine="f5", voice_reference="audio/my_voice.wav",
  reference_text="Exact words in the reference")` (relative to imports), or register
  `tts/f5/voices/Ana.json` with `{"voice_reference":"my_voice.wav",
  "reference_text":"Exact transcript", "language":"id", "gender":"female", "age":28}`;
  relative paths in JSON resolve beside it. Do not use Edge/Microsoft speech or an
  unpermitted real person's recordings as references.

  `script_to_scene(script, tts_engine="f5", language="id")` works with normal casting.
  Results include measured wall/CPU time and real-time factor; cache keys include
  reference content, local model/vocab/vocoder identity and inference settings.
  `CHAR3D_F5_STEPS=8|16|24|32|64` chooses quality/cost (default 32),
  `CHAR3D_F5_THREADS=2` controls CPU threads; experimental
  `CHAR3D_F5_QUANTIZE=1` quantizes linear layers to int8, with its own cache identity.
  CPU generation is much slower than real time on the i5-4460; Piper stays default.
  Measured with four CPU threads: draft 8-step sentences take roughly 40–46 s for
  2–3 s speech; the current 32-step smoke takes 167.922 s wall / 629.306 s CPU for
  2.187 s raw speech (76.79 RTF; 2.267 s normalized WAV). These are local measurements,
  not guarantees; default thread count is two. The 8-step child reference has worse
  Whisper-tiny WER than its Piper comparison, so do not assume every F5 preset improves speech.
  Run `tests/audio2_demos.py` for 10 Indonesian sentences per builtin voice plus
  matched Piper WAVs, Whisper-tiny WER, F0/duration/loudness/peak and latency metrics
  in `output/voice_demos_f5/`. Quality scores are measurements, not a claim that
  synthetic references reproduce the variety/naturalness of licensed recordings.
- **chatterbox**: explicit online wrapper of the existing free Hugging Face Space
  (MIT, tiny GPU quota, may queue/fail, **no Indonesian**). Use `chatterbox:ms` only
  when Malay is acceptable. Text is sent to Hugging Face/ResembleAI. The existing
  `ai_text_to_speech` job API remains unchanged.

`list_voices(language="id")` reports installed engines, licenses, privacy, install hints
and voices. The default catalog and all casting are offline; explicitly requesting
`engine="edge"` refreshes its list. `text_to_speech(text, voice=None, engine="piper",
language="id", rate=1.0, pitch=0.0, gender=None, output=None,
voice_reference=None, reference_text=None)` returns `path` relative to
`imports/`, `duration_s`, `engine`, `voice`, `cached`, and online `privacy`. `rate` is a
0.5..2 multiplier; `pitch` is -12..12 semitones relative to the raw voice. `output`
optionally copies the cached WAV to another `.wav` path inside `imports/`.
All engines normalize to 48 kHz mono 16-bit PCM, target active RMS ~-18.4 dBFS with
gentle syllable compression, a -2 dB true-peak ceiling, short fades and 40 ms
silence pads. Peak limiting can reduce RMS for high-crest audio. Cache keys cover engine/version/model, voice, exact text,
language, rate, pitch and DSP version under `imports/audio/tts/`.
Piper with the `alignment` extra (`piper-tts[alignment]`, pulls `onnx`) also returns
`phone_events`: eSpeak phones mapped to char3d phonemes, shifted onto the normalized
WAV and cached beside it as `.phones.json`. Script/dialog lines pass them to
`lip_sync_audio(..., phone_events=...)`, so mouths follow the synthesizer's own timing;
sub-frame m/b/p keep a full closure. Without alignment support, or when the timing is
rejected (`phone_timing` in the result), transcript timing is used with a warning.

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
  `directed` (aliases `emosi`, `emotional`) edits from the sentence-emotion curve:
  establishing groups, OTS/singles, tighter peaks, listener inserts over continuing
  speaker audio, and a wider ending echo. `dialog` keeps its `mixed` default.
  `stage_dialog(..., camera="directed")` optionally covers existing timed speech;
  without speech it establishes the staged cast. Omit camera for placement only.
  Directed results include `emotion_curve`, visible `reactions`, and each shot's
  `reason` (role/emotion/intensity/phase). Explicit camera cues always override it.
  An automatic insert shortened below one second by a closing cue is removed;
  the preceding view holds until the authored closing cut.
  Energy comes only from audible voice samples, alongside saved `char3d_emotions`,
  line/body emotion and punctuation. This is a local heuristic, not story analysis.
  Reactions begin about .3 s after a trigger word, on separate `__c3d_reaction_`
  brow/eye/cheek/corner morphs; articulation, gaze, blinks and face_life stay intact.
  Cuts use word gaps quantized to the video grid (<= half-frame boundary error),
  protect the speaker's first second and hold at least a second. Sad/tender passages
  hold longer; >30 s scenes reserve a five-second breath. Tight shock accents require
  a strong explicit surprise emotion cue. Short scenes/absent word gaps can limit
  variety or reactions; missing face targets warn. Inspect actual listener faces.
  One extreme close-up is reserved for a real silent peak; talking portraits use
  close-up/full-face coverage. Returning singles vary size or move within twelve
  seconds. `camera_shot` also protects talking mouths and limits ECU count.
  Explicit camera cues retain their timing and direction; an unsafe talking ECU or
  additional ECU is refitted to close-up, reported in `requested_shot`/`framing_notes`.
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

Emotional coverage verification: only port **9972**, workspace `$PWD/output`;
`tests/test_emocam.py` prints `EMOCAM UNIT OK`. `tests/e2e_smoke.py --emocam-only`
builds argument/reunion/good-news fixtures and compares directed/mixed coverage on
identical saved performances. Evidence lives in `output/emocam/`; use
`CHAR3D_EMOCAM_REUSE=1` to recut saved fixtures or `CHAR3D_EMOCAM_CASE=argument`
(also reunion/good_news) for one case. Regression stills can use
`CHAR3D_TEST_WORKBENCH=1` to cap them at 384 px; final emotional stills use Eevee.
Stop the owned engine after checks; never use 9876 for verification.

## Script → scene
`script_to_scene(script, name=None, environment=None, lighting="studio", camera="directed",
subtitles=True, language="auto", seed=0, build=True, sound=True, body_language=True, voice=True,
tts_engine="piper", voices=None, look=None)` composes the existing tools into
a complete scene for 1–4 characters. Directed coverage is the default; explicit
KAMERA/CAMERA cues keep priority. Results include a smoothed `emotion_curve` and
visible listener `reactions`; `camera="mixed"` retains the original coverage. `build=False` returns a deterministic normalized
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
kuda, braid/kepang, afro), hair colour attached to the word rambut/hair (`rambut bob
merah kecokelatan`, `rambut cokelat`, `pirang`, `hitam`, `uban`, `red bob hair` ->
dict `hair_color`), skin tone (`kulit cerah/terang/putih`, `kulit sawo matang`,
`kulit gelap`, `light/fair/medium/dark skin` -> dict `skin_tone`), outfits, facial
hair, accessories or exact MPFB catalog names.
For realistic casts, generic hair words and the default hair prefer fuller installed
CC0 pack grooms: bob -> `toigo_curled_under_bob`, short/pendek -> `culturalibre_hair_02`
(`short02` -> `culturalibre_hair_05`); the system bob01/short01 cards read as a helmet.
Without the hair01 pack, or with an explicit dict `hair`/catalog name, the requested
asset is kept. Hair colour descriptors tint whichever groom is used.
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
Camera/music/silence cues are documented in **Directing method** and reported in parse-only plans.
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
Initial dialog in podcast_studio/news_desk/office seats the cast together when no
sit/stand/walk/enter/interact direction is authored. It adapts the standing-height desk
to the chairs (podcast chairs move to 72% of their spacing, about 1.25 m apart) and folds microphones below the mouth, aimed toward each guest.
Guests lean ~9° onto the desk with palms resting on it (`sit_on(hands="desk")`): the
hand lifts its thumb side ~15° and fingertips ~10° with open fingers, as a real resting
hand does, then the wrist target is re-solved so the lowest evaluated hand/finger skin
sits 3 mm above the desk for that character's hand thickness. Flat palms with relaxed
fingers sank the thumb ~4-5 cm and the fingertips ~3 cm into the desk; a fixed wrist
height left thick hands floating ~1.5 cm. Talk gestures still lift the arms. Desk-seated
guests' microphones sit beside the chin line, clear of chest gestures. Desk-seated talkers
turn their heads at most 35° from the body toward a partner (about three-quarter to a
frontal camera); the eyes cover the rest, so faces stay readable in two-shots.
Default `studio` lighting in podcast_studio becomes `podcast` (result `lighting`).
The default podcast set uses procedural walnut, matte black hardware, dark leather
chairs, a deep navy wall and thin LED edges on the acoustic panels (any explicit
`color_theme` keeps the previous palette). The walnut is lengthwise noise grain with
fibre roughness/bump; microphones and their desk bases are rebuilt as 48-segment
bevelled cylinders (anodized body, shader woven grille, no wire geometry; bases keep
their size and stay on the desk top); panels and wall get fine
roughness/bump noise. The grille only reads at 1080p or in close-ups.
Podcast scenes raise realistic characters' face_life intensity 1.65x (max 2) so
listener reactions read in held desk shots; VRM actors keep the normal intensity.
Authored physical blocking and world stages retain priority. Results report `staging`.
Hand-made `stage_dialog` in an existing desk set has the same default; `desk=False`
keeps standing staging, and `dialog(stage=False)` preserves placement.
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
Limits inherit the component tools: bounded proxy/BVH collision repair can skip conflicts;
static seats, one held prop per hand, rule-based text pronunciation and approximate
text/audio alignment remain. Outfit/accessory selection does not fit geometry. The final
collision/garment bake reduces supported intersections; inspect posed Eevee frames and skips.
Declare characters before using them; invalid references fail with a clear error.

## Films (multi-scene)
`script_to_film(script, name=None, build=True, scene_index=None, ...)` reuses the
single-scene pipeline, saving `projects/<name>/scene_01.blend`, etc., and `film.json`.
Directed coverage is the default. Each scene stores its own `emotion_curve` and
listener `reactions`; an opening widens after the previous scene ends close.
Explicit camera cues retain priority across rebuilds.
It replaces the editor scene during building; save outstanding work first.
`build=False` returns a deterministic storyboard without Blender/file/audio/network
changes. Single-scene scripts still work with `script_to_scene`, with their original
result shape. That tool rejects ADEGAN/SCENE headers and points to `script_to_film`.

Text adds `ADEGAN 1: Kafe` / `SCENE 1:` / `ADEGAN:` / `SCENE:`. Each scene accepts
LOKASI/LOCATION, SUASANA/LOOK/MOOD, CUACA/WEATHER and PENCAHAYAAN/LIGHTING.
Declare characters once (a bare `ANA (perempuan, 28)` is valid for films), or at
first dialogue. References are case-insensitive; up to four global characters.
Scene casts are inferred from speech/actions/targets, or specified by dict `cast`.
A silent establishing scene uses all declared characters unless `cast` is supplied.
Identity/build parameters, global outfit seeds and voice casting persist across scenes.
Place `[Ana berganti baju formal]` / `[Ana changes into formal]` **before** the scene's
beats to change its outfit for that scene and later ones. No animated wardrobe swap.

Put `[TRANSISI: dissolve 0.5 detik]` / `[TRANSITION: dip_black 0.5 seconds]` between
scenes; default `cut`. Dissolve/crossfade overlaps adjacent segments by the requested
frames. fade_black/dip_black/fade_white keep a cut and dip around it. Transitions must
fit adjacent segments and cannot overlap one another. `KARTU: Sore harinya...` /
`CARD:` inserts a two-second centered card before the scene. Dict cards accept
`{text, duration_s}`. Incoming transitions lead into the card when present.
Dict film: `{title, characters:[...], scenes:[{name, environment, look, weather,
lighting, card, transition_in:{kind,duration_s}, cast?, beats:[...]}]}`.
Dict costume beat: `{do:"outfit", who:"Ana", outfit:"formal"}`.

`film_info(name)` reads the canonical JSON; each blend embeds a manifest snapshot.
`open_film_scene(name,index)` opens a one-based scene for preview/editing. Save changes
with `save_project` to the returned project path; timeline changes refresh manifest
offsets. Keep a common fps. `scene_index=N` rebuilds only that scene if other source
scenes are unchanged; a costume change affecting later scenes requires rebuilding all.

`film_render_options(name,quality,vertical,calibrate)` aggregates existing per-scene
`render_options` and machine calibration. **The owner still chooses the resolution
before preview/final/Cycles renders.** `render_film(name,path,quality="draft",
resolution=None,wait=False,resume=True)` prepares existing `render_video` snapshots,
runs one worker at a time, then composes one H.264/AAC MP4 in Blender VSE. Poll
`render_status` for whole-film/per-scene progress; `cancel_render` stops pending/active
workers. Completed scene clips are cached by blend SHA-256 + render settings; changed
projects invalidate only their clip. External assets changed in-place require
`resume=False`. The live editor is restored from a temporary snapshot, preserving
unsaved edits and its logical save path. Render only saved scene edits.

Each clip contains its own voice/music/Foley. Transitions also fade audio; cards and
silent scenes retain a continuous silent AAC bed. Captions are composed globally and
an `.srt` is written beside the film, including card/dissolve offsets. All scene-level
looks, graphics, weather, camera, voice and motion limitations still apply. Draft is
workbench; inspect Eevee stills for materials/continuity. No system ffmpeg is required.

Recipe: `script_to_film(script,build=False)` → `script_to_film(script,language="id")`
→ for each scene `open_film_scene(name,index)` → `render_frames([8],camera="scene",
engine_name="eevee",size=512)` → inspect/edit/save → `render_film(name,quality="draft")`
→ `film_render_options(name,quality="final")` → owner selects resolution → render.
Studio shows a storyboard, build/rebuild progress, an Adegan switcher, whole-film
resolution estimates and playable MP4s in Galeri. Director drafts may optionally use
several scenes for multiple places or >45-second ideas.

Verify: `.venv/bin/python tests/test_film.py` prints `FILM UNIT OK`; isolated
`CHAR3D_PORT=9996 CHAR3D_WORKSPACE="$PWD/output" .venv/bin/python tests/e2e_smoke.py
--film-only` checks MPFB/Piper, offsets, AAC continuity, transitions, cache and cancel.

## Remote rendering

`render_video(..., target="local"|"name")` and `render_film(..., target=...)`
retain the local defaults. `render_options(..., target=...)` and
`film_render_options(..., target=...)` report per-target time and USD estimates.
`remote_targets()` lists configured targets and durable jobs, instance IDs, estimated
running cost and pending cleanup; `stop_target(name)` cancels all **char3d-owned** jobs
and terminates their rented instances. Unrelated account instances are never stopped.
No automatic resume or replacement of a stopped/preempted paid machine occurs.

Create `~/.config/char3d/targets.json` yourself, outside the repository:
```json
{
  "devodo": {
    "kind": "ssh", "host": "devodo", "jump_host": "reyhan", "user": "reyhan",
    "remote_dir": "/opt/char3d/remote", "blender": "/opt/char3d/blender-5.2.4-linux-x64/blender",
    "device": "cpu", "max_parallel": 1, "threads": 4, "max_hours": 4
  },
  "rented": {
    "kind": "runpod", "gpu_type": "NVIDIA GeForce RTX 4090",
    "image": "YOUR_OWN_PREPARED_BLENDER_IMAGE", "public_key": "~/.ssh/id_ed25519.pub",
    "remote_dir": "/tmp/char3d", "blender": "/opt/blender/blender", "device": "optix",
    "max_hourly_usd": 1, "max_budget_usd": 3, "max_hours": 2, "max_parallel": 1
  }
}
```
For Vast.ai use `kind="vast"` and its GPU name (for example `RTX 4090`). The owner
creates/funds the provider account, configures their SSH public key and prepares the
image. Paid adapters create on-demand single-GPU containers, without persistent volumes,
and **terminate**, rather than merely stopping, after completion/failure/cancellation.
Vast offers must have free inbound/outbound transfer. RunPod defaults to Secure Cloud;
`cloud_type="COMMUNITY"` is explicit. No Colab/Kaggle/free-tier workaround is supported.

Put `RUNPOD_API_KEY=...` / `VAST_API_KEY=...` only in `~/.config/char3d/env` with
mode **600**. Runtime reads that file without shell evaluation; environment-only keys
are deliberately ignored. Keys are sent only in HTTPS authorization headers to the
official provider endpoint, with redirects disabled. Never put secrets in targets,
scripts, project files or logs. Target fields are allowlisted. SSH/rsync use
`-F ~/.ssh/config`, BatchMode and strict host-key checking; a jump uses an explicit
ProxyCommand with the same user-only config. Password prompts are not supported.

Money and upload consent are separate:

1. First job on a target returns `consent_required`, describing the upload. Repeat
   with `consent_upload=True`. Consent is stored by target configuration fingerprint;
   changing the target requires fresh consent.
2. A paid render returns `quote_required`: GPU, API hourly price, calibrated or
   explicitly uncalibrated runtime, startup allowance, estimated USD total and caps.
   **No instance is created on this call**, even with `confirm_cost=True`.
3. Show the quote to the owner. Repeat the same arguments and caps with its
   `quote_id` and explicit `confirm_cost=True`. Quotes expire after ten minutes and
   are single-use. A quote renders the prepared snapshot, preserving the quoted scene.
   Changing settings/target/limits requires another quote. Estimates from render_options
   are advisory; the actual render supplies the confirmable quote.

The provider offer is fetched again immediately before allocation; a changed offer or
higher price requires a new confirmation. The allocated instance's rate is also checked.

Both target caps and smaller per-call `max_budget_usd`/`max_hours` apply per job. Provisioning,
transfer and render time count; 30 seconds are reserved for teardown. A detached local
supervisor owns provider cleanup, time/budget/idle watchdogs and persistent state under
`output/remote/`. It survives MCP exit, reattaches by job ID after a restart, and retries
unacknowledged termination visibly as `cleanup_pending`. The remote process also has a
credential-free time/idle watchdog. **Keep the controlling laptop awake and online.**
No client can guarantee a provider invoice cap while the controller is powered off or
the provider API is unavailable. Use provider account spending limits/alerts as the
independent backstop; tax/rounding/storage and provider metering can differ. Provider
billed seconds/cost are reported from RunPod billing history when published and from
instance totals when exposed (history may lag and is labelled provisional); otherwise
`cost_so_far_usd` is explicitly an elapsed-time estimate, never an invoice.

Privacy: scene geometry/animation/native materials, referenced MPFB/user textures,
images, fonts, voice/music/Foley WAVs, and title/caption images leave this machine.
The scene must contain native baked data. Look/style overrides are saved into the
snapshot and grain is updated by the standalone worker. No MPFB installation or
engine package is needed on the remote host. Missing assets, linked libraries,
external simulation caches, volumes, UDIM and image/movie texture sequences are
rejected; convert these to supported native data first. Absolute source paths are
remapped to content hashes. Generated SRT/CREDITS/treatment files stay local; verified
MP4s are downloaded atomically. Films render scene clips remotely and compose locally
using the original Blender VSE script, with original captions/music/cards/transitions.
Remote film cache keys also include external asset bytes and target/device settings.

The remote worker needs Linux or Windows, system Python **3.9+**, and Blender's
system graphics/audio libraries. Linux uses rsync; Windows uses OpenSSH SCP's SFTP
protocol, without rsync. `blender_version="minor"` is the default: major/minor must
match (5.2.3 can render 5.2.4 snapshots), with a visible patch warning in the job report.
Use `blender_version="exact"` to require the identical patch. A different major/minor
is always refused, before upload and again inside Blender. Patch compatibility is a
policy, not a promise that every newer feature will work; inspect the result. Use
`scripts/install_remote_worker.sh --help` on the worker/image build; it installs only
an explicitly supplied official Blender archive with its published checksum and
never installs into the shared venv. CUDA/OptiX/HIP must be available in Blender's
Cycles build. Eevee/workbench use the worker's graphics context; GPU targets reject
software rasterizers instead of silently charging for CPU fallback. The image/host
must provide functional graphics driver access (EGL on headless Linux). Detected GPU,
device and VRAM from `nvidia-smi` are reported. Optional `vram_gb` supplies a labelled
fallback when inventory is unavailable. Scene geometry/texture/render-buffer estimates
warn when they exceed VRAM and suggest lower resolution; these are planning heuristics,
not measured allocations. Lower resolution cannot fix oversized geometry/textures.

`render_options(target="devodo", calibrate=True, consent_upload=True)` renders one
480p frame remotely and records target-specific speed. Paid calibration follows the
same quote/confirm flow. `film_render_options(..., calibrate=True)` measures the first
saved film scene and restores the editor. First-frame cold startup makes single-frame calibration
approximate. Each SSH target learns its own speed; explicit local fallback updates the
normal local calibration using only frames actually rendered locally.

Remote compose passes absolute overlay paths (Windows Blender resolves drive-less
relative strip paths against the drive root) and fails on a missing overlay image
instead of silently dropping captions/titles.
Transfers use SHA-256 blobs; rsync/SCP send only missing or corrupt content. Windows
SCP uses a staging folder, Python verifies SHA-256, then atomically publishes blobs.
Interrupted SCP transfers retry the missing blob/file; they do not resume byte offsets
as rsync does. Both SSH hops use connect/alive limits. Target defaults are
`connect_timeout_s=10`, `server_alive_interval_s=5`, `server_alive_count_max=2`,
`rpc_timeout_s=30`, `upload_timeout_s=120`, `download_timeout_s=120`, and
`offline_grace_s=150`; transfers and OS detection share their operation deadline.
Timed-out transports kill only their own process group, including the jump subprocess.
Dead SSH targets fail preflight before snapshots/queueing. A queued job rechecks target
health instead of waiting behind a dead job with `max_parallel=1`.

During failed reconnects, `render_status`/`remote_targets` expose `last_seen`,
`offline_since`, and, after the grace, `stage="target offline since HH:MM:SS"`.
Successful polling alone never resets the frame-progress idle deadline.
`idle_timeout_s` defaults to 900; increase it for unusually slow frames. An independent
watchdog records `watchdog_at` without SSH or the state lock. `wait=True` returns a
terminal timeout/cancel even while cleanup is pending. Every stage/status change is
timestamped in `output/remote/jobs/<id>/supervisor.log`.

New jobs render atomic numbered PNGs plus an audio WAV, SHA-256 indexed and mirrored
to `output/remote/jobs/<id>/frames_<scene>/`. Reconnect reattaches; a dead worker restarts
only missing frames (at most three automatic restarts, without extending the attempt's
TTL or allocating another paid instance). `resume_job(job_id, fallback=None,
consent_upload=False)` explicitly resumes a failed/cancelled SSH snapshot with a fresh
time allowance. It never creates/resumes rentals. The film `resume=True` clip-cache
option keeps its original meaning. Old direct-MP4 jobs have no frame checkpoints;
snapshots already deleted by old cleanup cannot be recovered this way.

`render_video`/`render_film(..., fallback=None|"local"|"other_ssh")` require explicit
fallback selection. After the offline grace (or dead preflight), fallback renders only
verified missing frames at the requested engine/quality. Another SSH target needs its
own upload consent; paid fallback is forbidden. `fallback_used`, `frame_sources`, and
`scene_frame_sources` report source frame ranges. Captions, crossfade handles, credits,
MP4/AAC verification and film clip-cache keys keep the same pipeline. Different GPU/CPU
results can vary visually; fallback does not reduce quality automatically.

Cancel goes only to the verified job/process identity; Windows PID + creation-time
checks remain required. During disconnection TTL is the remote backstop, not proof of
shutdown. `cleanup_pending=True` persists until a successful terminal/missing response
and, for delivered jobs, cleanup acknowledgement. Detached cleanup retries when the
target returns; `remote_targets` lists pending jobs even after `wait` returns. Legacy
cancellation records without acknowledgements are treated as unknown/pending.
Failed/cancelled jobs retain snapshots/checkpoints for resume; these can be large and
are not limited by `cache_bytes`. Completed remote directories are removed; a private
bounded blob cache remains (default `cache_bytes=1073741824`). Remove retained private
files only after verifying no worker is active. One job uses one Blender process at a
time; film scenes are serial. A hard disk loss can recover only mirrored frames.

Troubleshooting: first verify `ssh -F ~/.ssh/config -o BatchMode=yes HOST` yourself,
including known_hosts entries for rented host/port, then Python/rsync/Blender paths
and graphics drivers. Strict host-key checking can prevent a newly rented host from
becoming ready; add a **verified** fingerprint to known_hosts yourself. No auto-trust.
`render_status` reports reconnection/cleanup; local downloaded logs are in
`output/remote/jobs/<id>/`. `tests/remote_ssh_smoke.py TARGET` runs 24 draft frames,
two Eevee frames and a tiny two-scene film/cache check against an SSH target, using
isolated editor port **9969**. `--loopback` uses fake SSH/rsync with real Blender workers.
`tests/test_remote.py` runs offline fake RunPod/Vast APIs and cleanup tests;
success prints `REMOTE UNIT OK`. No paid account or real rental is used by tests.
`tests/test_remote_robust.py` covers hung transports/offline/watchdog/queue contracts;
`--integration` uses real Blender for partial-frame fallback, worker restart and
cancel/resume. Run it separately from the loopback smokes, one Blender at a time.

### Target SSH Windows (penyiapan oleh pemilik PC)

Windows OpenSSH Server dengan default shell **cmd.exe** atau PowerShell 5.1 didukung.
Semua RPC Windows memakai `powershell -NoProfile -NonInteractive -EncodedCommand`
(base64 UTF-16LE); payload/source Python lewat stdin UTF-8 supaya tidak melewati batas
8191 karakter cmd.exe. Path dan nama login berspasi tidak dipotong oleh shell.
`os` dapat diisi `windows`/`linux`; bila dihilangkan, char3d mendeteksi `ver`, lalu
`$env:OS`, lalu `uname -s`. `shell="cmd"|"powershell"` mencatat shell SSH; tidak perlu
mengubah registry DefaultShell. Keduanya tetap memakai command PowerShell terenkode.

Pemilik menyiapkan OpenSSH Server dari PowerShell **Administrator** bila belum ada:
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```
Untuk anggota Administrators, tambahkan **public key laptop yang telah disetujui** ke
`C:\ProgramData\ssh\administrators_authorized_keys`, bukan profil `.ssh` pengguna.
Pertahankan key yang sudah ada; jangan salin private key. Contoh untuk file baru:
```powershell
$keyFile = "$env:ProgramData\ssh\administrators_authorized_keys"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::AppendAllText($keyFile, "ssh-ed25519 AAAA_GANTI_DENGAN_PUBLIC_KEY_LAPTOP pemilik`n", $utf8)
icacls.exe $keyFile /inheritance:r
icacls.exe $keyFile /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F'
icacls.exe $keyFile
New-Item -ItemType Directory -Force 'D:\char3d\remote'
```
SID tersebut berarti Administrators dan SYSTEM, termasuk Windows berbahasa lain.
Periksa ACL file yang sudah ada dan hapus grant pengguna lain bila diperlukan.
Batasi akses folder worker ke akun pemilik/Administrators/SYSTEM juga; `chmod` Unix
tidak mengatur DACL Windows. Pertahankan pembatasan jaringan/VPN/jump host yang ada.

Contoh registry untuk PC pemilik (backslash JSON harus ditulis `\\`):
```json
{
  "pc": {
    "kind": "ssh", "os": "windows", "shell": "cmd",
    "host": "10.8.0.8", "jump_host": "reyhan", "port": 22,
    "user": "reyhan febrizio r",
    "remote_dir": "D:\\char3d\\remote",
    "python": "C:\\Users\\Reyhan Febrizio R\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
    "blender": "C:\\Users\\Reyhan Febrizio R\\AppData\\Local\\Programs\\Blender\\blender-5.2.3-windows-x64\\blender.exe",
    "blender_version": "minor", "device": "cuda", "vram_gb": 4,
    "max_parallel": 1, "threads": 4, "max_hours": 4
  }
}
```
GTX 750 Ti 4 GB memakai GPU untuk Eevee. Cycles memilih CUDA atau OptiX sesuai
`device`; memilih mode yang tidak tersedia menghasilkan error, tanpa fallback CPU
diam-diam. Kalibrasikan setiap kualitas yang dipakai. Pengukuran PC 0,70 s/frame pada
640×360 / 8 samples tidak otomatis berlaku untuk final 64 samples atau scene lain.
FFmpeg/ffprobe eksternal tidak wajib; Blender menyandikan MP4 dengan FFmpeg bawaannya.

Verifikasi host key di PC dengan
`ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub`, lalu cocokkan di laptop.
Fingerprint yang diberikan pemilik untuk PC ini:
`SHA256:N0TqA8emrMKQQW8hU7r0xtN7LvpH43b535HuFOehDq8` (ED25519).
Jangan menonaktifkan StrictHostKeyChecking atau menerima fingerprint secara otomatis.
Uji manual setelah key disetujui:
```bash
ssh -F ~/.ssh/config -o 'ProxyCommand=ssh -F ~/.ssh/config -o BatchMode=yes -W %h:%p reyhan' -l 'reyhan febrizio r' 10.8.0.8 ver
.venv/bin/python tests/remote_ssh_smoke.py pc
```
char3d tetap memerlukan `consent_upload=True` untuk target PC ini. Worker Windows
dilepas dengan DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP, menyimpan PID dan waktu
pembuatan proses untuk menghindari PID reuse. Pembatalan memakai `taskkill /PID ... /T /F`
hanya untuk worker yang identitasnya cocok. TTL/idle watchdog, reattach, cleanup dan
cache sama seperti Linux. Tidak ada `taskkill /IM blender.exe`, password, atau perubahan
konfigurasi SSH otomatis.

Tes offline: `tests/test_remote_windows.py` → `REMOTE WINDOWS UNIT OK` menguji command,
SCP/hash/cache, lifecycle Win32 dengan fakes, versi dan VRAM. `tests/remote_ssh_smoke.py
--windows-loopback` memakai emulasi layer Windows/SCP dengan Blender Linux sungguhan;
ini tidak menggantikan pengujian OpenSSH/driver/Blender native pada PC pemilik.

## Directing method

Judge the assembled film in this order: sound, rhythm, camera, performance; then
check continuity and text readability. Write a treatment before building: compare
three possible structures and choose one with a reason; specify a logline,
setup/turn/ending, an opening event within three seconds, a returning opening detail
at the ending, one peak shot, motivated shot list, beat sheet, music/cut grid,
section sound table and subtitle design. `direct_scene` returns this as `treatment`
JSON and Markdown inside `brief`; offline/API/CLI use the same closed contract.
No external directing documents or prompts are included.
Offline drafts keep their dramatic progression and reserve camera overrides for the
opening, the decisive line and the ending echo, returning to automatic speaker coverage
between them. Their beat sheets describe actions/actors; instrument notes come from the
actual composer events and the selected synth or zero-based GM program mapping.
All director providers validate hidden speaking turns and long static overrides before
building; online transports retain their single repair opportunity.
Indonesian scripts use `MUSIK`, `KAMERA`, `HENING`, `jeda`, translated mood aliases and
readable shot names (`medium close-up`, `close-up`, `diam` for a static camera).
Default offline hair keeps eyes clear; an explicitly requested bob still needs visual
inspection. Inspect the peak close-up even when the proxy-based camera score is high.

Execute decisions with bracket cues or dict beats:
- `[KAMERA: close-up Ana, push in]`, `[CAMERA: wide, drone reveal]`,
  `[CAMERA: medium two-shot, orbit left]`; `[KAMERA: otomatis]` / `[CAMERA: auto]`
  resumes dialog coverage. Dict `{do:"camera",shot:"close_up",subject:"Ana",move:"push_in"}`.
  Subjects must be declared characters. A cue overrides cuts until the next cue.
  Dict `deliberate:true` exempts an intentional sub-0.8-second shot from the rhythm warning.
  Small default move intensity and current dialog-line side constrain camera travel;
  an unsafe crossing is reduced to static with a warning. Visibility/composition
  checks still run. Check the actual shot after changing animation.
- `[MUSIK: tegang]` / `[MUSIC: warm]` changes the generated mood at the next
  four-beat bar. `[MUSIK: berhenti]` / `[MUSIC: stop]` stops the score at that bar.
  Dict `{do:"music",mood:"tense"}` or `mood:null`. `music=None` disables all
  generated music, including cues. Original offline instruments/installed SoundFont
  are used; manual music is preserved.
- `[HENING 1 detik]` / `[SILENCE 1 second]`, dict `{do:"silence",seconds:1}`,
  holds the timeline and dips music/ambience by 30 dB with short shoulders. Foley
  stays audible. Saved volume automation survives snapshots; rerunning ducking
  preserves the silence envelope.
- Film `[TRANSISI: dissolve 0.5 detik, J-cut 0.4]` or `L-cut` adds audio handles.
  Dict transition `{kind:"crossfade",duration_s:.5,audio:"j_cut",audio_s:.4}`.
  J-cuts reserve incoming picture head frames; L-cuts reserve outgoing picture
  tail frames. Audio and the visible source picture remain aligned. Film duration
  shortens by those handles in addition to dissolves. Handles must fit adjacent
  scenes. Default transitions retain the previous frame arithmetic.

Review once, make one safe fix round, recheck once, then inspect the images and
final MP4. `review_scene(level="standard",fix=False,sheet=True,engine="workbench",
size=384,asr=False,frames=None)` returns score/category scores, stable issue IDs,
severity, frame/shot/character, numeric evidence, suggested `{tool,args}` calls,
auto-fix eligibility, labelled contact sheet, action strips, Markdown/JSON reports
and timings. `quick` samples every two seconds; standard every 1.5 seconds; both
include shot middles. Full uses the denser geometry path. Stills remain <=512 px.
`frames` selects extra/explicit stills; it never limits timeline sound checks.

Checks include offline sequencer mix LUFS/estimated true peak/clipping, measured
music attenuation and speech balance, audio/lip coverage, contact Foley, ambience
and a quiet turn; shot length/variation/mid-word cuts; projected scale, face/eye
position, visibility, jump cuts and dialog side; subtitle hold/CPS/face overlap,
title duration, sampled luminance/contrast; blink/articulation/expression/motion,
sole/torso/held-grip proxies, skin-fitted limb distances and sampled garment/prop
penetration against evaluated furniture triangles. Scenery on any face, including two-shots, is an error
with a native camera auto-fix. Talking-mouth crops, repeated ECU and repeated single
framing are checked too. Measured caption glyph/outline boxes and title backing boxes
are checked against face/mouth boxes and each other; `layout_overlays` repairs their
placement without changing words or timing. OTS review also checks rear-head orientation and measured
foreground width. `limited_coverage` warns only for scenes >20 s with >=4 shots,
all static, and >=75% at one size. This is one normal camera warning (8 category
points, about 1–2 overall points), with no automatic artistic edit; a single held
master, shorter scenes, varied sizes or a motivated move are exempt.
`fix=True` calls resolve_collisions once for the affected cast and records skipped
reasons. It runs at most one call per tool/target for
safe blink, ducking, missing Foley/ambience, subtitle grouping/hold, native camera
re-fitting or title hold fixes, and reviews once. An undersized native shot is re-fitted
with its subject, move and dialog side retained; a jump cut changes the incoming view
by two sizes. Short shots, long static holds and turned faces receive executable
suggestions, kept for a directing decision. It never edits the script, cast or
voices. Insufficient overlay space and artistic edits remain suggestions.
`add_subtitles(min_hold=1.8,hold=.6,max_cps=17)` supplies reading-time targets;
subsequent captions and the scene end can still constrain them.

`review_film(name,...)` opens each saved project, reviews it, checks wardrobe,
cards and transitions, and restores the unsaved editor snapshot in `finally`.
Reports/sheets are combined under the film folder; fixes save changed scenes.
`review_video(path,asr=False)` runs PyAV/numpy without starting Blender, measuring
encoded audio, A/V durations, near-black/frozen intervals and audio gaps. ASR is
optional local Whisper round-trip WER against stored lines, never default.
No story comprehension, exact mesh collision solver or certified loudness meter
is implied. Static holds/fades/quiet audio can be intentional. Workbench exposure
is provisional; use Eevee or encoded-file review for delivery. Subject hair and worn
character accessories still need visual review. Foreground and held scenery props count
in face rays for every size. Custom sequencer
DSP/spatialization is outside the offline volume/trim mix model.

`credits(path=None,card=False,name=None)` writes `CREDITS.txt` and returns used
MPFB assets/pack names (CC0), SoundFont/licence file, TTS voice/runtime/privacy
notes, ASR model when recorded, actual fonts, user imports and original generators.
Unknown provenance is labelled; the inventory grants no permissions. `name` selects
a saved film. `card=True` adds a three-second end card; for a named film it saves
the final scene and restores the editor. Repeated calls reuse the same card. `render_video` and
`render_film` automatically write credits beside MP4; `credits=False` opts out.
Keep TTS voice limitations from **Voices (TTS)**; runtime licences do not grant
voice-model or recording permissions. Deliver MP4, SRT, treatment and CREDITS.

Verification for this feature uses only **9973**, workspace `$PWD/output`, one
Blender at a time. `tests/test_review.py` prints `REVIEW UNIT OK`;
`tests/e2e_smoke.py --review-only --serial-video` supplies deliberate faults and
before/after evidence. Keep `--script-only`, `--film-only` and director E2E passing.
`tests/director_e2e.py --reviews-only` builds three seeded offline scenes and asserts
score >=90, no rhythm/camera warnings/errors, speaker visibility and static holds <=6 s.
Each matrix case uses a fresh owned engine; `--review-case NAME` reruns one case.
Do not install packages into the shared `.venv`.

## Sutradara AI (idea → script)
`director_status()` reports offline/API/Claude Code availability, configured yes/no,
model, privacy and billing, without a request or Blender. `direct_scene(idea,
generator="auto", language="id", duration_s=30, characters=None, style=None,
look=None, location=None, seed=0, consent=False)` returns a detailed Markdown
`brief`, structured `treatment`, executable text `script`, character metadata, parse-only `plan`, warnings
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

The brief includes the structured treatment as Markdown alongside look/palette/light,
weather/dressing, cast/outfit/voice and blocking. The script executes camera, music
and silence cues described in **Directing method**. `build_options.treatment`
preserves its JSON in built projects. Wardrobe colours and bespoke dressing still
need manual art direction. TTS/action timing remains approximate; inspect renders.

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
Action motions run the bounded collision pass after contact IK (collisions=False opts out).
Large skirts, extreme builds and furniture can still intersect with explicit skipped reasons.
There is no full fabric simulation. Traditional dance is an
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
  turns. On flat ground a walk uses steps of about 0.37 x stature, a heel strike (toes up
  12°) and a heel rise onto the toe edge (15°) pivoting on the sole, and the body bob,
  widest stride and counter arm swing coincide with double support. Its last two steps
  land side by side at the destination about .3 s before the decelerating hips stop; the
  body glides over the planted feet while the chest carries ~3.5° forward and rights
  itself. Runs and terrain routes keep whole-sole contacts and two gathering steps.
  `face_end` optionally faces an XY/XYZ point, object name or `"camera"`, sampled when the
  final turn begins. `turn_to("Maya_rig", "camera", start_frame=None)` turns in place
  by the shortest angle with alternating steps, then stands. Targets at the root's XY
  position leave its heading unchanged; `"camera"` requires a scene camera/shot.
  Both tools support basic, Rigify and MPFB rigs through the same proxy as `animate`;
  `start_frame=None` appends after the rig's existing action (otherwise scene start).
  Results include `frames`, `next_start_frame`, `distance_m`, `duration_seconds`,
  `foot_lock.contacts` (flat, fixed-foot frames; heel/toe roll frames are excluded) and
  `footfalls` (heel-strike frames; pass them to `auto_sfx(footfalls=...)`). Check
  `render_frames(..., view="top")` with waypoint markers for the route and
  `view="right"`/`"three_quarter"` for steps. Z follows walkable terrain (see below);
  static obstacle avoidance is described below.
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
    start; the route planner does not predict moving characters or arbitrary limbs.
    The baked collision pass can repair bounded limb conflicts afterwards; it never re-routes roots.
- `import_mocap(path, armature)` — .bvh/.fbx/.glb motion (CMU, Mixamo "without skin",
  Rokoko...). Matches names, T/A rest pose, facing and body size automatically;
  the imported source skeleton is deleted afterwards. If `mapped` is missing bones,
  pass `bone_map={"thigh.L": "their_bone", ...}` (keys = basic bone names).
- `retarget_animation(source, target)` — copy motion between two rigs in the scene.
- **Captured approach and standing press** — `walk_approach` places a forward BVH
  walk-and-stop take at a world XY destination. Supply the inclusive source range
  and both feet's planted intervals at scene FPS. An optional shoe mesh lets the
  tool correct residual slip using the evaluated sole. Follow with `press_button`
  on a movable cap. It leads with gaze and shoulder, transfers weight over planted
  feet, fits the finger to the descending cap, and returns contact timing. Pass
  the walk's `footfalls` to `auto_sfx` for exact sound timing.
  See [the Budi reference](examples/standing-button.md).
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
  not every surface vertex. Loose cloth also queries evaluated seat/desk/armrest/terrain
  BVHs and posed peer/own-arm proxies (collisions=False disables these added colliders).
  There is no exact body-mesh, held-prop, finger or full self-collision simulation. Extreme
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
  does not follow walking characters. The later bounded collision pass snapshots its
  evaluated triangles for hands/desk clearance; arbitrary camera orbits still need inspection.
  Use explicit character subjects for lighting and camera framing.
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
  `hands`: thighs, lap, armrests (requires seat metadata), desk (palms flat on the
  desk/table in front, torso leaning ~9°; falls back to thighs when no desk surface
  is reachable), none (keeps arm posture).
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
  (not arbitrary concave seats). The baked collision pass handles bounded armrest/desk
  and eligible garment conflicts; seat occupancy and approach placement remain manual.
  Very high/low seats can exceed limb reach. Prop pickup/release
  intervals must be sequential; a new hold can start at/after the previous release. Use one held
  prop per hand at a time. Upright holds own wrist roll/flex; extreme arm poses can require
  a pronounced wrist bend or still intersect the body/prop. Collision repair can move
  the wrist target or lift its elbow while keeping grip/wrist orientation; unreachable,
  excessive or protected lip/hand contacts stay reported. Call resolve_collisions after
  manual attachment/pose edits and inspect drinking/raised-microphone poses.

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

## Nature kit

`set_environment` adds `blossom_garden`, `pine_forest`, `lakeside`, `riverside`,
`rice_terraces`, `mountain_village`; park and beach use the same richer generators.
`density=.2..2` (default 1) scales vegetation dressing. Subject-foot anchoring,
variant seeds, theme accents, clear/replace, benches and beach deck chairs retain
the existing contracts. The acting corridor stays open; inspect later custom blocking.
Script aliases: kebun bunga/taman sakura, hutan/hutan pinus/forest, danau/tepi danau,
sungai/tepi sungai, sawah/sawah bertingkat, desa/desa pegunungan. Existing aliases remain.
The tool also accepts `forest`, `mountain_lake`, `village`; scripts additionally
accept taman bunga, rice field and kampung.

Pure library: [`engine/nature/README.md`](engine/nature/README.md).
`from engine.nature import tree, grass_field, flowers, rice_paddies, ...` returns
Blender-free `Asset`/`Mesh` recipes, deterministic with local `seed`, without IO or
global RNG changes. Twenty-nine generators cover eight tree kinds, bush/hedge/reeds,
meadows, terraced rice, hills/ridges/rocks/cliffs/paths, lake/river/sea/waterfall,
clouds, petals/leaves, birds, butterflies and fireflies; fences, lanterns, bridges,
gazebos, village houses, open field huts, ferns and fallen-log seats. Tree seasons
include dry/wet. Units are meters, Z up.

`nature_catalog()` lists signatures and limits.
`add_nature("tree", location=[-4,6,0], seed=17,
params={"kind":"blossom","height":5,"season":"spring"})` adds a transformable root.
`clear_nature()` removes only standalone nature groups; `clear_environment()` also
removes preset scenery and other managed props. Nature generators use no downloads.

Opaque folded foliage and shared material palettes bound CPU cost. Near/middle/far
detail is fixed at build time, with larger distant leaves; existing shot frusta
thin distant groves/patches toward 35% density. Without cameras, builds use the
acting area. Reapply after framing to redistribute, or use `camera_aware=False`
on add_nature. Cameras never switch LOD per frame. Trunks/bushes/rocks block walking;
thin ground cover does not.
Camera probes consider actual tree foliage and bushes; grass/flowers/life/sky/water
are ignored. Hills and terrace banks are walkable, but rises >.25 m still block routes.
Large terraces need explicit stairs for access. Low flattened stones can be seats.
Layouts have distinct landmarks: L pier/open lake, S river/bridge, contoured sawah
with a tapered causeway/gubuk, pond/gazebo blossom walk and fern/log conifer glade.
Park portraits use a lower green middle storey. `COMPOSITIONS` provides suggested
wide framing; cameras remain user controlled. Water presets enable screen-space
reflections and restore prior ray settings on clear. Ferns, fallen logs and field
huts are also reusable generators; `falling_petals(ground=True)` makes static litter.
`rice_paddies(exclude=[(x,y,r), ...])` clears crop roots beneath props.

Wind sway, wingbeats, cyclic bird flight, drifting petals and animated water normals
are saved drivers/nodes and evaluate on arbitrary frames without simulation caches.
Weather wind updates foliage live; secondary hair/cloth still needs its usual rebake.
Normal separate-process videos preserve motion. GLB exports geometry/morph targets;
procedural drivers/nodes need baking for non-Blender consumers. Water is opaque,
with no fluid/refraction simulation. Clouds are cheap geometry; distant ridges use
layered palettes and cooperate with cinematic haze. Ground fallback permits walking
across water: keep routes on banks or add walkable bridge geometry.

`render_options` includes `nature_cost_factor`, multiplied with style/look once and
removed once during calibration. Draft is 1; default Eevee floors are 1.15..1.70,
scaled by density. These are estimates; measured evidence is in
`output/nature_baseline.json`, `nature_benchmark.json`, `nature_visuals.json` and
`nature_clips.json`. Sheets: `output/nature_sheets/`; saved scenes: `output/projects/nature_*.blend`.
Measured review revision: i5-4460 CPU Eevee, two MPFB actors, density 1,
960×540/16 samples, overcast/no look, no camera thinning: legacy park bookend
30.00 s/frame; revised sets 23.42–48.40 s/frame (0.78–1.61×). Rice is at the
approximate 1.6× boundary; the other means are ≤1.29×. The initial reference was
39.40 s/frame and the historical reference 30.02; shared CPU load varies.
The library README gives raw conditions and per-preset means. Rice's estimate
floor is now 1.70; other floors are unchanged.
Review evidence: `output/nature_review/{benchmark,reference,reference_end,visuals}.json`,
sheets in `output/nature_review/sheets/`, native scenes in
`output/projects/nature_review/`. Reproduce on port **9997** with
`tests/nature_review.py --reference --sheets --bench`; original fixtures and
clips remain intact. Tests: `tests/test_nature.py`, `tests/nature_e2e.py`.

**Lighting** — `set_lighting(preset, subject, follow="auto")`: studio, podcast, soft, dramatic,
sunset, noon, overcast, night, neon, silhouette, horror. `podcast` is a warm soft key from
camera left, a dim cool fill and one thin blue rim per subject (placed behind it, on the
side away from the group). Adds a large ground plane indoors by default and
switches the scene to Eevee. `rotate` spins the rig of lights around the subject.
It also raises Eevee shadow tracing to at least 3 rays x 12 steps: Blender's single
default ray left a stipple where hair hulls shade cheeks/necks under soft keys.
Its own shadow-casting lights also use jittered soft shadows, which remove the
stipple in wide shots where a face covers few shadow-map texels. Higher existing
values are kept; together these cost roughly 1.3-1.5x per frame in noisy CPU tests.
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
- `shot="over_shoulder"` (alias `ots`) uses one facing subject and `foreground=partner`,
  or `subject=[facing_subject, partner]`. The camera is placed behind the near
  upper-arm/shoulder joint, at shoulder height, on the established action-line side.
  Default lenses stay within 50–85 mm; the subject's evaluated eye mesh supplies
  the upper-third framing and cinematic focus (anatomical fallback on other rigs).
  The partner's rear head/shoulder occupies roughly 20–35% of frame width.
  `foreground_composition` and `occlusion.foreground` report the shoulder, side,
  clipped width/area fractions and head-to-camera angle. Width uses a 64×36 mesh-ray
  mask, not an alpha-aware raster pass; review allows a margin of two percentage points.
  Opposite coverage selects opposite anatomical shoulders while retaining the action
  line side. OTS-to-clean cuts still need two sizes or a 30-degree viewpoint change.
  The foreground partner is
  excluded only from the foreground-area budget: face/eye occlusion and solid camera
  collision checks still include it. Tight spacing, furniture or unusual blocking can
  prevent a safe OTS and produce a warning. Cinematic DOF focuses the facing subject;
  directed reaction cameras rack from the speaker to the listener's live eye plane.
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
  head/chest and, for wider sizes, body bounds. Anatomical landmarks include the
  lips/chin and authored eyes/teeth, with head-weighted width for stylised heads.
  Subject character meshes, ground and render-hidden geometry are excluded; held
  and foreground scenery props remain occluders. Other characters can block
  singles, while every subject in a two-shot is excluded.
- Blocked faces or excessive foreground trigger a deterministic search: pedestal
  up first, then small azimuth changes, then closer positions past the occluder.
  Each candidate fits aim and lens to the original projected eye/head-top/chest
  landmarks. Seated bounds that place eyes outside the upper-third band define
  their unobstructed design by translating those targets to a 1/3 eye line,
  retaining their relative size. Candidates allow ±4% of frame height/width for
  headroom/eye position and ±15% for head-to-chest projected height.
- Acceptance requires zero sampled scenery rays on a face, total face occlusion <= 5%, clear eyes for close-ups, face samples
  inside the frame, and foreground coverage <= 25% (close_up, medium_close, medium;
  also extreme_close_up) or <= 35% for wider sizes. Coverage uses a 24x14 ray grid,
  ending at the nearest subject's eye-depth plane. Subject geometry uses the same
  exclusions as face rays. Camera positions inside scenery/subject bounds or
  across walls are rejected; dialog preserves the current action-line side.
- If no candidate passes, try wider sizes (close_up → medium_close →
  medium → medium_full → full → wide → extreme_wide), with the same checks. If
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
  samples may be missed. Own hair and worn character accessories still need visual checks.

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
- Captions break at sentence ends, pauses > 0.6 s and long clauses. Two-line styles keep a
  short sentence with the same speaker's quickly following sentence so it can be read. Calling `add_subtitles`
  again replaces the settings; `remove_subtitles` or `render_video(subtitles=False)` skips them.
- `avoid_overlap=True` (default, also on `add_title`) measures actual glyph outlines
  and title backing boxes, reserving the current shot's face/mouth regions. Captions
  and titles stack into free vertical space; requested placement remains when clear.
  The same layout and cut/chunk/title boundaries drive stills and movie PNGs. A caption
  crossing a camera cut gets separate overlays; SRT, highlights and speech timing stay
  intact. `layout_overlays()` enables this on saved legacy configs; review can apply it.
  If the image has no free space, review keeps a visible finding for wider framing.

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

## Mode bebas (world recipes)

Use `world_schema()` for the closed JSON Schema, 38-generator catalog, parameter
ranges and hard budgets. `compose_world(recipe, build=False)` validates, normalizes
and estimates without Blender or scene changes; True builds an owned world.
`clear_world()` removes it; `save_world(name)` / `load_world(name)` store validated
JSON under workspace `worlds/`. Names never accept paths. No AI-authored Python,
expressions, URLs or external assets execute: only declarative allowlisted data.

Recipes contain version/seed, elements (generator/params, XYZ transform, explicit
instances or seeded scatter with spacing/exclusions), named palette/material
presets, practical lights, sky/look/weather, saved animation presets, hero camera
hints and walkable stage/standing/seats. All 26 nature builders plus primitive and
prop are available. Original heroes: serpent, whale_like, bird_like,
floating_island, lantern_swarm, hot_air_balloons, crystal_cluster, arch_gate,
pagoda_like and banner_cloth; existing waterfall is reused. Architecture uses
generic vocabulary; never recreate specific films/games/brands/landmarks.

Art quality: serpent uses round parallel-transport sections along a spatial coil,
UV scale shading, belly/mane, articulated jaw, horns/whiskers and optional legs.
`coil` 0–1, length 2–100m, emission 0–3. Whale `motion` .2–2.5 drives independent
fin/fluke hinges with shared swim. Islands have strata, grass, roots/vines,
waterfall spray and 0–12 `orbiting_rocks`. Clouds use three seamless Gaussian-union
billow layers (`area` controls extent); mountain layers are sloped heightfields.
All shaders/motion remain fixed internal profiles. `camera_hints.medium/close`
plus `f_stop` create reusable owned DOF cameras (`portrait_cameras` in build output).
Dress the portrait midground and keep paths/faces clear. Quality evidence is in
`output/world_sheets/quality_v2/`; harness supports `--refresh` to rebuild recipes
around saved actors, and `--reuse` to render saved milestones without rebuilding.

Hard budgets: 20k internal instances, 256 placements, 400k estimated triangles,
1.2M vertices, 1,200 objects, 16 lights, 2 volumes, 200k transform keys. Geometry
is preflighted; prop costs are conservative. Warnings begin at 70%. World motion
uses saved native drivers/keys, without simulation caches or Python handlers.

`direct_world("paus berenang melalui awan senja", generator="offline", seed=17)`
returns recipe/brief/warnings/cost without building. Offline has ten seeded world
archetypes. Claude API and Claude Code reuse existing director generators, privacy
and explicit `consent=True`; auto selects online only with consent. Structured
JSON gets one validation-repair round, then visible offline fallback on failure.
Prompts include composition layers, motivated lighting, palette, scale and motion.

Use `DUNIA: saved-name` / `WORLD:` headers or dict `world` (name/inline recipe).
The world supplies the set and stage; dialog/cameras/sound work normally and script
look/weather override recipe defaults. Studio's **Dunia** page offers describe,
generator/consent, summary, JSON with inline validation, Eevee hero preview, save
and use in Naskah. Existing characters remain during composition and preview.

Recipe example, full catalog/ranges, lifecycle/safety/cost details and limits:
[`engine/world/README.md`](engine/world/README.md).
Verify: `tests/test_world.py` → `WORLD UNIT OK`; `tests/e2e_smoke.py --world-only`;
`tests/world_visuals.py --stills` / `--reuse --clips`; `tests/world_ui.cjs`.
Use only engine **9998**, UI **8798**, workspace `$PWD/output`; one Blender at a
time. Evidence: `output/world_sheets/`, `output/world_visuals.json`, saved world
JSON and `.blend` milestones. Clouds/water/creatures are stylized; inspect hero,
medium/close and motion. Procedural Blender motion needs baking for other apps.

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
- `animated_film` (aliases `film_animasi`, `animasi`): a cohesive original animated
  feature direction over humans, nature, procedural heroes and indoor sets. At default
  strength the same dominant painterly response covers photographic and procedural
  materials: four softly eased light masses, HDR highlight compression, a continuous
  form gradient, and colored shadows. Per-look key/shadow palettes harmonize materials,
  softboxes and sky; midtones gain color, fill becomes cooler and rims stronger.
  Temporary low-resolution color samplers suppress skin pores, hair strands and fabric
  grain while preserving original UVs, alpha masks and normal/data maps. Broad normals
  and specular lobes simplify surfaces; water/metals retain more physical reflection.
  Skin gets warm bounce and subtle head-following cheek blush. Iris textures stay sharp
  and richer; glossy corneas keep their authored optics. Short-range AO reinforces
  contacts/creases. Color samplers used for opacity/emission, including through group
  inputs, stay unfiltered. Alpha, practical emission and nested material graphs
  survive. Scene/look/weather still motivate lighting; no extra volume, render pass
  or render-sample increase is used.
  Outlines default off; `outline=True` opts into the existing silhouette hulls.
  Cycles uses the filtered albedo, softened normals, blush, physical material and
  softbox/palette changes, without Eevee's Shader-to-RGB light masses.
  `script_to_scene`/`script_to_film(..., style="animated_film")` and `GAYA:`/`STYLE:`
  headers accept these styles. Explicit arguments override headers; omitted style
  preserves the current scene configuration. Parse-only mode reports `plan.style`.
  Base MPFB materials are never edited, including enhanced skin/eye/hair/fabric graphs.
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

`animated_film` was measured separately at 512×288 / 16 samples, golden_hour,
two clothed MPFB humans, llvmpipe and 8 render threads. Three none / three styled /
three none stills bookend shared CPU load; discard the first of each triplet and
average the remaining baseline trials. Wall timings include override setup/restoration,
the MCP call and PNG output. CPU timings measure all Blender threads across the same
calls. Load varied substantially, so wall ratios below one do not establish a speedup.
The cost estimate retains a conservative 1.25× factor; outlines were off.

| scene | none, seconds/frame | animated_film | wall ratio | CPU ratio | estimate factor |
|---|---:|---:|---:|---:|---:|
| podcast_studio | 53.56 | 40.86 | 0.76× | 1.07× | 1.25× |
| park, density 0.6 | 45.71 | 47.02 | 1.03× | 1.03× | 1.25× |

Reproduce with `CHAR3D_PORT=9972 FILMSTYLE_OUTPUT=output/filmstyle_v2 .venv/bin/python
tests/filmstyle_visuals.py --sheets`, then `--bench --only podcast_studio` and
`--bench --only park` (same environment prefix). The guarded harness uses only port
9972 and the worktree's `output/`; `output/filmstyle_v2/benchmark.json` retains all
wall/CPU trials. The four-set sheets include park, rice_terraces, an offline lantern
lake world and podcast_studio, each in golden_hour plus night/misty, wide/medium/close.

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
- The screenplay camera picker includes directed emotion, OTS, and listener reactions.
  Scene controls include manual OTS and collision inspection/correction. Use the
  character page for MPFB styles, VRM imports and local face fitting with consent.
  The Render screen reads the target registry and asks for upload consent before
  remote submission. GPU quotes require a second explicit confirmation.
  Review checks the current scene, saved scenes of the active film, or a rendered
  MP4. Its default operation is read-only. The separate correction action is explicit.
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
