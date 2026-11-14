"""End-to-end check: real MCP client -> MCP server (stdio) -> Blender engine.

    .venv/bin/python tests/e2e_smoke.py
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CHAR3D_PORT", "9899")  # don't collide with a running engine


def text_of(res):
    return [c.text for c in res.content if c.type == "text"]


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        assert "char3d" in (init.instructions or ""), "server instructions missing"
        tools = {t.name for t in (await s.list_tools()).tools}
        print("tools:", sorted(tools))

        async def call(tool, **args):
            res = await s.call_tool(tool, args)
            if res.isError:
                raise RuntimeError(f"{tool} failed: {text_of(res)}")
            return res

        print("status:", text_of(await call("engine_status")))
        await call("new_scene")
        await call("add_primitive", kind="monkey", name="Hero", location=[0, 0, 1])
        await call("transform_object", name="Hero", rotation_deg=[0, 0, 0])
        exp = json.loads(text_of(await call("export_asset", path="e2e_hero.glb", objects=["Hero"]))[0])
        await call("new_scene")
        imp = json.loads(text_of(await call("import_model", path=exp["path"]))[0])
        assert imp["imported"][0]["name"] == "Hero", imp
        prev = await call("render_preview", view="front", width=256, height=256)
        kinds = [c.type for c in prev.content]
        assert "image" in kinds, kinds
        sheet = await call("render_views", views=["front", "right"], size=128)
        assert [c.type for c in sheet.content].count("image") == 2
        saved = await call("save_project", path="e2e.blend")
        # phase 2: character -> rig -> pose -> export
        await call("new_scene")
        await call("create_human", name="Hero", style="stylized")
        for rig_type in ("basic", "rigify"):
            rep = json.loads(text_of(await call("auto_rig_humanoid", mesh="Hero",
                                                rig_type=rig_type))[0])
            assert rep["ok"] and rep["unweighted_vertices"] == 0, rep
            assert rep["max_influences"] <= 4, rep
        await call("set_pose", armature="Hero_rig",
                   bones={"upper_arm_fk.L": [0, 0, 60], "shin_fk.R": [-45, 0, 0]})
        posed = await call("render_preview", view="three_quarter", width=256, height=256)
        assert "image" in [c.type for c in posed.content]
        glb = json.loads(text_of(await call("export_asset", path="e2e_hero_rigged.glb"))[0])
        assert glb["bytes"] > 10000, glb
        print("phase 2 rig:", rep["rig_type"], rep["deform_bones"], "deform bones")

        guide = await s.read_resource("char3d://guide")
        assert "Working loop" in guide.contents[0].text
        await call("engine_shutdown")
        print("saved:", text_of(saved))
        print("E2E OK")


asyncio.run(main())
