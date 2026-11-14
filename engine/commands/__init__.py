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


from . import scene, io, render, character, rig, anim, camera, lighting, video, mpfb  # noqa: E402,F401  (registers commands)
