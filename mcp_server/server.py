"""char3d MCP server: exposes the Blender engine as tools for Claude, Codex, etc.

Run:  .venv/bin/python -m mcp_server.server     (stdio transport)
"""
import json
import os
from typing import Literal

import anyio
from mcp.server.fastmcp import FastMCP, Image

from .blender_client import ROOT, BlenderClient

INSTRUCTIONS = """\
char3d drives a headless Blender to build 3D characters, rigs, animation and renders.

Conventions: meters, Z up, characters face -Y ("front"). Relative file paths resolve
inside the workspace: imports/ for import_model, exports/ for export_asset,
projects/ for save/open, renders/ for images.

Working loop:
1. scene_info first, to know what exists (names are case-sensitive).
2. Make one change at a time.
3. Check it visually with render_preview (workbench engine = fast, ~1s).
   Use eevee only for final looks (~10s on this machine, no GPU).
4. save_project at milestones; export_asset (.glb) to deliver assets.
Characters: create_human -> auto_rig_humanoid -> set_pose test -> render_views.
Read resource char3d://guide for the full workflow guide.
"""

mcp = FastMCP("char3d", instructions=INSTRUCTIONS)
engine = BlenderClient()

View = Literal["front", "back", "left", "right", "top", "three_quarter", "three_quarter_left"]
Engine = Literal["workbench", "eevee", "cycles"]
Primitive = Literal["cube", "sphere", "ico_sphere", "cylinder", "cone", "plane", "torus", "monkey"]


async def run(cmd: str, **params):
    params = {k: v for k, v in params.items() if v is not None}
    return await anyio.to_thread.run_sync(lambda: engine.call(cmd, **params))


# --- engine & scene ---------------------------------------------------------
@mcp.tool()
async def engine_status() -> dict:
    """Start the Blender engine if needed and report its version and workspace."""
    info = await run("ping")
    info["workspace"] = engine.workspace
    return info


@mcp.tool()
async def scene_info() -> dict:
    """List every object (type, transform, dimensions, mesh/armature stats, animation),
    the scene bounds, frame range, fps and active camera. Call this before editing."""
    return await run("scene_info")


@mcp.tool()
async def new_scene(fps: int = 24, frame_end: int = 120) -> dict:
    """Discard the current scene and start an empty one (no cube, camera or light).
    Unsaved work is lost: save_project first if it matters."""
    return await run("new_scene", fps=fps, frame_end=frame_end)


@mcp.tool()
async def add_primitive(kind: Primitive = "cube", name: str | None = None,
                        location: list[float] = [0, 0, 0], size: float = 1.0) -> dict:
    """Add a basic mesh (blockout, props, ground plane, test subject)."""
    return await run("add_primitive", kind=kind, name=name, location=location, size=size)


@mcp.tool()
async def transform_object(name: str, location: list[float] | None = None,
                           rotation_deg: list[float] | None = None,
                           scale: list[float] | None = None) -> dict:
    """Set location (m), rotation (XYZ Euler degrees) and/or scale of an object."""
    return await run("transform_object", name=name, location=location,
                     rotation_deg=rotation_deg, scale=scale)


@mcp.tool()
async def delete_objects(names: list[str]) -> dict:
    """Delete objects by exact name."""
    return await run("delete_objects", names=names)


# --- files --------------------------------------------------------------------
@mcp.tool()
async def import_model(path: str) -> dict:
    """Import .glb/.gltf/.fbx/.obj/.stl/.ply/.usd(z)/.bvh into the current scene.
    Returns the names of the new objects."""
    return await run("import_model", path=path)


@mcp.tool()
async def export_asset(path: str, objects: list[str] | None = None) -> dict:
    """Export to .glb (recommended: mesh + rig + animation), .gltf, .fbx, .obj or .usd.
    `objects` limits the export to those objects and their children."""
    return await run("export_asset", path=path, objects=objects)


@mcp.tool()
async def save_project(path: str = "scene.blend") -> dict:
    """Save the scene as a .blend file (relative paths go to projects/)."""
    return await run("save_project", path=path)


@mcp.tool()
async def open_project(path: str) -> dict:
    """Open a .blend file, replacing the current scene."""
    return await run("open_project", path=path)


# --- rendering ----------------------------------------------------------------
def _image_result(r: dict):
    return [Image(path=r["path"]), json.dumps(r)]


@mcp.tool(structured_output=False)
async def render_preview(view: View = "three_quarter", width: int = 512, height: int = 512,
                         engine_name: Engine = "workbench", frame: int | None = None,
                         objects: list[str] | None = None, transparent: bool = False):
    """Render a still from an auto-framed camera and return the image so you can SEE
    the result. workbench = fast clay/material preview (use for checking shape, pose,
    rig deformation); eevee = lit materials; cycles = slow, accurate.
    `objects` frames only those objects. `frame` sets the animation frame first."""
    r = await run("render_preview", view=view, width=width, height=height, engine=engine_name,
                  frame=frame, objects=objects, transparent=transparent)
    return _image_result(r)


