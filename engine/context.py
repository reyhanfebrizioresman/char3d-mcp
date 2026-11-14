"""Shared engine state: workspace folder and path helpers."""
import os

WORKSPACE = None


def init(workspace):
    global WORKSPACE
    WORKSPACE = workspace
    for sub in ("renders", "exports", "projects", "imports"):
        os.makedirs(os.path.join(workspace, sub), exist_ok=True)


def resolve(path, default_dir=""):
    """Absolute paths pass through; relative ones land inside the workspace."""
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(WORKSPACE, default_dir, path)
