"""char3d MCP server: exposes the Blender engine as tools for Claude, Codex, etc.

Run:  .venv/bin/python -m mcp_server.server     (stdio transport)
"""
import json
import os
from typing import Literal

import anyio
from mcp.server.fastmcp import FastMCP, Image

from providers import speech
from providers.jobs import JobManager

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
camera="scene" -> (add_subtitles for captions) -> render_video(quality="draft") -> render_options (let the user pick a
resolution, shown with estimated time) -> render_video(quality="preview"/"final", resolution=...).
Read resource char3d://guide for the full workflow guide.
"""

mcp = FastMCP("char3d", instructions=INSTRUCTIONS)
engine = BlenderClient()
ai = JobManager(engine)

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
async def export_asset(path: str, objects: list[str] | None = None,
                       max_influences: int | None = None) -> dict:
    """Export to .glb (recommended: mesh + rig + animation), .gltf, .fbx, .obj, .usd, or
    .bvh (animation only, first armature in `objects`/scene).
    `objects` limits the export to those objects and their children. max_influences:
    None keeps existing export behavior; a positive integer keeps the N largest deform
    weights per vertex and normalizes them on temporary copies (scene unchanged).
    Use 4 for games (Unity/Unreal/glTF). Returns vertices_limited (count trimmed)."""
    return await run("export_asset", path=path, objects=objects, max_influences=max_influences)


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
    """Create a procedural humanoid body (smooth stylized MANNEQUIN, no face/clothes),
    standing on Z=0, facing -Y. For realistic people use create_realistic_human.
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
                  speed: float = 1.0, amplitude: float = 1.0, in_place: bool = False,
                  foot_lock: bool | None = None, blend_frames: int | None = None) -> dict:
    """Keyframe a procedural motion clip on any humanoid rig. walk/run move the character
    forward (-Y) unless in_place. speed > 1 = faster, amplitude scales the motion.
    Chain clips with start_frame = previous result's next_start_frame.
    foot_lock (default auto: on for walk/run/jump unless in_place) pins planted feet to the
    floor with leg IK so they don't slide; the result lists the detected foot contacts.
    Crossfade: when the rig already has animation before start_frame, the clip blends in
    from that last pose (blend_frames None = automatic 4-18 frames by how big the change
    is, 0 = hard cut); the feet finish their step and stay planted through the blend."""
    return await run("animate", armature=armature, clip=clip, start_frame=start_frame,
                     cycles=cycles, speed=speed, amplitude=amplitude, in_place=in_place,
                     foot_lock=foot_lock, blend_frames=blend_frames)


@mcp.tool()
async def import_mocap(path: str, armature: str, start_frame: int = 1, in_place: bool = False,
                       bone_map: dict[str, str] | None = None, foot_lock: bool = True,
                       blend_frames: int | None = None) -> dict:
    """Load motion capture (.bvh, .fbx, .glb - e.g. CMU, Mixamo, Rokoko) and retarget it onto
    `armature`. Bone names, T/A rest pose, facing and body size are matched automatically;
    if bones are not recognised pass bone_map {"thigh.L": "their_left_thigh", ...}.
    foot_lock=True (default) removes the foot sliding retargeting causes. Like animate, it
    crossfades from earlier animation on the rig (blend_frames None = auto, 0 = hard cut)."""
    return await run("import_mocap", path=path, armature=armature, start_frame=start_frame,
                     in_place=in_place, bone_map=bone_map, foot_lock=foot_lock,
                     blend_frames=blend_frames)


@mcp.tool()
async def lock_feet(armature: str, frame_start: int | None = None, frame_end: int | None = None,
                    floor: float | None = None, height_tolerance: float | None = None,
                    speed_tolerance: float | None = None, blend_frames: int | None = None,
                    adjust_hips: bool = True,
                    contacts: dict[str, list[list[int]]] | None = None) -> dict:
    """Foot IK clean-up for an animation already on a rig (any clip, mocap, retarget): finds
    when each foot is planted, keeps it still on the floor (rolling heel -> toe, no sliding,
    no sinking into the floor) and re-solves the legs with IK, lowering the hips slightly when
    a leg can't reach. animate(walk/run/jump) and import_mocap already do this. Tune with
    height_tolerance (m above floor counted as contact), speed_tolerance (m/s drift allowed),
    floor (Z, default the rig's origin), or force contacts {"L": [[10, 27]], "R": [[1, 11]]}
    (frames; L = character's left)."""
    return await run("lock_feet", armature=armature, frame_start=frame_start,
                     frame_end=frame_end, floor=floor, height_tolerance=height_tolerance,
                     speed_tolerance=speed_tolerance, blend_frames=blend_frames,
                     adjust_hips=adjust_hips, contacts=contacts)


