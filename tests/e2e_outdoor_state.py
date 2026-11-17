"""Save/open/clear preserves user world data and deterministic saved weather.

Run on an assigned experiment port: CHAR3D_PORT=9976 .venv/bin/python tests/e2e_outdoor_state.py
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main():
    env = dict(os.environ, CHAR3D_ALLOW_PYTHON="1")
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()

        async def call(tool, **args):
            result = await session.call_tool(tool, args)
            texts = [c.text for c in result.content if c.type == "text"]
            assert not result.isError, (tool, texts)
            return json.loads(texts[0]) if tool != "engine_shutdown" else texts[0]

        async def inspect(code):
            return (await call("run_blender_python", code=code))["result"]

        await call("scene_info")
        await call("new_scene", frame_end=24)
        original = await inspect('''
sc=bpy.context.scene
w=sc.world
w.name='UserWorld'
w['roundtrip_marker']=17
w.use_nodes=True
w.node_tree.nodes['Background'].inputs['Strength'].default_value=.37
result=[w.name,w.use_fake_user,sc.eevee.shadow_pool_size,sc.eevee.shadow_resolution_scale]
''')
        await call("create_human", name="Roundtrip", height=1.75)
        await call("auto_rig_humanoid", mesh="Roundtrip")
        await call("set_environment", preset="park", subject=["Roundtrip_rig"],
                   color_theme={"accent": [.8, .15, .05]})
        color = await inspect("result=list(next(o for o in bpy.context.scene.objects if 'c3d_seat_centers' in o).data.materials[0].diffuse_color[:3])")
        assert max(abs(a-b) for a, b in zip(color, [.8, .15, .05])) < 1e-6, color
        await call("camera_shot", subject=["Roundtrip_rig"], shot="wide", start_frame=1, end_frame=24)
        weather = await call("set_weather", kind="rain", seed=37)
        sample = '''
sc=bpy.context.scene;sc.frame_set(7)
o=bpy.data.objects['Weather_rain'].evaluated_get(bpy.context.evaluated_depsgraph_get())
m=o.to_mesh()
try:
    result=[len(m.vertices),[list(v.co) for v in list(m.vertices)[:24]]]
finally:
    o.to_mesh_clear()
'''
        before = await inspect(sample)
        assert before[0] == 12*weather["particle_count"], before[0]
        exported = await call("export_asset", path="outdoor_roundtrip.glb", objects=["Roundtrip_rig"])
        assert exported["bytes"] > 1000, exported
        saved = await call("save_project", path="outdoor_roundtrip.blend")
        await call("new_scene")
        await call("open_project", path=saved["path"])
        assert await inspect(sample) == before, "saved geometry-node particles changed"
        await call("clear_environment")
        state = await inspect('''
sc=bpy.context.scene
w=sc.world
result=dict(world=w.name,marker=w['roundtrip_marker'],fake=w.use_fake_user,
 strength=w.node_tree.nodes['Background'].inputs['Strength'].default_value,
 shadow=[sc.eevee.shadow_pool_size,sc.eevee.shadow_resolution_scale],
 weather=sum(bool(o.get('c3d_weather')) for o in bpy.data.objects),
 settings=[k for k in sc.keys() if k.startswith(('c3d_weather_','c3d_outdoor_previous_'))])
''')
        assert state["world"] == original[0] and state["marker"] == 17, state
        assert state["fake"] == original[1] and state["shadow"] == original[2:], state
        assert abs(state["strength"]-.37) < 1e-6, state
        assert state["weather"] == 0 and state["settings"] == [], state
        await call("engine_shutdown")
        print("OUTDOOR STATE E2E OK: theme + saved particles + user world/shadow restoration + GLB")


if __name__ == "__main__":
    asyncio.run(main())
