"""Pure, seeded procedural nature library; importable without bpy or any IO.

All 26 GENERATORS return core.Asset: local-meter Mesh parts, material recipes,
collision/walkability/seat flags and analytic motion. Inputs never mutate a scene
or global RNG. The command adapter realizes recipes beneath transformable roots.

Vegetation: tree(kind, height, seed, season, detail), bush, hedge, grass_field,
flowers, reeds, rice_paddies. Tree kinds are broadleaf/pine/palm/blossom/maple/
banana/bamboo/dead; seasons spring/summer/autumn/dry/wet/winter. Heights are nominal.
Landscape: hills, mountains_backdrop, rocks, cliff, path. Water: lake, river, sea,
waterfall. Sky/life: clouds, falling_petals(kind='petals'|'leaves'), birds_flock,
butterflies, fireflies(night=True). Dressing: fence, lantern, wooden_bridge,
gazebo, village_house. All accept a local integer seed; field density means /m².

Example: tree('blossom', height=5, seed=17, season='spring') or
grass_field(area=[12,8], density=10, seed=17). dataclasses.asdict(asset) is JSON.
Use engine.nature.blender.realize only inside Blender, or MCP add_nature(params).

Every generator returns core.Asset. See engine/nature/README.md for units,
budgets, collision semantics, motion and the command-facing adapter.
"""
from .vegetation import tree, bush, grass_field, flowers, hedge, reeds, rice_paddies
from .landscape import hills, mountains_backdrop, rocks, cliff, path, lake, river, sea, waterfall, clouds
from .life import falling_petals, birds_flock, butterflies
from .props import fence, lantern, wooden_bridge, gazebo, village_house, fireflies

GENERATORS = {fn.__name__: fn for fn in (tree,bush,grass_field,flowers,hedge,reeds,
    rice_paddies,hills,mountains_backdrop,rocks,cliff,path,lake,river,sea,waterfall,
    clouds,falling_petals,birds_flock,butterflies,fence,lantern,wooden_bridge,gazebo,village_house,fireflies)}
