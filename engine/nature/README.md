# Procedural nature library

All geometry is original, offline and deterministic. Importing `engine.nature`
does **not** import Blender, read files, use the network, mutate a scene or change
the global random state. Each generator uses a local `random.Random(seed)`.

```python
from engine.nature import tree, grass_field, rice_paddies, river
oak = tree(kind="broadleaf", height=6, season="summer", seed=17, detail=.75)
meadow = grass_field(area=[12, 8], density=12, height=.35, seed=17,
                     exclude=[(0, 0, 2)])
paddies = rice_paddies(terraces=6, area=[30, 25], height=3, seed=17)
stream = river(points=[[-12, 8, -.03], [0, 6, -.03], [12, 9, -.03]],
               width=3, seed=17)
```

An `Asset` has `kind`, `parts: list[Mesh]`, and `metadata`. A `Mesh` has local
`vertices`, indexed `faces`, per-face `indices`, material recipes, `solid`,
`occludes`, `walkable`, `smooth`, optional `seat`, analytic `motion` and per-vertex
particle `pivots`.
`dataclasses.asdict(asset)` is JSON serializable. Material RGB is linear 0..1.
Coordinates and heights are meters, Z is up. Fields are centered on XY except
`rice_paddies` / `sea`, which extend along +Y, and paths, which follow XYZ points.
`Asset.placed()` returns a transformed copy; for animated scenes prefer the
adapter's root transforms, which also preserve local motion coordinates.
Vegetation height is a nominal botanical scale: branching and blade tips can
extend above it. Read recipe vertices or `scene_info` dimensions for exact bounds.

| Function | Main controls |
|---|---|
| `tree` | kind: broadleaf/pine/palm/blossom/maple/banana/bamboo/dead; height .3..40; season spring/summer/autumn/dry/wet/winter; detail .25..1 |
| `bush`, `hedge` | height, color/detail (bush), length (hedge) |
| `grass_field`, `flowers` | area [width,length], density in clumps or flowers/m², height, color/palette, circular XY exclusions |
| `reeds`, `rice_paddies` | area, density, height; 1..16 curved terraces, optional corridor/crop exclusions, sampled dike contours in metadata |
| `hills` | area, height, roughness 0..1; fixed 48×48 height field |
| `mountains_backdrop` | 1..6 layers, area, height; full sloping ridges with distance palettes |
| `rocks`, `cliff` | count/area/height; cliff width/height |
| `path` | XYZ points, width, gravel/earth/stone/wood; feathered crown, nonwalkable decorative aggregate |
| `lake`, `river`, `sea`, `waterfall` | ellipse-like irregular shape; river XYZ points/width and optional banks; sea area/wave height; waterfall height/width |
| `clouds` | cover 0..1, height, wisps/cumulus; opaque smooth lobes, no volume cost |
| `falling_petals` | area, count 0..500, height, kind petals/leaves; ground=True creates a static carpet |
| `birds_flock`, `butterflies` | count 0..60 / 0..80; cyclic closed XYZ flight path / area and height |
| `fireflies` | area, count 0..500, height, night flag; emissive saved flight |
| `fence`, `lantern` | length/height; lantern includes a warm practical light |
| `wooden_bridge`, `gazebo` | length/width/arch height; walkable deck/floor and separate solid rails/posts |
| `ferns` | centered area, count 0..300, height, season; rooted feathered fronds |
| `fallen_log` | length/radius; two level seat positions, local front -Y |
| `field_hut` | width/depth/height; original open gubuk, raised walkable floor and steps |
| `village_house` | width, depth, height; original timber/plaster gable, warm practical windows |

All accept seed 0..2147483647. Field area components are .1..400 m. Density is
capped at 18,000 grass clumps / 3,000 flowers / 9,000 rice clumps; reeds cap their heads separately.
Zero counts/density return empty geometry. `nature_catalog()` exposes exact
Python signatures and defaults. Invalid inputs fail before the adapter creates
objects. `add_nature` rejects assets above 1.2 million vertices.

