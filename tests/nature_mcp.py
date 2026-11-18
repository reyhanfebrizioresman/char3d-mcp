"""Real MCP schemas and adapter round-trip, isolated to 9997."""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]


async def main():
    if os.environ.get('CHAR3D_PORT')!='9997': raise SystemExit('Use CHAR3D_PORT=9997')
    env=dict(os.environ,CHAR3D_ALLOW_PYTHON='1',CHAR3D_WORKSPACE=str(ROOT/'output'),
             XDG_CACHE_HOME=str(ROOT/'output/cache'),LP_NUM_THREADS='8')
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),env=env)
    async with stdio_client(params) as (r,w),ClientSession(r,w) as session:
        await session.initialize()
        tools={t.name:t for t in (await session.list_tools()).tools}
        assert {'nature_catalog','add_nature','clear_nature'} <= tools.keys()
        assert 'density' in tools['set_environment'].inputSchema['properties']
        async def call(name,**args):
            result=await session.call_tool(name,args)
            assert not result.isError,(name,result)
            return json.loads(next(b.text for b in result.content if b.type=='text'))
        await call('scene_info');await call('new_scene')
        catalog=await call('nature_catalog');assert len(catalog['generators'])==26
        a=await call('add_nature',kind='tree',params={'kind':'maple','height':3},seed=91)
        assert a['vertices']>1000 and a['root'] in a['objects'],a
        result=await session.call_tool('render_preview',dict(objects=[a['root']],engine_name='workbench',width=256,height=256))
        assert not result.isError,result
        await call('clear_nature')
        assert not (await call('scene_info'))['objects']
        await session.call_tool('engine_shutdown',{})
        print('NATURE MCP OK: schemas, catalog, add, render, clear',flush=True)


if __name__=='__main__': asyncio.run(main())