@mcp.tool()
async def retarget_animation(source: str, target: str, bone_map: dict[str, str] | None = None,
                             frame_start: int | None = None, frame_end: int | None = None,
                             dest_start: int | None = None, in_place: bool = False,
                             blend_frames: int | None = None) -> dict:
    """Copy the animation of one humanoid armature in the scene onto another (crossfades from
    earlier animation on the target: blend_frames None = auto, 0 = hard cut)."""
    return await run("retarget_animation", source=source, target=target, bone_map=bone_map,
                     frame_start=frame_start, frame_end=frame_end, dest_start=dest_start,
                     in_place=in_place, blend_frames=blend_frames)


@mcp.tool()
async def clear_animation(armature: str) -> dict:
    """Remove all keyframes from an armature and return it to rest pose."""
    return await run("clear_animation", armature=armature)


@mcp.tool(structured_output=False)
async def render_frames(frames: list[int], view: View = "three_quarter", size: int = 256,
                        objects: list[str] | None = None,
                        camera: Literal["auto", "scene"] = "auto",
                        engine_name: Engine = "workbench", subtitles: bool = True):
    """Render several animation frames (workbench) so you can check a motion like a
    flip-book. Tip: use view="right" to judge walking/running, and list the character
    mesh in `objects` so the camera frames it alone. camera="scene" shows the actual
    shots (use eevee to judge lighting) with the add_subtitles captions drawn on top
    (subtitles=False hides them)."""
    r = await run("render_frames", frames=frames, view=view, size=size, objects=objects,
                  camera=camera, engine=engine_name, subtitles=subtitles)
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
    """Replace the scene lighting aimed at subject (default: visible subjects, excluding sets):
    studio, soft, dramatic, sunset, noon, overcast, night, neon, silhouette, horror.
    rotate spins all lights around the subject (degrees). background overrides the sky
    color (RGB 0..1). ground adds a large floor at the subject's feet."""
    return await run("set_lighting", preset=preset, subject=subject, strength=strength,
                     rotate=rotate, background=background, ground=ground,
                     ground_color=ground_color)


Environment = Literal["podcast_studio", "classroom", "office", "stage", "living_room", "news_desk"]
Prop = Literal["chair", "desk", "table", "microphone", "laptop", "plant", "lamp", "screen",
               "bookshelf", "sofa", "whiteboard"]


@mcp.tool()
async def set_environment(preset: Environment, subject: list[str] | None = None,
                          scale: float = 1.0, variant: int = 0,
                          color_theme: str | dict[str, list[float]] | None = None,
                          screen_image: str | None = None) -> dict:
    """Replace all char3d sets/props with a procedural furnished set and practical lights.
    subject: character armature/mesh names (None = visible subjects; empty scene = origin).
    Furniture is sized to subject height * scale, anchored at its feet, facing -Y; the
    character is never moved. Podcast/news desks sit in front of the standing presenter;
    the stage platform top stays at their feet. Central -Y camera aisle stays open.
    variant: nonnegative deterministic seed (odd variants mirror side decor).
    color_theme: warm/cool/neutral or {wall, accent, fabric: [R,G,B]} overrides in 0..1.
    screen_image: optional local image, relative to imports/ or absolute; mapped upright
    across screens/whiteboards (stretched to fit). All objects are in char3d_env; returns
    object names and a transformable root. Set lighting and camera_shot separately with
    the character as subject. Replaces add_prop objects too; preserves characters/cameras
    and set_lighting lights. Static set: no automatic seating or collision avoidance."""
    return await run("set_environment", preset=preset, subject=subject, scale=scale,
                     variant=variant, color_theme=color_theme, screen_image=screen_image)


@mcp.tool()
async def add_prop(kind: Prop, location: list[float] = [0, 0, 0], rotation_z: float = 0,
                   scale: float = 1.0, screen_image: str | None = None) -> dict:
    """Add procedural furniture in char3d_env without replacing existing sets/props.
    location is the floor/base center in world meters; rotation_z is degrees about Z
    (0 faces -Y); scale is a positive uniform multiplier, independent of character height.
    Desk is standing height (1.02 m), table is a coffee table (0.43 m), microphone/laptop
    bases sit at location.z (use a desktop height). Lamp includes a practical light.
    screen_image: optional local image for screen/laptop/whiteboard, relative to imports/.
    Returns all part names and a root; move/rotate/scale that root to move the whole prop."""
    return await run("add_prop", kind=kind, location=location, rotation_z=rotation_z,
                     scale=scale, screen_image=screen_image)


@mcp.tool()
async def clear_environment() -> dict:
    """Remove all managed sets, props and practical lights (plus unused owned data).
    Preserves characters, cameras, set_lighting lights, ground and unrelated user objects.
    Returns removed names/count. Safe to call again when already empty."""
    return await run("clear_environment")


@mcp.tool()
async def set_material(objects: list[str], color: list[float] = [0.8, 0.8, 0.8],
                       roughness: float = 0.5, metallic: float = 0.0,
                       emission_strength: float = 0.0, name: str | None = None) -> dict:
    """Give objects one simple material: base color (RGB 0..1), roughness, metallic, and
    optional glow (emission_strength > 0 glows in the base color)."""
    return await run("set_material", objects=objects, color=color, roughness=roughness,
                     metallic=metallic, emission_strength=emission_strength, name=name)