`rice_paddies(corridor=3.6)` leaves a central gap; the caller supplies the path.
Its `metadata['dikes']` contains one sampled XYZ contour per level for planting
and prop placement. Local XY circles in `exclude=[(x,y,r), ...]` clear crop roots;
include blade reach when clearing a hut floor. `river(banks=True, bank_height=.12)` requires strictly
increasing Y points and extends each bank to local X=-150 or +150 m. For other
river directions, generate the water ribbon and supply bank geometry separately.

## Engine adapter and tools

`engine.nature.blender.realize(builder, asset, location, rotation, scale)` creates
objects in an existing environment builder. It shares material recipes within
that builder and tags owned meshes, materials, actions and node groups for
cleanup. Thin grass/flowers/reeds, water, sky and life do not block navigation or
camera probes. Trees separate solid trunks from foliage; actual canopy geometry
still blocks camera rays. Bushes and rocks block both. Hills and terrace banks
are walkable; terrace rises above .25 m still block routes. Low flattened stones
have honest level seat metadata; preset benches retain the furniture contract.

MCP tools: `nature_catalog()`,
`add_nature(kind, location=[0,0,0], rotation_z=0, scale=1, seed=0, params={}, name=None, camera_aware=True)`,
`clear_nature()`. `params` contains generator arguments except seed. Top-level
`area`, `density`, `season` override their params entry on supporting generators.
Tools add independent transformable roots without replacing a set. The original
recipe is saved as root JSON (`c3d_nature_recipe`, API version 1). `clear_nature` removes
only those roots; `clear_environment` also removes them and preset scenery.

Example tool call:
```python
add_nature("tree", location=[-4, 6, 0], seed=17,
           params={"kind":"blossom", "height":5, "season":"spring"})
```

`set_environment` adds `density=.2..2` (default 1) for nature sets. Presets:
park, beach, blossom_garden, pine_forest, lakeside, riverside, rice_terraces,
mountain_village (`forest`, `mountain_lake`, `village` are accepted set/tool aliases).
Each uses an open acting area and its own layout: an L pier/open lake, winding river
and bridge, contoured paddies and a narrow raised causeway/gubuk, a pond/gazebo
blossom walk, a curved park avenue with a low green middle storey, and a fern/log
conifer glade. Preset composition metadata is saved on the root; COMPOSITIONS
contains recommended wide angles/elevations without overriding user cameras.
Detail is selected once while building; it never switches
with a camera, distance or time. Leaf size compensates for lower distant counts.
When cameras exist, builds snapshot the union of their near frusta over the
timeline and thin distant groves/patches smoothly toward 35% density. Empty-camera
builds use the acting area. Reapply the set after framing to redistribute it.
`add_nature(..., camera_aware=False)` opts out. No camera edits silently rebuild
user-transformed geometry; the snapshot stays fixed throughout saved animation.
No image cards, texture downloads, simulation caches or render subdivision.

## Motion, cost and limits

Wind uses saved Scene Time geometry nodes. `set_weather` updates it live using
the same world acceleration that secondary hair/cloth reads; hair/cloth still
requires its usual rebake. Water combines low-frequency mesh waves and animated
procedural normals. Wingbeats use native morph drivers.
Vegetation accepts all six seasons; explicit colors/palettes keep their chosen
art direction. Winter flowers are absent; dry rice becomes straw colored.
Petals use saved Scene Time nodes; birds use cyclic smooth
flight paths and wingbeat morphs. Arbitrary seeking is deterministic. Save/open
and normal separate-process videos need no handlers. GLB contains geometry and
morph targets; procedural drivers/nodes themselves are Blender-specific, so
bake/snapshot motion for consumers that require it.

