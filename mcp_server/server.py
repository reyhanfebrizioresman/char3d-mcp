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
Motion: apply_pose / animate / import_mocap -> render_frames to check it.
Film: set_lighting -> camera_shot (one per shot, consecutive frames) -> render_frames
camera="scene" -> render_video(quality="draft") -> render_video(quality="preview"/"final").
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
    """Export to .glb (recommended: mesh + rig + animation), .gltf, .fbx, .obj, .usd, or
    .bvh (animation only, first armature in `objects`/scene).
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
                         objects: list[str] | None = None, transparent: bool = False,
                         camera: Literal["auto", "scene"] = "auto"):
    """Render a still and return the image so you can SEE the result.
    camera="auto": temporary auto-framed camera from `view` (`objects` frames/isolates
    those objects). camera="scene": look through the shot camera active at `frame`
    (check your camera_shot framing; height follows the scene aspect).
    workbench = fast clay preview; eevee = real lights/materials (~2-10 s); cycles = slow."""
    r = await run("render_preview", view=view, width=width,
                  height=None if camera == "scene" else height, engine=engine_name,
                  frame=frame, objects=objects, transparent=transparent, camera=camera)
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


# --- animation (phase 3) -------------------------------------------------------
Pose = Literal["rest", "t_pose", "relaxed", "wave", "cheer", "point_forward", "hands_on_hips",
               "thinking", "crouch", "sit", "fight_stance", "run_pose"]
Clip = Literal["idle", "walk", "run", "wave", "cheer", "jump", "nod", "head_shake"]


@mcp.tool()
async def list_animations() -> dict:
    """Pose library and procedural clips available (with descriptions and cycle lengths)."""
    return await run("list_animations")


@mcp.tool()
async def apply_pose(armature: str, pose: Pose, frame: int | None = None,
                     keyframe: bool = False) -> dict:
    """Put a humanoid rig (basic, Rigify or imported Mixamo/CMU-style) into a library pose.
    keyframe=True keys it at `frame` (build pose-to-pose animation)."""
    return await run("apply_pose", armature=armature, pose=pose, frame=frame, keyframe=keyframe)


@mcp.tool()
async def animate(armature: str, clip: Clip, start_frame: int = 1, cycles: int = 2,
                  speed: float = 1.0, amplitude: float = 1.0, in_place: bool = False) -> dict:
    """Keyframe a procedural motion clip on any humanoid rig. walk/run move the character
    forward (-Y) unless in_place. speed > 1 = faster, amplitude scales the motion.
    Chain clips with start_frame = previous result's next_start_frame."""
    return await run("animate", armature=armature, clip=clip, start_frame=start_frame,
                     cycles=cycles, speed=speed, amplitude=amplitude, in_place=in_place)


@mcp.tool()
async def import_mocap(path: str, armature: str, start_frame: int = 1, in_place: bool = False,
                       bone_map: dict[str, str] | None = None) -> dict:
    """Load motion capture (.bvh, .fbx, .glb - e.g. CMU, Mixamo, Rokoko) and retarget it onto
    `armature`. Bone names, T/A rest pose, facing and body size are matched automatically;
    if bones are not recognised pass bone_map {"thigh.L": "their_left_thigh", ...}."""
    return await run("import_mocap", path=path, armature=armature, start_frame=start_frame,
                     in_place=in_place, bone_map=bone_map)


@mcp.tool()
async def retarget_animation(source: str, target: str, bone_map: dict[str, str] | None = None,
                             frame_start: int | None = None, frame_end: int | None = None,
                             dest_start: int | None = None, in_place: bool = False) -> dict:
    """Copy the animation of one humanoid armature in the scene onto another."""
    return await run("retarget_animation", source=source, target=target, bone_map=bone_map,
                     frame_start=frame_start, frame_end=frame_end, dest_start=dest_start,
                     in_place=in_place)


@mcp.tool()
async def clear_animation(armature: str) -> dict:
    """Remove all keyframes from an armature and return it to rest pose."""
    return await run("clear_animation", armature=armature)


@mcp.tool(structured_output=False)
async def render_frames(frames: list[int], view: View = "three_quarter", size: int = 256,
                        objects: list[str] | None = None,
                        camera: Literal["auto", "scene"] = "auto",
                        engine_name: Engine = "workbench"):
    """Render several animation frames (workbench) so you can check a motion like a
    flip-book. Tip: use view="right" to judge walking/running, and list the character
    mesh in `objects` so the camera frames it alone. camera="scene" shows the actual
    shots (use eevee to judge lighting)."""
    r = await run("render_frames", frames=frames, view=view, size=size, objects=objects,
                  camera=camera, engine=engine_name)
    out = []
    for item in r["frames"]:
        out += _image_result(item)
    return out


# --- camera, lighting, video (phase 4) -----------------------------------------
Move = Literal["static", "push_in", "dolly_in", "dolly_out", "pull_out", "orbit_left",
               "orbit_right", "arc", "crane_up", "crane_down", "truck_left", "truck_right",
               "pan_left", "pan_right", "tilt_up", "tilt_down", "zoom_in", "crash_zoom",
               "dolly_zoom", "handheld", "tracking", "tracking_side", "drone_reveal"]