Resolution = Literal["480p", "540p", "720p", "1080p", "1440p", "4k"]


@mcp.tool()
async def render_options(quality: Literal["draft", "preview", "final", "cycles"] = "final",
                         frame_start: int | None = None, frame_end: int | None = None,
                         vertical: bool = False, calibrate: bool = False) -> dict:
    """Resolution choices (480p..4k) with the estimated render time of THIS scene at the
    given quality ON THIS MACHINE. Call before a preview/final/cycles render and let the user
    pick the resolution (show size + estimated total time); then render_video(resolution=...).
    Speed is learned per machine from every finished render_video (`machine_speed`); when
    `machine_speed.measurements` is 0 the numbers are developer-machine defaults (CPU only) —
    pass calibrate=True to render one 480p test frame now (~5-20 s) and measure."""
    return await run("render_options", quality=quality, frame_start=frame_start,
                     frame_end=frame_end, vertical=vertical, calibrate=calibrate)


@mcp.tool()
async def render_video(path: str = "video.mp4", frame_start: int | None = None,
                       frame_end: int | None = None,
                       quality: Literal["draft", "preview", "final", "cycles"] = "preview",
                       resolution: Resolution | None = None, vertical: bool = False,
                       width: int | None = None, height: int | None = None,
                       fps: int | None = None, wait: bool = False,
                       subtitles: bool | None = None) -> dict:
    """Render the shot timeline to MP4 (H.264) in a BACKGROUND process; returns a job_id
    and an `estimate` of the render time.
    draft = clay workbench, half res (~0.1 s/frame) for checking timing/cameras;
    preview = Eevee half res (~3-4 s/frame here); final = Eevee full res 64 samples
    (~48 s/frame at 1080p with a realistic human); cycles = slowest, photoreal.
    resolution = output size chosen by the user (480p, 540p, 720p, 1080p, 1440p, 4k; renders
    at exactly that size for any quality); vertical=True for 9:16 (e.g. 1080x1920).
    width/height = custom size instead. Ask the user which resolution first
    (render_options lists them with time estimates). Poll render_status(job_id).
    wait=True blocks (only sensible for draft).
    subtitles: None = burn in the add_subtitles captions when set up (a short second pass
    after the frames; an .srt is also written next to the video), False = without captions."""
    return await run("render_video", path=path, frame_start=frame_start, frame_end=frame_end,
                     quality=quality, resolution=resolution, vertical=vertical, width=width,
                     height=height, fps=fps, wait=wait, subtitles=subtitles)


SubtitleStyle = Literal["tiktok", "karaoke", "classic"]


@mcp.tool()
async def add_subtitles(style: SubtitleStyle = "tiktok",
                        position: Literal["bottom", "lower_third", "center", "top"] | None = None,
                        size: float = 1.0, color: list[float] | None = None,
                        highlight_color: list[float] | None = None,
                        highlight: bool | None = None, uppercase: bool | None = None,
                        max_words: int | None = None, lines: list[dict] | None = None,
                        audio: str | None = None, language: str | None = None,
                        start_frame: int = 1, font: str | None = None) -> dict:
    """Captions burned into render_video (and shown by render_frames(camera="scene")).
    Words come from lip_sync / lip_sync_audio word times automatically (all speakers).
    style: "tiktok" = 1-3 big bold words at a time, the spoken word highlighted, pop-in
    (social/vertical video); "karaoke" = a full line with the current word highlighted;
    "classic" = plain film subtitles (1-2 lines, no highlight). position default: tiktok
    lower_third, others bottom. size scales the font; colors are RGB 0..1 (highlight default
    yellow). Other sources: lines=[{"text": "...", "start": 0.5, "end": 2.8}] (seconds from
    the scene start) or audio="audio/line.wav" (local Whisper transcript placed at
    start_frame) for voice-overs without a lip-synced character. Calling it again replaces
    the settings; remove_subtitles turns them off."""
    words = None
    if audio:
        path = _workspace_path(audio)
        tr = await anyio.to_thread.run_sync(lambda: speech.transcribe(path, language))
        words = tr["words"]
    return await run("add_subtitles", style=style, position=position, size=size, color=color,
                     highlight_color=highlight_color, highlight=highlight, uppercase=uppercase,
                     max_words=max_words, lines=lines, words=words, start_frame=start_frame,
                     font=font)


@mcp.tool()
async def remove_subtitles() -> dict:
    """Turn captions off (render_video renders without them)."""
    return await run("remove_subtitles")


@mcp.tool()
async def render_status(job_id: str | None = None) -> dict:
    """Progress of a render job (frames done, ETA, output path), or all jobs."""
    return await run("render_status", job_id=job_id)


@mcp.tool()
async def cancel_render(job_id: str) -> dict:
    """Stop a running render job."""
    return await run("cancel_render", job_id=job_id)