@mcp.tool(structured_output=False)
async def render_views(views: list[View] = ["front", "right", "back", "three_quarter"],
                       size: int = 320, objects: list[str] | None = None,
                       frame: int | None = None):
    """Render several workbench views at once (model sheet) to inspect a character
    from all sides."""
    out = []
    for v in views:
        r = await run("render_preview", view=v, width=size, height=size, engine="workbench",
                      frame=frame, objects=objects)
        out += _image_result(r)
    return out


# --- characters & rigging (phase 2) -----------------------------------------
Style = Literal["realistic", "heroic", "stylized", "cartoon", "chibi"]
Gender = Literal["neutral", "male", "female"]


@mcp.tool()
async def create_human(name: str = "Human", height: float = 1.75, style: Style = "stylized",
                       gender: Gender = "neutral", build: float = 1.0, arm_angle: float = 35.0,
                       skin_color: list[float] = [0.80, 0.62, 0.50],
                       location: list[float] = [0, 0, 0]) -> dict:
    """Create a procedural humanoid body (smooth mannequin), standing on Z=0, facing -Y.
    style sets proportions in head units: realistic 7.5, heroic 8, stylized 6, cartoon 4.5,
    chibi 3. build scales thickness (0.7 slim .. 1.4 heavy). arm_angle: 0 = T-pose,
    35 = A-pose (best for rigging). Joint landmarks are stored on the mesh so
    auto_rig_humanoid fits bones exactly."""
    return await run("create_human", name=name, height=height, style=style, gender=gender,
                     build=build, arm_angle=arm_angle, skin_color=skin_color, location=location)


@mcp.tool()
async def estimate_landmarks(mesh: str) -> dict:
    """Show the joint landmarks (world coords) auto_rig_humanoid will use for a mesh:
    stored ones for create_human meshes, otherwise estimated from the shape (mesh must
    stand upright, face -Y, in T- or A-pose). Use it to inspect/correct before rigging."""
    return await run("estimate_landmarks", mesh=mesh)


@mcp.tool()
async def auto_rig_humanoid(mesh: str, rig_type: Literal["basic", "rigify"] = "basic",
                            landmarks: dict[str, list[float]] | None = None,
                            name: str | None = None) -> dict:
    """Build a humanoid armature for `mesh` and skin it with automatic weights
    (max 4 influences, normalized). basic = 21 deform bones (games, mocap, simple FK
    posing). rigify = full animator rig with FK/IK controls (limbs default to FK).
    `landmarks` overrides individual joints, e.g. {"elbow.L": [x, y, z]}; .R mirrors .L.
    Returns a validation report; check `ok` and `issues`, then render a test pose."""
    return await run("auto_rig_humanoid", mesh=mesh, rig_type=rig_type, landmarks=landmarks,
                     name=name)


@mcp.tool()
async def validate_rig(mesh: str) -> dict:
    """Check a rigged mesh: unweighted vertices, influences per vertex, unused bones."""
    return await run("validate_rig", mesh=mesh)


@mcp.tool()
async def list_bones(armature: str, deform_only: bool = False, contains: str | None = None) -> dict:
    """List bone names of an armature (filter with `contains`, e.g. "fk" or "arm")."""
    return await run("list_bones", armature=armature, deform_only=deform_only, contains=contains)


@mcp.tool()
async def set_pose(armature: str, bones: dict[str, list[float]] | None = None,
                   reset: bool = False, frame: int | None = None,
                   keyframe: bool = False) -> dict:
    """Rotate bones: {"bone": [x, y, z]} local Euler degrees. reset=True clears the pose
    first. With keyframe=True the pose is keyed at `frame` (simple animation).
    Axis meaning on char3d rigs: X+ = bend/lift toward the front (knees: use X-),
    Y = twist, Z = sideways (raise left arm Z+, right arm Z-). See char3d://guide."""
    return await run("set_pose", armature=armature, bones=bones, reset=reset, frame=frame,
                     keyframe=keyframe)


# --- escape hatch & lifecycle ------------------------------------------------
if os.environ.get("CHAR3D_ALLOW_PYTHON") == "1":
    @mcp.tool()
    async def run_blender_python(code: str) -> dict:
        """Run Python inside Blender (bpy, Vector available). Assign to `result` to return
        a JSON value. Prefer the dedicated tools; use this only when none fits."""
        return await run("run_python", code=code)


@mcp.tool()
async def engine_shutdown() -> str:
    """Stop the Blender engine started by this server (it restarts on the next call)."""
    await anyio.to_thread.run_sync(engine.stop)
    return "stopped"


@mcp.resource("char3d://guide", mime_type="text/markdown")
def guide() -> str:
    """Full workflow guide for agents."""
    with open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8") as f:
        return f.read()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
