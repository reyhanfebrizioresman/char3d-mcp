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
| `reeds`, `rice_paddies` | area, density, height; 1..16 curved terraces |
| `hills` | area, height, roughness 0..1; fixed 48×48 height field |
| `mountains_backdrop` | 1..6 layers, area, height; full sloping ridges with distance palettes |
| `rocks`, `cliff` | count/area/height; cliff width/height |
| `path` | XYZ points, width, gravel/earth/stone/wood |
| `lake`, `river`, `sea`, `waterfall` | ellipse-like irregular shape; river XYZ points/width; sea area/wave height; waterfall height/width |
| `clouds` | cover 0..1, height, wisps/cumulus; opaque smooth lobes, no volume cost |
| `falling_petals` | area, count 0..500, height, kind petals/leaves |
| `birds_flock`, `butterflies` | count 0..60 / 0..80; cyclic closed XYZ flight path / area and height |
| `fireflies` | area, count 0..500, height, night flag; emissive saved flight |
| `fence`, `lantern` | length/height; lantern includes a warm practical light |
| `wooden_bridge`, `gazebo` | length/width/arch height; walkable deck/floor and separate solid rails/posts |
| `village_house` | width, depth, height; original timber/plaster gable, warm practical windows |

All accept seed 0..2147483647. Field area components are .1..400 m. Density is
capped at 18,000 grass clumps / 3,000 flowers / 9,000 rice clumps; reeds cap their heads separately.
Zero counts/density return empty geometry. `nature_catalog()` exposes exact
Python signatures and defaults. Invalid inputs fail before the adapter creates
objects. `add_nature` rejects assets above 1.2 million vertices.

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
They use an open acting corridor, near detail, midground groves and distant ridges.
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

Opaque water does not simulate refraction, fluids or reflections of unseen
geometry. Clouds are stylized geometry, not a weather simulation. No dynamic
collision or leaf/cloth interaction. Ground fallback still permits routes across
unmarked water; keep routes on banks or add a walkable bridge. Arbitrary layouts,
large camera orbits, oversized flora and close face coverage need inspection.
Ground-cover patches start at local Z=0; they do not automatically conform to an
arbitrary terrain mesh. Place roots or sample the height field explicitly.
Generated fallen petals wrap beyond the ground/top, not with camera LOD.

Nature cost factors multiply style/look factors once and are removed once during
machine-speed learning. Draft uses 1. Default Eevee estimate floors are 1.15..1.50,
including the measured park/blossom overhead; density scales the overhead. `render_options`
reports `nature_cost_factor`. Conditions, measured seconds/frame and paths are
recorded by `tests/nature_visuals.py` under gitignored `output/nature_*.json`.


Measured on an Intel i5-4460 (CPU/software Eevee), Blender 5.2.4 LTS,
two MPFB actors, fixed eight Blender/software-GL threads, overcast, look `none`,
960×540, 16 samples. A 320px warm-up is excluded; values average two timed
960px frames including RPC/render preparation. Legacy park: **30.02 s/frame**.
Shared CPU load and shader allocation can vary; raw samples remain in JSON.

| Preset | Seconds/frame | / legacy park |
|---|---:|---:|
| park | 43.48 | 1.45× |
| beach | 24.46 | 0.81× |
| blossom_garden | 42.13 | 1.40× |
| pine_forest | 35.43 | 1.18× |
| lakeside | 32.34 | 1.08× |
| riverside | 36.01 | 1.20× |
| rice_terraces | 30.37 | 1.01× |
| mountain_village | 36.14 | 1.20× |

These default-density fixtures were built before shot cameras, so this is the
full acting-area population, without later camera-based thinning. All eight
averages are below 1.6× the old park in this run. Look costs are additional.

Reproduce with `CHAR3D_PORT=9997 CHAR3D_WORKSPACE=$PWD/output .venv/bin/python
tests/nature_visuals.py --sets --only park --looks none`, then `--reuse` for other
looks. Use `--bench` for warm-up + two 960×540/16-sample stills, and `--clips` for
3 s, 512×288/12 fps drafts rendered in the same engine (no second Blender).
Pure tests: `tests/test_nature.py`; integration: `tests/nature_e2e.py`.
