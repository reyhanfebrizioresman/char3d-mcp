"""Run existing sections in isolation on 9972, using serial video snapshots."""
import argparse
import ast
import asyncio
import json
from pathlib import Path
import textwrap
from types import SimpleNamespace
from filmstyle_support import connection, snapshot_video, ROOT
import e2e_smoke as smoke
import filmstyle_checks


async def facial_talk(call, part=None):
    """Execute the existing inline facial/talk/dialog assertions without duplicating them.

    AST keeps embedded Blender code strings unchanged. Selection starts at the
    Dani/Rigify fixture and ends after the Vo/Ko dialog, inside the MPFB branch.
    """
    source = (ROOT/'tests/e2e_smoke.py').read_text()
    lines = source.splitlines()
    start = next(i+1 for i, line in enumerate(lines) if '# Rigify + face: expression, lip sync, blink' in line)
    end = next(i+1 for i, line in enumerate(lines) if 'aa = json.loads(text_of(await call("add_audio", path=wav' in line)
    audio = next(i+1 for i,line in enumerate(lines) if '# audio: synthetic "speech"' in line)
    tree = ast.parse(source)
    body = sorted((node for node in ast.walk(tree) if isinstance(node, ast.stmt)
                   and start < node.lineno < end and node.col_offset in (8,12)), key=lambda n:n.lineno)
    # Keep only top-level statements of the selected branch, excluding nested
    # statements with coincidentally equal indentation elsewhere.
    selected = []
    last = 0
    for node in body:
        if node.lineno > last:
            selected.append(node)
            last = node.end_lineno
    if part:
        selected=[node for node in selected if (node.lineno<audio)==(part=='facial')]
    fn = ast.AsyncFunctionDef(name='_existing_face_talk',
        args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='call'),ast.arg(arg='wav')],
                           kwonlyargs=[],kw_defaults=[],defaults=[]),body=selected,decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    namespace = dict(vars(smoke),s=call.session)
    exec(compile(module,'existing_facial_talk_checks','exec'),namespace)
    wav = smoke._synthetic_speech(str(ROOT/'output/imports/filmstyle_speech.wav'))
    await namespace['_existing_face_talk'](call,wav)
    print('EXISTING '+(part.upper() if part else 'FACIAL/TALK/DIALOG')+' E2E OK',flush=True)


async def main(section):
    async with connection() as (raw, data, python):
        async def call(tool, **args):
            print('CHECK',tool,flush=True)
            if tool == 'render_video':
                result = await snapshot_video(python,args)
                return SimpleNamespace(content=[SimpleNamespace(type='text',text=json.dumps(result))])
            return await raw(tool,**args)
        call.session=raw.session
        sections = {'fresh':lambda:filmstyle_checks.fresh_snapshot(call,smoke.text_of),
                    'defaults':lambda:filmstyle_checks.defaults(call,smoke.text_of),
                    'animated': lambda:filmstyle_checks.animated(call,smoke.text_of),
                    'life':lambda:filmstyle_checks.life(call,smoke.text_of),
                    'render-style':lambda:smoke._render_style_checks(call),
                    'cinematic':lambda:smoke._cinematic_checks(call),
                    'facial-talk':lambda:facial_talk(call),
                    'facial':lambda:facial_talk(call,'facial'),
                    'talk':lambda:facial_talk(call,'talk'),
                    'dialog':lambda:smoke._dialog_gaze_checks(call),
                    'script':lambda:smoke._script_scene_checks(call,single_engine=True)}
        await sections[section]()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('section',choices=['animated','life','fresh','defaults','render-style','cinematic','facial-talk','facial','talk','dialog','script'])
    asyncio.run(main(p.parse_args().section))