# --- realistic humans (MPFB) --------------------------------------------------------
Hair = Literal["afro01", "bob01", "bob02", "braid01", "long01", "ponytail01", "short01",
               "short02", "short03", "short04"]
MpfbRig = Literal["game_engine", "rigify", "default", "default_no_toes", "mixamo", "cmu_mb", "none"]


@mcp.tool()
async def mpfb_assets() -> dict:
    """Realistic-human assets available for create_realistic_human: skins, hair, eyebrows,
    eyelashes, eyes, clothes (incl. shoes, hats) and MPFB rigs."""
    return await run("mpfb_assets")


@mcp.tool()
async def create_realistic_human(name: str = "Person", gender: float = 0.5, age: float = 25,
                                 muscle: float = 0.5, weight: float = 0.5, height: float = 0.5,
                                 proportions: float = 0.5,
                                 race: dict[str, float] | None = None, skin: str = "auto",
                                 hair: Hair | None = None, eyebrows: str = "eyebrow001",
                                 eyelashes: str = "eyelashes01", eyes: str = "high-poly",
                                 clothes: list[str] | None = None, rig: MpfbRig = "game_engine",
                                 subdiv: int = 0, location: list[float] = [0, 0, 0],
                                 face: bool = True) -> dict:
    """Create a REALISTIC human (MakeHuman/MPFB, CC0): textured skin, eyes, eyebrows,
    eyelashes, optional hair and clothes, already rigged with hand-made skin weights.
    gender 0 = female .. 1 = male; age in years (1-90); muscle/weight/height/proportions
    0..1 (0.5 average); race e.g. {"asian": 1} or {"african": 0.5, "caucasian": 0.5}.
    skin "auto" picks age/gender/ethnicity-matched skin. clothes: names from mpfb_assets,
    e.g. ["male_casualsuit01", "shoes01"]. The rig works with apply_pose, animate,
    import_mocap and camera_shot (pass the armature name `<name>_rig` as subject).
    rig="game_engine" (53 bones, best for games/glTF) or "rigify" (full animator control
    rig incl. face controls, ~930 bones; slower, ~9 s). face=True loads ARKit face shapes +
    visemes and adds teeth/tongue so set_expression / lip_sync / auto_blink work."""
    return await run("create_realistic_human", name=name, gender=gender, age=age, muscle=muscle,
                     weight=weight, height=height, proportions=proportions, race=race,
                     skin=skin, hair=hair, eyebrows=eyebrows, eyelashes=eyelashes, eyes=eyes,
                     clothes=clothes, rig=rig, subdiv=subdiv, location=location, face=face)


Expression = Literal["neutral", "smile", "big_smile", "laugh", "sad", "angry", "furious",
                     "surprised", "fear", "disgust", "smirk", "wink_left", "wink_right",
                     "eyes_closed", "pout", "kiss", "thinking", "shout", "sleepy", "look_left",
                     "look_right", "look_up", "look_down", "tongue_out"]


@mcp.tool()
async def list_expressions() -> dict:
    """Facial expression presets (with the ARKit face units they use), all 52 ARKit unit
    names and the 22 viseme names."""
    return await run("list_expressions")


@mcp.tool()
async def set_expression(character: str, expression: Expression = "neutral",
                         units: dict[str, float] | None = None, strength: float = 1.0,
                         clear: bool = True, frame: int | None = None, keyframe: bool = False,
                         transition_frames: int = 6) -> dict:
    """Set a facial expression on a character (its armature `<name>_rig` or mesh). Works on
    create_realistic_human characters and any mesh with ARKit blendshapes. `units` adds or
    overrides raw ARKit weights 0..1 (e.g. {"jawOpen": 0.4}); strength scales the preset.
    keyframe=True keys it at `frame`, holding the previous face until
    frame - transition_frames, so a sequence of calls makes an animated performance."""
    return await run("set_expression", character=character, expression=expression, units=units,
                     strength=strength, clear=clear, frame=frame, keyframe=keyframe,
                     transition_frames=transition_frames)


@mcp.tool()
async def auto_expression(character: str, frame_start: int | None = None,
                          frame_end: int | None = None, base: Expression = "smile",
                          base_strength: float = 0.35, intensity: float = 1.0,
                          language: Literal["auto", "id", "ms", "en"] = "auto",
                          cues: list[dict] | None = None) -> dict:
    """Animate sentence emotions from the meaning of stored speech words (local lexicon,
    Indonesian/Malay + English; auto matches both). Run after lip_sync or lip_sync_audio
    with text/whisper timing; audio-only timing has no words. Detects joy, sadness,
    surprise, anger, fear/worry and thinking, suppresses nearby negated words, boosts !,
    and adds a slight questioning brow for ?. Emotions arrive ~0.2 s before sentences,
    hold through speech and relax to base in pauses. Range defaults to the scene range.
    Only brows/eyes/cheeks/nose and smile/frown corners are replaced in the range; jaw,
    mouth articulation/visemes, blink and gaze keys stay intact. Compatible with
    auto_blink in either order. Run before talk_motion (which adds brow/gaze accents).
    base_strength 0..1, intensity >=0 scales inferred emotions (not base or explicit cues).
    cues=[{"frame": 48, "expression": "sad", "strength": 0.7}] forces the containing
    sentence, or holds ~0.6 s without words; cues outside the range are ignored. Cues
    use the same protected channels as inferred expressions. Returns sentences with
    emotion, expression, strength, speech frames, keyed peak/hold frames and relax frame.
    This lexicon does not understand sarcasm or wider context."""
    return await run("auto_expression", character=character, frame_start=frame_start,
                     frame_end=frame_end, base=base, base_strength=base_strength,
                     intensity=intensity, language=language, cues=cues)