ShotSize = Literal["extreme_wide", "wide", "full", "medium_full", "medium", "medium_close",
                   "close_up", "extreme_close_up"]
Light = Literal["studio", "soft", "dramatic", "sunset", "noon", "overcast", "night", "neon",
                "silhouette", "horror"]


@mcp.tool()
async def list_camera_moves() -> dict:
    """Describe every camera move and shot size."""
    return await run("list_camera_moves")


@mcp.tool()
async def camera_shot(subject: list[str] | None = None, shot: ShotSize = "medium",
                      move: Move = "static", start_frame: int = 1, end_frame: int = 72,
                      angle: float = 20.0, elevation: float = 5.0, intensity: float = 1.0,
                      ease: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "ease_in_out",
                      lens: float | None = None, handheld: float = 0.0, roll: float = 0.0,
                      depth_of_field: bool = False, f_stop: float = 2.8,
                      name: str | None = None) -> dict:
    """Create a cinematic shot camera for frames start..end, framed on `subject` (mesh or
    armature names; default = everything) even while it moves. angle: 0 = in front,
    90 = subject's left, 180 = behind. elevation: degrees (negative = low angle, heroic).
    intensity scales the move. handheld 0..1 adds shake, roll = dutch angle.
    Each shot adds a timeline marker, so consecutive shots CUT automatically in
    render_video. Chain with start_frame = previous next_start_frame. Re-using `name`
    replaces that shot."""
    return await run("camera_shot", subject=subject, shot=shot, move=move,
                     start_frame=start_frame, end_frame=end_frame, angle=angle,
                     elevation=elevation, intensity=intensity, ease=ease, lens=lens,
                     handheld=handheld, roll=roll, depth_of_field=depth_of_field,
                     f_stop=f_stop, name=name)


@mcp.tool()
async def list_shots() -> dict:
    """The shot timeline (marker, camera, frame range, settings) and total frame range."""
    return await run("list_shots")


@mcp.tool()
async def delete_shot(name: str) -> dict:
    """Remove a shot camera and its timeline marker."""
    return await run("delete_shot", name=name)


@mcp.tool()
async def set_timeline(frame_start: int | None = None, frame_end: int | None = None,
                       fps: int | None = None) -> dict:
    """Set the scene frame range and frame rate (24 default; 30/60 for social media)."""
    return await run("set_timeline", frame_start=frame_start, frame_end=frame_end, fps=fps)


@mcp.tool()
async def list_lighting_presets() -> dict:
    """Describe the lighting presets."""
    return await run("list_lighting_presets")


@mcp.tool()
async def set_lighting(preset: Light = "studio", subject: list[str] | None = None,
                       strength: float = 1.0, rotate: float = 0.0,
                       background: list[float] | None = None, ground: bool = True,
                       ground_color: list[float] = [0.32, 0.32, 0.33]) -> dict:
    """Replace the scene lighting with a preset aimed at `subject` (default: everything):
    studio, soft, dramatic, sunset, noon, overcast, night, neon, silhouette, horror.
    rotate spins all lights around the subject (degrees). background overrides the sky
    color (RGB 0..1). ground adds a large floor at the subject's feet."""
    return await run("set_lighting", preset=preset, subject=subject, strength=strength,
                     rotate=rotate, background=background, ground=ground,
                     ground_color=ground_color)


@mcp.tool()
async def set_material(objects: list[str], color: list[float] = [0.8, 0.8, 0.8],
                       roughness: float = 0.5, metallic: float = 0.0,
                       emission_strength: float = 0.0, name: str | None = None) -> dict:
    """Give objects one simple material: base color (RGB 0..1), roughness, metallic, and
    optional glow (emission_strength > 0 glows in the base color)."""
    return await run("set_material", objects=objects, color=color, roughness=roughness,
                     metallic=metallic, emission_strength=emission_strength, name=name)


@mcp.tool()
async def render_video(path: str = "video.mp4", frame_start: int | None = None,
                       frame_end: int | None = None,
                       quality: Literal["draft", "preview", "final", "cycles"] = "preview",
                       width: int | None = None, height: int | None = None,
                       fps: int | None = None, wait: bool = False) -> dict:
    """Render the shot timeline to MP4 (H.264) in a BACKGROUND process; returns a job_id.
    draft = clay workbench, half res (~0.1 s/frame) for checking timing/cameras;
    preview = Eevee half res (~3 s/frame here); final = Eevee full res 64 samples;
    cycles = slowest, photoreal. width/height e.g. 1920x1080, 1080x1920 (vertical).
    Poll render_status(job_id). wait=True blocks (only sensible for draft)."""
    return await run("render_video", path=path, frame_start=frame_start, frame_end=frame_end,
                     quality=quality, width=width, height=height, fps=fps, wait=wait)


@mcp.tool()
async def render_status(job_id: str | None = None) -> dict:
    """Progress of a render job (frames done, ETA, output path), or all jobs."""
    return await run("render_status", job_id=job_id)


@mcp.tool()
async def cancel_render(job_id: str) -> dict:
    """Stop a running render job."""
    return await run("cancel_render", job_id=job_id)


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
