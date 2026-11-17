"""Command registry. Each module registers functions with @command."""
REGISTRY = {}


def command(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


def dispatch(name, params):
    fn = REGISTRY.get(name)
    if fn is None:
        raise KeyError(f"unknown command '{name}'. Known: {sorted(REGISTRY)}")
    return fn(**params)


from . import scene, io, render, character, rig, anim, camera, lighting, video, mpfb, face, audio, talk, gesture, fingers, footlock, subtitles, dialog, environment, walk, graphics, secondary, seating, holding, terrain  # noqa: E402,F401  (registers commands)
from . import script_scene, interaction  # noqa: E402,F401
from . import render_style  # noqa: E402,F401
from . import sfx  # noqa: E402,F401