@mcp.tool()
async def lip_sync(character: str, text: str, start_frame: int = 1,
                   chars_per_second: float = 14.0, strength: float = 0.9,
                   expression: Expression | None = None) -> dict:
    """Animate the mouth to `text` (letter-to-viseme approximation; works for English and
    Indonesian-style spelling). No audio is generated - this is mouth motion only.
    chars_per_second ~14 = normal speech. Returns next_start_frame for chaining. Word times
    are stored so talk_gestures can add meaning gestures."""
    return await run("lip_sync", character=character, text=text, start_frame=start_frame,
                     chars_per_second=chars_per_second, strength=strength, expression=expression)


@mcp.tool()
async def auto_blink(character: str, frame_start: int | None = None, frame_end: int | None = None,
                     interval_seconds: float = 3.5) -> dict:
    """Add natural blinks over a frame range (defaults to the scene range)."""
    return await run("auto_blink", character=character, frame_start=frame_start,
                     frame_end=frame_end, interval_seconds=interval_seconds)


# --- audio & audio-driven lip sync ---------------------------------------------------
def _workspace_path(path: str, sub: str = "imports") -> str:
    p = os.path.expanduser(path)
    return p if os.path.isabs(p) else os.path.join(engine.workspace, sub, p)


@mcp.tool()
async def add_audio(path: str, start_frame: int = 1, volume: float = 1.0,
                    kind: Literal["voice", "music", "sfx"] = "voice", loop: bool = False,
                    fade_in: float = 0.0, fade_out: float = 0.0) -> dict:
    """Put a sound file (wav/mp3/flac/ogg/m4a) on the timeline; render_video then includes
    it as AAC audio. Relative paths are inside imports/. kind tags voice (default), music,
    or sfx. loop=True (music only) repeats to the current scene end and trims the last
    strip; set the timeline first. fade_in/fade_out are seconds across the whole track,
    including repeats. Returns the first strip and all repeat names in strips."""
    return await run("add_audio", path=path, start_frame=start_frame, volume=volume,
                     kind=kind, loop=loop, fade_in=fade_in, fade_out=fade_out)


@mcp.tool()
async def duck_music(music_strip: str | None = None, amount_db: float = -12,
                     attack: float = 0.15, release: float = 0.4) -> dict:
    """Lower music during speech using volume keys. music_strip=None selects all music;
    a strip name selects that track and its repeats. Speech is the union of unmuted voice
    strip spans (untagged legacy strips count as voice) and all stored lip-sync word times;
    gaps <= 0.5 s are merged. amount_db <= 0 is relative to the original track volume;
    attack seconds leads speech, release seconds follows it. Fades are preserved.
    Replaces selected music volume curves; safe to rerun after changing speech/timeline.
    Returns affected strips and merged speech_ranges in frames."""
    return await run("duck_music", music_strip=music_strip, amount_db=amount_db,
                     attack=attack, release=release)


@mcp.tool()
async def list_audio() -> dict:
    """Sound strips on the timeline, with names, kinds, frame spans, volumes and paths."""
    return await run("list_audio")


@mcp.tool()
async def remove_audio(name: str | None = None) -> dict:
    """Remove one sound strip by name, or all of them."""
    return await run("remove_audio", name=name)


@mcp.tool()
async def transcribe_audio(audio: str, language: str | None = None) -> dict:
    """Speech-to-text with word timestamps, fully local (Whisper). language e.g. "en", "id";
    None = auto-detect. First use downloads the model once (~75 MB)."""
    path = _workspace_path(audio)
    return await anyio.to_thread.run_sync(lambda: speech.transcribe(path, language))