Water presets enable native Eevee screen-space reflections and restore the prior
ray-tracing settings when cleared. River normals scroll downstream in local Y.
Opaque water does not simulate refraction, fluids or reflections of unseen geometry. Clouds are stylized geometry, not a weather simulation. No dynamic
collision or leaf/cloth interaction. Ground fallback still permits routes across
unmarked water; keep routes on banks or add a walkable bridge. Arbitrary layouts,
large camera orbits, oversized flora and close face coverage need inspection.
Ground-cover patches start at local Z=0; they do not automatically conform to an
arbitrary terrain mesh. Place roots or sample the height field explicitly.
Generated fallen petals wrap beyond the ground/top, not with camera LOD.

Nature cost factors multiply style/look factors once and are removed once during
machine-speed learning. Draft uses 1. Default Eevee estimate floors are 1.15..1.70,
including the measured park/blossom/rice overhead; density scales the overhead. `render_options`
reports `nature_cost_factor`. Conditions, measured seconds/frame and paths are
recorded by `tests/nature_visuals.py` under gitignored `output/nature_*.json`.


Measured review revision on an Intel i5-4460 (CPU/software Eevee), Blender
5.2.4 LTS, two MPFB actors, eight Blender/software-GL threads, overcast, look
`none`, medium frame 32, 960×540, 16 samples. A 320px warm-up is excluded;
each value averages two timed 960px frames including RPC/setup/PNG output.
Legacy park bookend: **30.00 s/frame**; initial reference **39.40 s/frame**.
Preserved 481cde5 park retimed: **48.53 s/frame**; historical legacy park:
30.02 s/frame. Shared CPU load
and size-specific shader/allocation work cause substantial variance.

| Preset | Previous kit s/frame* | Revised s/frame | / legacy park bookend |
|---|---:|---:|---:|
| park | 43.48 | 38.56 | 1.29× |
| beach | 24.46 | 23.42 | 0.78× |
| blossom_garden | 42.13 | 38.75 | 1.29× |
| pine_forest | 35.43 | 31.18 | 1.04× |
| lakeside | 32.34 | 28.85 | 0.96× |
| riverside | 36.01 | 31.19 | 1.04× |
| rice_terraces | 30.37 | 48.40 | 1.61× |
| mountain_village | 36.14 | 38.57 | 1.29× |

*Previous-kit values are the preserved historical batch, not a paired speedup
measurement. The legacy park bookend measured **30.00 s/frame** (30.17/29.83 s),
matching the historical 30.02 s reference. The initial batch reference was
39.40 s/frame (50.73/28.08 s). Revised means are 0.78–1.61× the bookend:
rice is at the approximate 1.6× budget boundary; the other means are ≤1.29×.
Rice's latest samples were 50.80/45.99 s. Shared CPU load and allocation vary;
these two-frame means do not guarantee a hard ceiling. Look costs are additional.
Rice's default estimate floor is now 1.70, with margin over the 1.61× measurement;
other floors are unchanged and no look/style factor is counted twice.

These density-1 fixtures were built before shot cameras, without camera thinning.
Review samples: `output/nature_review/benchmark.json`, `reference.json` and
`visuals.json`; the bookend is `reference_end.json`. Original measurements remain in `output/nature_benchmark.json`.

Reproduce with `CHAR3D_PORT=9997 CHAR3D_WORKSPACE=$PWD/output .venv/bin/python
tests/nature_visuals.py --sets --only park --looks none`, then `--reuse` for other
looks. Use `--bench` for warm-up + two 960×540/16-sample stills, and `--clips` for
3 s, 512×288/12 fps drafts rendered in the same engine (no second Blender).
Pure tests: `tests/test_nature.py`; integration: `tests/nature_e2e.py`.

Review evidence: `tests/nature_review.py --reference --sheets --bench` reuses the
preserved script_to_scene cast, rebuilds the scenery without camera thinning,
and writes fresh sheets/CPU samples under `output/nature_review/`. It leaves the
original sheets and baseline fixtures intact. Per-preset source signatures reject
stale fixtures with `--reuse`; render-cost coefficients do not invalidate geometry.
