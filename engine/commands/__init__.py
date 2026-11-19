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
from . import weather  # noqa: E402,F401

from . import cinematic  # noqa: E402,F401
from . import nature  # noqa: E402,F401
from . import world  # noqa: E402,F401
from . import film  # noqa: E402,F401
from . import materials  # noqa: E402,F401
from . import face_life  # noqa: E402,F401
from . import music  # noqa: E402,F401