@mcp.tool()
async def lip_sync_audio(character: str, audio: str, start_frame: int = 1,
                         text: str | None = None,
                         timing: Literal["auto", "whisper", "text", "audio"] = "auto",
                         language: str | None = None, strength: float = 0.9,
                         add_sound: bool = True, volume: float = 1.0,
                         expression: Expression | None = None) -> dict:
    """Lip-sync a character's mouth to a voice recording and (add_sound) put the audio on the
    timeline so render_video has sound. timing: "whisper" = local speech recognition gives
    exact word times (best; any language); "text" = spread the given `text` over the voiced
    parts; "audio" = guess mouth shapes from the sound alone; "auto" = whisper if available,
    else text if given, else audio. Combine with set_expression/auto_blink for life."""
    path = _workspace_path(audio)
    words, transcript = None, None
    use_whisper = timing == "whisper" or (timing == "auto" and speech.available())
    if use_whisper:
        tr = await anyio.to_thread.run_sync(lambda: speech.transcribe(path, language))
        words, transcript = tr["words"], tr["text"]
    r = await run("lip_sync_audio", character=character, audio=path, start_frame=start_frame,
                  words=words, text=None if timing == "audio" or words else text,
                  strength=strength, add_sound=add_sound, expression=expression, volume=volume)
    if transcript is not None:
        r["mode"] = "whisper"
        r["transcript"] = transcript
    return r


@mcp.tool()
async def talk_motion(character: str, frame_start: int | None = None, frame_end: int | None = None,
                      intensity: float = 1.0, head: bool = True, eyes: bool = True,
                      brows: bool = True, look_at_camera: bool = True, seed: int = 3,
                      look_at: str | None = None, listen_to: str | None = None) -> dict:
    """Make a speaking character feel alive: speech-driven head nods on stressed words,
    gentle head drift and phrase tilts, brow flashes, and eye saccades with occasional
    'thinking' glances. Rhythm comes from timeline voice audio (or the lip-sync keys).
    Layered on top: only neck/head rotation and brow/eye-gaze shape keys are keyed, body
    animation is untouched. look_at_camera turns eyes (and partly the head) toward the
    shot camera. Run it LAST, after animate/lip_sync_audio/camera_shot (re-running animate
    over the same frames would overwrite the head). intensity 0.5 = calm, 1.5 = animated.
    look_at = another character/object to look at instead of the camera; listen_to = a
    character whose stressed words get small listener nods while this one is silent
    (the `dialog` tool sets both automatically)."""
    return await run("talk_motion", character=character, frame_start=frame_start,
                     frame_end=frame_end, intensity=intensity, head=head, eyes=eyes, brows=brows,
                     look_at_camera=look_at_camera, seed=seed, look_at=look_at,
                     listen_to=listen_to)


@mcp.tool()
async def talk_gestures(character: str, frame_start: int | None = None,
                        frame_end: int | None = None,
                        style: Literal["calm", "presenter", "energetic"] = "presenter",
                        hands: Literal["both", "right", "left"] = "both",
                        intensity: float = 1.0, seed: int = 5, fingers: bool = True,
                        semantic: bool = True, cues: list[dict] | None = None) -> dict:
    """Speech-timed hand gestures: while talking the arms move into a speaking posture
    (hands in front of the belly) and hit beats, open-palm, sweep and point gestures on
    stressed words (stroke lands on the syllable), then relax back to the base animation in
    pauses. Rhythm from timeline voice audio or lip-sync keys. Layered: only arm/hand/finger
    rotations are keyed, legs/torso/head untouched; gestures follow the chest. Works on
    create_realistic_human, Rigify and basic rigs. Run after lip_sync_audio / lip_sync and
    body clips, before/after talk_motion (independent bones).
    semantic=True: words with a meaning get an iconic gesture instead of a beat (needs word
    times: lip_sync text or lip_sync_audio with whisper/text timing; Indonesian/Malay +
    English): numbers satu..lima/one..five -> fingers counted with palm forward,
    saya/I -> hand on chest, kamu/you -> palm-up offer, ini/itu -> point, besar/semua/big ->
    wide hands, kecil/small -> pinch, tidak/no -> palms-down wipe, bagus/great -> thumbs up,
    mungkin/apa/why -> palms-up shrug, tunggu/stop -> palm out, naik/turun -> hand rises/falls,
    bersama/kita -> hands come together, pikir/idea -> point at temple, cinta/terima kasih ->
    hands on heart. Result `semantic` lists word, gesture and frame.
    cues: force gestures yourself, e.g. [{"frame": 48, "gesture": "two"},
    {"frame": 90, "gesture": "big", "hands": "both", "hold_seconds": 0.8}] (gesture names as
    above; a cue replaces any word gesture near it).
    fingers=True also shapes the hands on rigs with finger bones (realistic humans,
    Mixamo/Rigify; mannequins have none - they still get the arm motion)."""
    return await run("talk_gestures", character=character, frame_start=frame_start,
                     frame_end=frame_end, style=style, hands=hands, intensity=intensity,
                     seed=seed, fingers=fingers, semantic=semantic, cues=cues)


# --- dialog --------------------------------------------------------------------------
@mcp.tool()
async def stage_dialog(characters: list[str], layout: Literal["angled", "face_to_face",
                       "side_by_side"] = "angled", distance: float = 1.3,
                       cheat_deg: float = 35.0, center: list[float] | None = None) -> dict:
    """Place 2-4 characters for a conversation (left to right in the given order): they face
    each other, "cheated" cheat_deg toward the camera side (-Y) so faces stay visible
    (angled); face_to_face = exact profile; side_by_side = both toward camera. distance in m."""
    return await run("stage_dialog", characters=characters, layout=layout, distance=distance,
                     cheat_deg=cheat_deg, center=center or [0.0, 0.0])


@mcp.tool()
async def dialog(lines: list[dict], characters: list[str] | None = None, stage: bool = True,
                 layout: Literal["angled", "face_to_face", "side_by_side"] = "angled",
                 distance: float = 1.3, start_frame: int = 1, gap_s: float = 0.35,
                 camera: Literal["mixed", "singles", "two_shot", "none"] = "mixed",
                 shot: Literal["medium_full", "medium", "medium_close", "close_up"] = "medium",
                 gestures: Literal["calm", "presenter", "energetic"] | None = "presenter",
                 expression: Expression | None = "smile", language: str | None = None) -> dict:
    """A conversation between 2-4 characters (realistic humans with faces work best), in one
    call. lines = [{"speaker": "Ana_rig", "audio": "audio/ana1.wav"},
                   {"speaker": "Budi_rig", "text": "Wah, ide yang bagus!"}, ...]
    — each line is lip-synced back to back (audio: local Whisper word timing, the sound goes
    on the timeline; text: mouth motion only), gap_s apart (per line "pause_s" overrides).
    Then: characters are staged facing each other (stage=False keeps your placement),
    everyone looks at whoever talks (the talker at the person they answer), listeners nod on
    stressed words, each speaker gestures on their own words (gestures=None: off), blinks,
    a light base expression, an idle clip on rigs without animation, and cameras: "mixed" =
    two-shot for the first line then a clean single of each speaker, cut 4 frames before
    they talk (same side of the action line). Run body clips (animate/walk) BEFORE this;
    add_subtitles afterwards for captions. Returns turns, shots, next_start_frame."""
    if not lines:
        raise ValueError("lines is empty")
    speakers = []
    for ln in lines:
        if "speaker" not in ln or not (ln.get("audio") or ln.get("text")):
            raise ValueError(f"each line needs speaker and audio or text: {ln}")
        if ln["speaker"] not in speakers:
            speakers.append(ln["speaker"])
    cast = characters or speakers
    if stage and len(cast) >= 2:
        fps = (await run("stage_dialog", characters=cast, layout=layout,
                         distance=distance))["fps"]
    else:
        fps = (await run("scene_info"))["fps"]
    frame = int(start_frame)
    turns = []
    for ln in lines:
        frame += int(round(float(ln.get("delay_s", 0)) * fps))
        if ln.get("audio"):
            path = _workspace_path(ln["audio"])
            words, transcript = None, None
            if speech.available():
                tr = await anyio.to_thread.run_sync(lambda: speech.transcribe(path, language))
                words, transcript = tr["words"], tr["text"]
            r = await run("lip_sync_audio", character=ln["speaker"], audio=path,
                          start_frame=frame, words=words,
                          text=None if words else ln.get("text"), strength=0.9, add_sound=True)
            text = transcript or ln.get("text")
        else:
            r = await run("lip_sync", character=ln["speaker"], text=ln["text"], start_frame=frame)
            text = ln["text"]
        a, b = r["frames"]
        turns.append({"speaker": ln["speaker"], "start": a, "end": b, "text": text})
        frame = b + 1 + int(round(float(ln.get("pause_s", gap_s)) * fps))
    d = await run("dialog_direct", turns=turns, characters=cast, camera=camera, shot=shot,
                  gestures=gestures, expression=expression)
    d["lines"] = turns
    d["next_start_frame"] = d["frames"][1] + 1
    return d


HandShape = Literal["relaxed", "open", "palm", "beat", "point", "fist", "thumbs_up", "peace",
                    "three", "four", "ok"]


@mcp.tool()
async def set_hand_pose(character: str, shape: HandShape = "relaxed",
                        side: Literal["both", "left", "right"] = "both", strength: float = 1.0,
                        frame: int | None = None, keyframe: bool = False) -> dict:
    """Pose the fingers: relaxed, open, palm, beat (half fist), point (index), fist,
    thumbs_up, peace (V), ok. Works on rigs with finger bones (create_realistic_human with
    any rig, Mixamo, Rigify human). Combine with apply_pose/set_pose for full gestures, e.g.
    apply_pose("point_forward") + set_hand_pose("point", side="right"). keyframe=True keys it
    at `frame`; strength < 1 for a softer version. 'left'/'right' = the character's own."""
    return await run("set_hand_pose", character=character, shape=shape, side=side,
                     strength=strength, frame=frame, keyframe=keyframe)


@mcp.tool(description=(
    "Generate a voice recording from text (Chatterbox Multilingual on a FREE public Hugging "
    "Face Space; queue/quota limits apply). language: ar da de el en es fi fr he hi it ja ko ms "
    "nl no pl pt ru sv sw tr zh (no Indonesian - 'ms' Malay is closest). voice_reference: "
    "optional short wav of a voice to imitate - ONLY the user's own voice or one they have "
    "permission to use. exaggeration 0.25-1.0 = expressiveness. Saves to imports/audio/; "
    "returns job_id - poll ai_job_status, then lip_sync_audio with the result's audio path. "
    "Sends the text (and reference voice) to a third-party service: only call it when the "
    "user asked for generated speech."))
async def ai_text_to_speech(text: str, language: str = "en", voice_reference: str | None = None,
                            exaggeration: float = 0.5, output: str | None = None) -> dict:
    return ai.text_to_speech(text, language, voice_reference, exaggeration, output)


# --- AI providers (phase 6) ----------------------------------------------------
AI_COST = (" Sends the prompt/image to an external AI service: provider='fal' is PAID "
           "(fal.ai, needs FAL_KEY); provider='hf' is FREE public Hugging Face Spaces (can "
           "queue, hit a daily GPU quota or be offline); 'auto' = fal if configured, else hf. "
           "Only call it when the user asked for AI generation. For hf, `model` picks a free "
           "Space recipe (see ai_status).")
Provider = Literal["auto", "fal", "hf"]


@mcp.tool()
async def prepare_model(objects: list[str], name: str = "Model", height: float | None = None,
                        max_faces: int | None = None, rotate_z: float = 0.0) -> dict:
    """Clean an imported model into ONE mesh ready for rigging: bake parent transforms,
    join pieces, weld duplicate vertices, decimate above `max_faces`, rotate about Z
    (use 180 if it faces +Y), scale to `height` m, center it and stand it on Z=0."""
    return await run("prepare_model", objects=objects, name=name, height=height,
                     max_faces=max_faces, rotate_z=rotate_z)


@mcp.tool()
async def ai_status() -> dict:
    """Which AI providers are usable: fal.ai (paid; FAL_KEY present? - never shows the key)
    and free Hugging Face Spaces (models/recipes per task, HF_TOKEN set?)."""
    return ai.status()


@mcp.tool(description=(
    "Generate a 3D model from text in the background: text -> concept image -> 3D mesh -> "
    "downloaded, imported, cleaned (prepare_model) and, for characters, auto-rigged. "
    "Returns job_id; poll ai_job_status, then render_views to inspect the result." + AI_COST))
async def ai_text_to_3d(prompt: str, name: str = "AIModel", character: bool = True,
                        rig: bool = True, rig_type: Literal["basic", "rigify"] = "basic",
                        height: float | None = None, max_faces: int = 60000,
                        model: str | None = None, image_model: str | None = None,
                        extra_input: dict | None = None,
        provider: Provider = "auto") -> dict:
    return ai.text_to_3d(prompt, name, character, rig, rig_type, height, max_faces,
                         image_model, model, extra_input, provider)


@mcp.tool(description=(
    "Generate a 3D model from an image (local path or https URL) in the background, then "
    "import, clean and (characters) auto-rig it. Best input: one subject, full body, A-pose, "
    "plain background. Returns job_id; poll ai_job_status." + AI_COST))
async def ai_image_to_3d(image: str, name: str = "AIModel", character: bool = True,
                         rig: bool = True, rig_type: Literal["basic", "rigify"] = "basic",
                         height: float | None = None, max_faces: int = 60000,
                         model: str | None = None, extra_input: dict | None = None,
        provider: Provider = "auto") -> dict:
    return ai.image_to_3d(image, name, character, rig, rig_type, height, max_faces, model,
                          extra_input, provider)


@mcp.tool(description=(
    "Animate a still into a video with an AI video model (Higgsfield/Kling style). `image` can "
    "be a char3d render (e.g. the path from render_preview camera='scene') or any image. "
    "Describe motion and camera in the prompt ('slow dolly in, hair blowing'). Saves the MP4 "
    "in renders/. Returns job_id; poll ai_job_status." + AI_COST))
async def ai_image_to_video(image: str, prompt: str, duration: int = 5,
                            aspect_ratio: str | None = None, model: str | None = None,
                            output: str | None = None, extra_input: dict | None = None,
        provider: Provider = "auto") -> dict:
    return ai.image_to_video(image, prompt, duration, aspect_ratio, model, extra_input, output,
                             provider)


@mcp.tool(description=(
    "Generate a video directly from text with an AI video model. Returns job_id; poll "
    "ai_job_status." + AI_COST))
async def ai_text_to_video(prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
                           model: str | None = None, output: str | None = None,
                           extra_input: dict | None = None,
        provider: Provider = "auto") -> dict:
    return ai.text_to_video(prompt, duration, aspect_ratio, model, extra_input, output,
                            provider)


@mcp.tool()
async def ai_job_status(job_id: str | None = None) -> dict:
    """Status of an AI job (stage, log, result files / imported mesh / rig report), or all."""
    return ai.get(job_id)


@mcp.tool()
async def ai_cancel_job(job_id: str) -> dict:
    """Cancel a running AI job (also cancels the request on the provider)."""
    return ai.cancel(job_id)


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
