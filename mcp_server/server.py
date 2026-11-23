"""char3d MCP server: exposes the Blender engine as tools for Claude, Codex, etc.

Run:  .venv/bin/python -m mcp_server.server     (stdio transport)
"""
import json
import os
from typing import Literal
from engine.motion_library import MOTIONS

import anyio
from mcp.server.fastmcp import FastMCP, Image

from providers import speech
from providers.jobs import JobManager
from providers.tts import TTS
from providers.remote import RemoteRenders

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
Film: set_lighting -> camera_shot (one per shot, consecutive frames) -> optional
cinematic_look (after weather; golden_hour outdoors, studio_film indoors) -> render_frames
camera="scene" -> (add_subtitles for captions) -> render_video(quality="draft") -> render_options (let the user pick a
resolution, shown with estimated time) -> render_video(quality="preview"/"final", resolution=...).
Multi-scene: script_to_film(build=False) -> script_to_film -> open_film_scene for each
Eevee check/edit/save -> render_film(quality="draft") -> film_render_options (owner
chooses resolution) -> render_film. film_info reads the manifest; render_status and
cancel_render cover the whole film. script_to_scene rejects multi-scene scripts.
Remote video/film: target="name" from remote_targets(); first upload needs
consent_upload=True. Paid targets return a quote first; repeat with its quote_id
and confirm_cost=True only after the owner approves its price and budget/time caps.
Read resource char3d://guide for the full workflow guide.
"""

mcp = FastMCP("char3d", instructions=INSTRUCTIONS)
engine = BlenderClient()
ai = JobManager(engine)
tts = TTS(engine.workspace)
remote = RemoteRenders(engine)

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
    """Import .glb/.gltf/.fbx/.obj/.stl/.ply/.usd(z)/.bvh/.vrm into the scene.
    VRM 0.x/1.0 needs VRM Add-on for Blender (scripts/install_vrm.sh); maps declared
    humanoid bones and authored face morphs for char3d animation. Keep its rig.
    VRM models carry their own licences; the user is responsible for permission.
    Native hair/clothing springs can be baked by secondary_motion; keep its rig.
    Returns the names of the new objects and VRM mapping report when applicable."""
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
                         camera: str = "auto"):
    """Render a still and return the image so you can SEE the result.
    camera="auto": temporary auto-framed camera from `view` (`objects` frames/isolates
    those objects). A camera object name selects it directly. camera="scene": look through the shot camera active at `frame`
    (check your camera_shot framing; height follows the scene aspect).
    workbench = fast clay preview; eevee = real lights/materials (~2-10 s); cycles = slow."""
    r = await run("render_preview", view=view, width=width,
                  height=None if camera == "scene" else height, engine=engine_name,
                  frame=frame, objects=objects, transparent=transparent, camera=camera)
    return _image_result(r)


@mcp.tool(structured_output=False)
async def render_views(views: list[View] = ["front", "right", "back", "three_quarter"],
                       size: int = 320, objects: list[str] | None = None,
                       frame: int | None = None, engine_name: Engine = "workbench"):
    """Render several views (model sheet) to inspect a character from all sides.
    workbench checks shape; engine_name="eevee" shows skin, clothes and textures."""
    out = []
    for v in views:
        r = await run("render_preview", view=v, width=size, height=size, engine=engine_name,
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
               "thinking", "crouch", "sit", "fight_stance", "run_pose", *MOTIONS]
Clip = Literal["idle", "walk", "run", "wave", "cheer", "jump", "nod", "head_shake", *MOTIONS]


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
                  foot_lock: bool | None = None, blend_frames: int | None = None,
                  bpm: float | None = None, phase: Literal["full", "down", "hold", "up"] = "full",
                  collisions: bool = True) -> dict:
    """Keyframe a procedural motion clip on any humanoid rig. walk/run move the character
    forward (-Y) unless in_place. speed > 1 = faster, amplitude scales the motion.
    Chain clips with start_frame = previous result's next_start_frame.
    foot_lock (default auto: on for walk/run/jump unless in_place) pins planted feet to the
    floor with leg IK so they don't slide; the result lists the detected foot contacts.
    Crossfade: when the rig already has animation before start_frame, the clip blends in
    from that last pose (blend_frames None = automatic 4-18 frames by how big the change
    is, 0 = hard cut); the feet finish their step and stay planted through the blend.
    Dance clips accept bpm=30..240 (four beats/cycle; speed multiplies cadence).
    kneel phase: full/down/hold/up. type requires sit_on; drink/phone_call/read_book
    require a held cup/phone/book in either hand. list_animations reports all metadata.
    Action clips run bounded collision repair last; collisions=False disables it."""
    return await run("animate", armature=armature, clip=clip, start_frame=start_frame,
                     cycles=cycles, speed=speed, amplitude=amplitude, in_place=in_place,
                     foot_lock=foot_lock, blend_frames=blend_frames, bpm=bpm, phase=phase, collisions=collisions)


@mcp.tool()
async def resolve_collisions(characters: list[str] | None = None,
                             frame_start: int | None = None, frame_end: int | None = None,
                             parts: str | list[str] = 'all', clearance: float = 0.01,
                             max_iterations: int = 8, report_only: bool = False) -> dict:
    """Repair bounded collisions on baked humanoid performance. Meter units.
    Skin-fitted posed body proxies, evaluated furniture BVHs and held prop samples
    drive two-bone limb IK; wrist orientation, fingers, root, feet, face, attachments
    and camera are retained. parts: all/arms/props/legs/torso/clothes or a list.
    Corrections ease over .2s; large/unreachable/protected-contact conflicts report
    skipped reasons. report_only measures without writing keys or garment setup.
    Returns per-part before/after penetration, corrected frames, skips and timings.
    Automatic after gestures, interaction, seating, action motions, dialog/script;
    each authoring tool accepts collisions=False. Re-run after later motion edits.
    Proxies and sampled elastic garment chains are not exact mesh/finger physics."""
    return await run('resolve_collisions', characters=characters, frame_start=frame_start,
                     frame_end=frame_end, parts=parts, clearance=clearance,
                     max_iterations=max_iterations, report_only=report_only)


@mcp.tool()
async def secondary_motion(character: str, parts: list[str] = ['hair'],
                            frame_start: int | None = None, frame_end: int | None = None,
                            stiffness: float = 0.5, damping: float = 0.5, gravity: float = 1.0,
                            wind: list[float] | None = None, clear: bool = False,
                            collisions: bool = True) -> dict:
    """Bake deterministic hair and loose garment motion as skin bones (glTF/FBX).
    Run LAST, after body motion, seating and talk_motion. parts accepts 'hair',
    'clothes' (all eligible garments), or skinned garment object/asset names.
    Geometry below the hips and away from the legs forms short cloth chain rings;
    VRM actors reuse authored hair/clothing spring bones and collider groups,
    preserving their weights. Results include native chain and tip-offset details.
    tight trousers/shirts skip with reasons. Original weights blend at the waist.
    Reuses bones and replaces owned keys in the inclusive range; clear=True removes
    them. stiffness/damping: 0..1; gravity >= 0; wind: world XYZ acceleration.
    Omitted wind uses set_weather wind; rebake after changing weather.
    Conservative leg capsules and neighbouring tips constrain cloth; hair uses
    head/neck/shoulder/back capsules. collisions=True adds scene BVHs and posed peer/arm
    colliders to cloth; incompatible scene contacts remain reported. Not full fabric physics. Returns
    per-garment chains, tip lag, clearance, skipped reasons and total bake_seconds."""
    return await run('secondary_motion', character=character, parts=parts,
                     frame_start=frame_start, frame_end=frame_end, stiffness=stiffness,
                     damping=damping, gravity=gravity, wind=wind, clear=clear, collisions=collisions)


@mcp.tool()
async def walk_path(armature: str, points: list[list[float]],
                    clip: Literal["walk", "run"] = "walk", start_frame: int | None = None,
                    speed: float = 1.0, face_end: list[float] | str | None = None,
                    avoid: Literal["auto"] | bool = "auto", ignore: list[str] | None = None) -> dict:
    """Walk/run from the current position through absolute world XY points (meters).
    Curves pass through the points; duplicates are ignored. Body yaw is limited to 100
    degrees/s: tight bends slow down, corners over 100 degrees stop for stepping turns.
    speed (0.1..4) scales natural travel speed and cadence; shorter steps handle slowing.
    Foot IK keeps each planted foot's world position and rotation fixed through turns.
    Ends standing with both feet gathered. face_end optionally faces a world XY/XYZ point,
    object name or "camera" (sampled when the final turn begins). Works on basic, Rigify
    and MPFB rigs. start_frame=None appends after the rig's action, or uses the scene start.
    Returns frames, next_start_frame, distance_m, duration_seconds and foot_lock contacts.
    Z follows tagged walkable terrain: tread-fitting steps, raised swings and ramp pitch.
    Speed/cadence adapt locally: natural on level ground, slope-scaled on ramps, short
    walking steps on stairs (clip=run keeps running elsewhere).
    avoid="auto" (or True) snapshots visible obstacles/other characters at start_frame,
    inflates their XY footprints by body radius + 0.05 m, and uses 5 cm A* detours only
    when the original route intersects. Clear routes keep identical animation keys.
    False preserves the old route. ignore excludes named objects and descendants (use
    the chair root when approaching sit_on). Walkable tops/held props/ground are excluded;
    terrain edges over 0.25 m block passage. Blocked targets snap to nearest free cells
    with warnings. A start inside the clearance margin first steps out (<= 0.6 m, warning);
    a deeper blocked start or unreachable route raises before baking; the search
    extends 3..10 m beyond the targets, up to one million cells. Static convex mesh slices
    are conservative; this is body/root clearance, not a hand/foot or moving collision solver.
    Reports avoided, detours, path_points, body_radius_m, clearance_m (null without obstacles
    or with avoid=False), warnings and planning_seconds. For terrain,
    use rises <= 0.20 m and treads long enough for the whole sole. At most 1000 points and
    24000 frames per call. Reports contact heights, penetration and swing clearance."""
    return await run("walk_path", armature=armature, points=points, clip=clip,
                     start_frame=start_frame, speed=speed, face_end=face_end, avoid=avoid, ignore=ignore)


@mcp.tool()
async def turn_to(armature: str, target: list[float] | str,
                  start_frame: int | None = None, avoid: Literal["auto"] | bool = "auto",
                  ignore: list[str] | None = None) -> dict:
    """Turn in place with alternating lifted steps, then stand with planted feet.
    target is a world XY/XYZ point, object name or "camera", sampled at start_frame.
    Takes the shortest yaw turn, at most 100 degrees/s, without horizontal root travel.
    Works on basic, Rigify and MPFB rigs. start_frame=None appends to the rig's action.
    avoid="auto"/True checks the same static body envelope as walk_path and raises if
    blocked; it does not move the root. False skips the check. ignore excludes objects
    and descendants. Returns navigation clearance plus the usual turn/foot-lock report."""
    return await run("turn_to", armature=armature, target=target, start_frame=start_frame,
                     avoid=avoid, ignore=ignore)


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
                    contacts: dict[str, list[list[int]]] | None = None,
                    terrain: bool = True) -> dict:
    """Foot IK clean-up for an animation already on a rig (any clip, mocap, retarget): finds
    when each foot is planted, keeps it still on the floor (rolling heel -> toe, no sliding,
    no sinking into the floor) and re-solves the legs with IK, lowering the hips slightly when
    a leg can't reach. animate(walk/run/jump) and import_mocap already do this. Tune with
    height_tolerance (m above floor counted as contact), speed_tolerance (m/s drift allowed),
    floor (Z, default the rig's origin), or force contacts {"L": [[10, 27]], "R": [[1, 11]]}
    (frames; L = character's left). terrain=True raycasts tagged walkable meshes, detects
    contacts relative to local height and pitches soles to ramps. False uses only floor.
    For stairs use walk_path to plan safe tread placements and root height first."""
    return await run("lock_feet", armature=armature, frame_start=frame_start,
                     frame_end=frame_end, floor=floor, height_tolerance=height_tolerance,
                     speed_tolerance=speed_tolerance, blend_frames=blend_frames,
                     adjust_hips=adjust_hips, contacts=contacts, terrain=terrain)


@mcp.tool()
async def add_terrain(kind: Literal["stairs", "ramp", "platform", "step"],
                      location: list[float] | None = None, rotation_z: float = 0,
                      width: float = 1.2, length: float | None = None,
                      height: float | None = None, steps: int | None = None,
                      name: str | None = None) -> dict:
    """Create original walkable geometry in char3d_terrain (meters). location is the base
    at the near edge; width is centered on X, length extends along local -Y, rotated by
    rotation_z degrees. Stairs/ramp rise toward the far end. For descent rotate 180 degrees
    and place the low entrance at the far end. Stairs default to 5 x 0.17 m rise / 0.28 m
    tread; height/steps/length override these. Platform/step have flat tops. All meshes are
    tagged char3d_walkable, so walk_path and lock_feet can query them. No downloads."""
    return await run("add_terrain", kind=kind, location=location, rotation_z=rotation_z,
                     width=width, length=length, height=height, steps=steps, name=name)


@mcp.tool()
async def clear_terrain() -> dict:
    """Remove char3d_terrain geometry and its unused meshes/materials; preserve scenery."""
    return await run("clear_terrain")


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
                        engine_name: Engine = "workbench", subtitles: bool = True,
                        graphics: bool = True):
    """Render several animation frames (workbench) so you can check a motion like a
    flip-book. Tip: use view="right" to judge walking/running, and list the character
    mesh in `objects` so the camera frames it alone. camera="scene" shows the actual
    shots (use eevee to judge lighting) with the add_subtitles captions drawn on top
    (subtitles=False hides captions, graphics=False hides titles). Shot transitions
    are applied only in render_video; use a draft to check their timing."""
    r = await run("render_frames", frames=frames, view=view, size=size, objects=objects,
                  camera=camera, engine=engine_name, subtitles=subtitles, graphics=graphics)
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
                   "close_up", "extreme_close_up", "over_shoulder", "ots"]
Light = Literal["studio", "podcast", "soft", "dramatic", "sunset", "noon", "overcast", "night", "neon",
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
                      depth_of_field: bool | None = None, f_stop: float = 2.8,
                      name: str | None = None,
                      avoid_occlusion: Literal["auto"] | bool = "auto",
                      action_line: list[str] | None = None, require_composition: bool = False,
                      angle_limits: list[float] | None = None, face_coverage: bool = False,
                      coverage_turns: list[dict] | None = None, foreground: str | None = None) -> dict:
    """Create a cinematic shot camera for frames start..end, framed on `subject` (mesh or
    armature names; default = everything) even while it moves. angle: 0 = in front,
    90 = subject's left, 180 = behind. elevation: degrees (negative = low angle, heroic).
    intensity scales the move. handheld 0..1 adds shake, roll = dutch angle.
    depth_of_field=None follows an active cinematic look (otherwise off); explicit
    False opts this shot out, and True keeps its own f_stop and keyed focus distance.
    Each shot adds a timeline marker, so consecutive shots CUT automatically in
    render_video. Chain with start_frame = previous next_start_frame. Re-using `name`
    replaces that shot. avoid_occlusion="auto" (or True) samples evaluated face/eyes,
    head/chest visibility and foreground coverage across the shot. Fits aim/lens to
    preserve eye line, headroom and subject size while trying pedestal, angle and
    closer positions. Requires <=5% face occlusion and <=25% foreground (35% wide).
    Tries one wider size before retaining the original camera with a warning.
    Faces turned over 75 degrees away also trigger adjustment; face_angle reports
    the worst sampled angle in degrees. Frontal clear shots keep identical keys;
    False retains original framing. face_coverage=True follows the live head-facing
    direction while action_line/angle_limits constrain the camera side; coverage_turns
    optionally identifies the active speaker. Review repairs preserve these settings.
    shot="over_shoulder" ("ots") takes one facing subject plus foreground=partner,
    or subject=[facing_subject, partner]. Partner foreground is intentional; subject
    face/eyes must remain clear. The near shoulder joint anchors a rear head/shoulder
    foreground, roughly 20–35% of frame width, with a 50–85mm default lens. Returns
    foreground_composition plus sampled occlusion.foreground width/area/head angles.
    Cinematic focus tracks the subject's evaluated eye mesh when available.
    Returns
    occlusion fractions, frame_coverage_before/after, normalized face_screen eye
    positions (top-left origin), subject_scale, shot_size, adjustments and timing.
    Subject parts/held props and ground are ignored; other characters can occlude."""
    return await run("camera_shot", subject=subject, shot=shot, move=move,
                     start_frame=start_frame, end_frame=end_frame, angle=angle,
                     elevation=elevation, intensity=intensity, ease=ease, lens=lens,
                     handheld=handheld, roll=roll, depth_of_field=depth_of_field,
                     f_stop=f_stop, name=name, avoid_occlusion=avoid_occlusion,
                     action_line=action_line, require_composition=require_composition,
                     angle_limits=angle_limits, face_coverage=face_coverage, coverage_turns=coverage_turns, foreground=foreground)


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
                       ground_color: list[float] = [0.32, 0.32, 0.33],
                       follow: bool | Literal["auto"] = "auto") -> dict:
    """Replace the scene lighting aimed at subject (default: visible subjects, excluding sets):
    studio, soft, dramatic, sunset, noon, overcast, night, neon, silhouette, horror.
    rotate spins all lights around the subject (degrees). background overrides the sky
    color (RGB 0..1). ground adds a large floor at the subject's feet.
    On outdoor sets, noon/sunset/overcast/night drive sky/sun, retain character
    key/fill lights and suppress this extra ground plane.
    follow='auto' follows travel > 0.43 x standing height (~0.75 m); True follows
    any motion, False keeps lights static. SUN lights stay static. Call AFTER body
    animation (walk_path, animate, sit_on); rerun after motion changes. The smoothed
    rig follows XY and ground height, keeping standing light scale when sitting.
    Returns follow (actually used), travel_m and keys (location sample count)."""
    return await run("set_lighting", preset=preset, subject=subject, strength=strength,
                     rotate=rotate, background=background, ground=ground,
                     ground_color=ground_color, follow=follow)


Environment = Literal["podcast_studio", "classroom", "office", "stage", "living_room", "news_desk",
                      "city_street", "park", "cafe_terrace", "beach", "blossom_garden", "pine_forest",
                      "lakeside", "riverside", "rice_terraces", "mountain_village",
                      "forest", "mountain_lake", "village"]
Prop = Literal["chair", "desk", "table", "microphone", "laptop", "plant", "lamp", "screen",
               "bookshelf", "sofa", "whiteboard", "bench", "stool", "cup", "phone", "book",
               "handheld_microphone"]


@mcp.tool()
async def set_environment(preset: Environment, subject: list[str] | None = None,
                          scale: float = 1.0, variant: int = 0,
                          color_theme: str | dict[str, list[float]] | None = None,
                          screen_image: str | None = None, density: float = 1.0) -> dict:
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
    and set_lighting lights. Outdoor city_street/park/cafe_terrace/beach have walkable
    ground, seat metadata, distant backdrops and a procedural sky/sun. Outdoor lighting
    suppresses the extra ground plane; walk_path routes around static furniture.
    Use sit_on for benches, cafe chairs and the beach deck chair.
    Nature presets also include blossom_garden, pine_forest, lakeside, riverside,
    rice_terraces and mountain_village. density .2..2 scales their dressing (default 1);
    park and beach use the same original generators. Use nature_catalog/add_nature
    to compose custom worlds. Wind is saved procedural motion; no downloads."""
    return await run("set_environment", preset=preset, subject=subject, scale=scale,
                     variant=variant, color_theme=color_theme, screen_image=screen_image, density=density)


@mcp.tool()
async def nature_catalog() -> dict:
    """List deterministic nature generators, parameters, units and budgets.
    Trees (8 kinds), meadow/bush/flowers/rice, hills/ridges/rocks/cliff/path, water,
    clouds, animated petals/birds/butterflies/fireflies, fences, lanterns, bridges,
    gazebos and village houses. No downloads or paid services."""
    return await run('nature_catalog')


@mcp.tool()
async def add_nature(kind: str, location: list[float] | None = None, rotation_z: float = 0.,
                     scale: float = 1., seed: int = 0, params: dict | None = None,
                     name: str | None = None, camera_aware: bool = True,
                     area: list[float] | None = None, density: float | None = None,
                     season: str | None = None) -> dict:
    """Add procedural nature without replacing the set. Inspect nature_catalog first.
    Example: kind='tree', params={'kind':'blossom','height':5,'season':'spring'}.
    Positions are local meters under one transformable root; density means clumps/m².
    Foliage responds live to set_weather wind; rebake secondary hair/cloth separately.
    camera_aware snapshots existing shots at build time and thins distant patches;
    False keeps requested density/detail. The saved choice never switches per frame.
    Native motion survives save/open. clear_environment removes all managed props."""
    return await run('add_nature',kind=kind,location=location or [0,0,0],rotation_z=rotation_z,
                     scale=scale,seed=seed,params=params,name=name,camera_aware=camera_aware,
                     area=area,density=density,season=season)


@mcp.tool()
async def clear_nature() -> dict:
    """Remove standalone add_nature groups; preserve preset scenery and other props."""
    return await run('clear_nature')


@mcp.tool()
async def set_weather(kind: Literal["clear", "rain", "snow", "fog", "wind"] = "clear",
                      intensity: float = 0.5, wind: list[float] | None = None,
                      seed: int = 0) -> dict:
    """Replace procedural weather: clear, rain, snow, fog or wind (intensity 0..1).
    Seeded falling geometry renders in Eevee/workbench and survives video snapshots.
    Coverage follows all shot cameras' near frusta (24 m depth), refreshed on render/save.
    Fog uses bounded distance attenuation in Eevee; rain darkens the outdoor sky and
    lowers ground roughness. wind is world XYZ acceleration, reused by secondary_motion
    when its wind argument is omitted; rebake secondary motion after changing weather.
    clear restores owned ground/sky settings and removes all owned weather data.
    Set cameras before weather for predictable initial coverage. No external assets."""
    return await run("set_weather", kind=kind, intensity=intensity, wind=wind, seed=seed)


@mcp.tool()
async def add_prop(kind: Prop, location: list[float] | None = None, rotation_z: float = 0,
                   scale: float = 1.0, screen_image: str | None = None) -> dict:
    """Add procedural furniture in char3d_env without replacing existing sets/props.
    location is the floor/base center in world meters; rotation_z is degrees about Z
    (0 faces -Y); scale is a positive uniform multiplier, independent of character height.
    Desk is standing height (1.02 m), table is a coffee table (0.43 m), microphone/laptop
    bases sit at location.z (use a desktop height). Lamp includes a practical light.
    Cup/phone/book/handheld_microphone have grip-point origins; omit location to spawn
    at the latest visible humanoid's right palm (or origin without a character).
    screen_image: optional local image for screen/laptop/whiteboard, relative to imports/.
    Returns all part names and a root; move/rotate/scale that root to move the whole prop."""
    return await run("add_prop", kind=kind, location=location, rotation_z=rotation_z,
                     scale=scale, screen_image=screen_image)


@mcp.tool()
async def sit_on(character: str, seat: str, start_frame: int | None = None,
                 transition_frames: int = 20, seat_index: int = 0,
                 hands: Literal["thighs", "lap", "armrests", "desk", "none"] = "thighs",
                 collisions: bool = True) -> dict:
    """Sit a humanoid on a chair/sofa/bench/stool root or part, or a mesh's top surface.
    Metadata follows moved/rotated/scaled furniture; sofa and bench have two positions.
    Aligns the character to the seat front, measures buttock contact and solves flat feet.
    start_frame=None appends after the rig action; ease into sitting and hold to scene end.
    hands: thighs, lap, armrests (seat must have them), desk (palms on the desk/table in
    front; falls back to thighs when none is reachable), none. Layer talk_motion,
    talk_gestures or set_hand_pose afterwards. Static level seats and flat floors only;
    bounded hand/desk collision repair (collisions=False disables it). Returns contact/IK errors/timing."""
    return await run("sit_on", character=character, seat=seat, start_frame=start_frame,
                     transition_frames=transition_frames, seat_index=seat_index, hands=hands, collisions=collisions)


@mcp.tool()
async def stand_up(character: str, start_frame: int | None = None,
                   transition_frames: int = 20) -> dict:
    """Stand in front of the saved seat, with a smooth transition and flat feet.
    Call sit_on first. None appends after the rig's action; holds until scene end."""
    return await run("stand_up", character=character, start_frame=start_frame,
                     transition_frames=transition_frames)


@mcp.tool()
async def hold_prop(character: str, prop: str, hand: Literal["right", "left"] = "right",
                    start_frame: int | None = None, end_frame: int | None = None,
                    grip: Literal["auto", "fist", "cup", "relaxed", "open"] = "auto",
                    upright: bool | None = None) -> dict:
    """Attach a prop root/part to the palm; auto grip follows the prop kind.
    add_prop cup/phone/book/handheld_microphone use real sizes and grip origins; location
    may be omitted. None start uses current frame, None end keeps holding. The live
    attachment follows later arm keys. end_frame releases on the following frame.
    A released prop may be held again at/after its release frame, retaining earlier holds.
    upright=None auto-levels cups and points handheld microphones up with a slight
    lean toward the palm; True levels any prop, False keeps the rigid hand rotation.
    Upright holds constrain wrist roll/flex while preserving yaw; the grip stays in
    the palm. The finger grip is layered over later gestures until release.
    glTF export samples world transforms (including release) and includes props when
    exporting their character. Mannequins attach but have no fingers. No physics."""
    return await run("hold_prop", character=character, prop=prop, hand=hand,
                     start_frame=start_frame, end_frame=end_frame, grip=grip, upright=upright)


@mcp.tool()
async def release_prop(character: str, prop: str, frame: int,
                       place_at: list[float] | None = None) -> dict:
    """Release at frame: keep the prop's world transform, or put its grip at place_at.
    The prop remains static afterwards; no falling simulation. place_at is world XYZ."""
    return await run("release_prop", character=character, prop=prop, frame=frame, place_at=place_at)


@mcp.tool()
async def interact(a: str, b: str,
                   kind: Literal["handshake", "hug", "high_five", "fist_bump", "handover", "pat_shoulder"],
                   start_frame: int | None = None, prop: str | None = None,
                   approach: bool = True, hold_seconds: float | None = None,
                   side: Literal["right", "left"] = "right", collisions: bool = True) -> dict:
    """Two humanoids approach, reach a shared contact, hold and retract.
    Supports basic/Rigify/MPFB and different heights; finger poses skip mannequins.
    None start appends after both actions. Existing animation before start is kept.
    approach walks/turns with static obstacle avoidance; False requires reachable placement.
    handshake pumps, high_five claps, fist_bump meets knuckles, hug wraps both arms,
    pat_shoulder touches the nearby shoulder. handover requires prop held by a in side;
    transfers its live palm attachment to b at contact, preserving its world transform.
    Returns approach/reach/contact/release/end frames, next_start_frame, moved characters,
    contact_error_m and hug penetration_m (sampled chest/arm proxies, not mesh collision).
    hold_seconds overrides the kind's hold duration (0..30). Bounded proxy/BVH collision repair runs last; collisions=False disables it."""
    return await run("interact", a=a, b=b, kind=kind, start_frame=start_frame, prop=prop,
                     approach=approach, hold_seconds=hold_seconds, side=side, collisions=collisions)


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
async def cinematic_look(preset: str = "golden_hour", intensity: float = 1.0,
                         haze: float | bool | None = None, god_rays: float | bool | None = None,
                         bloom: float | bool | None = None, dof: str | bool = "auto",
                         particles: str | dict | bool | None = None, grade: dict | None = None,
                         sun: dict | None = None, clear: bool = False) -> dict:
    """Art-directed procedural atmosphere for lit stills and videos. Presets: golden_hour,
    sunset, misty_morning, blue_hour, night, overcast_soft, dreamy, epic, studio_film, none.
    Indonesian aliases: senja, matahari terbenam, pagi berkabut, malam, mimpi, epik.
    haze: density 0..0.1 per meter; god_rays/bloom: 0..1 or boolean. dof=auto tracks
    live eyes/head on existing/future character shots; explicit camera DOF takes precedence.
    particles: none/dust/pollen/petals/embers or {kind,count:0..500,seed}. sun: elevation,
    azimuth (degrees, 0=-Y, 90=+X). Grade supports render_style primitives plus lifted_blacks,
    vignette, grain, chromatic_aberration. All overrides are temporary and restored in finally.
    JSON survives save/open and video snapshots. render_style grade keys override look keys;
    bloom/vignette are merged once. Weather fog replaces look haze. Workbench is unchanged.
    clear=True or none removes the look, preserving original world/lights/cameras/settings.
    Apply after environment, lighting, cameras and weather. CPU cost is in render_options.
    """
    return await run("cinematic_look", preset=preset, intensity=intensity, haze=haze,
                     god_rays=god_rays, bloom=bloom, dof=dof, particles=particles,
                     grade=grade, sun=sun, clear=clear)


@mcp.tool()
async def render_style(style: Literal['none', 'anime', 'toon', 'clay', 'film', 'noir', 'vintage', 'animated_film', 'film_animasi', 'animasi'] = 'none',
                       strength: float = 1.0, outline: bool | None = None,
                       grade: dict | None = None, letterbox: bool | float | None = None) -> dict:
    """Set a non-destructive scene look, saved in .blend and used by lit stills/videos.

    none restores today's output; draft/workbench always keeps its existing look.
    anime/toon uses texture-preserving cel shading and opaque silhouette outlines;
    animated_film (film_animasi/animasi) uses four softened light masses, colored
    shadows and form gradients across humans/worlds, filtered color detail, warm
    skin, crisp eyes and stronger rims. Palettes follow cinematic looks. Original
    materials, alpha masks and practical emission survive.
    clay is uniform matte clay; film uses AgX, glow, vignette and grain; noir is high
    contrast monochrome; vintage is warm and faded. Alpha hair/eyes stay readable.
    strength: 0..1. outline: anime default True, False disables silhouettes.
    grade overrides: exposure (-8..8 stops), contrast/saturation (0..3, neutral 1),
    temperature/tint (-1..1), teal_orange (bool). letterbox=True adds 2.39:1 bars,
    or provide an aspect 1..4. Captions/titles stay above the grade and bars.
    render_options includes the style's render cost. Custom non-Principled shaders
    keep their shading. Anime uses Toon BSDF in Cycles; animated_film uses physical
    material/softbox/palette changes there instead of Eevee's light masses."""
    return await run('render_style', style=style, strength=strength, outline=outline,
                     grade=grade, letterbox=letterbox)


@mcp.tool()
async def render_options(quality: Literal["draft", "preview", "final", "cycles"] = "final",
                         frame_start: int | None = None, frame_end: int | None = None,
                         vertical: bool = False, calibrate: bool = False, target: str = 'local',
                         consent_upload: bool = False, confirm_cost: bool = False,
                         quote_id: str | None = None, max_budget_usd: float | None = None,
                         max_hours: float | None = None) -> dict:
    """Resolution choices (480p..4k) with the estimated render time of THIS scene at the
    given quality ON THIS MACHINE. Call before a preview/final/cycles render and let the user
    pick the resolution (show size + estimated total time); then render_video(resolution=...).
    Speed is learned per machine from every finished render_video (`machine_speed`); when
    `machine_speed.measurements` is 0 the numbers are developer-machine defaults (CPU only) —
    pass calibrate=True to render one 480p test frame now (~5-20 s) and measure.
    target="name" reports that target's time/cost; remote calibration requires upload
    consent and uses the same paid quote_id/confirm_cost flow as render_video."""
    if target != 'local':
        return await anyio.to_thread.run_sync(lambda: remote.options('video', target,
            dict(quality=quality, frame_start=frame_start, frame_end=frame_end, vertical=vertical),
            calibrate, consent_upload, confirm_cost, quote_id, max_budget_usd, max_hours))
    return await run("render_options", quality=quality, frame_start=frame_start,
                     frame_end=frame_end, vertical=vertical, calibrate=calibrate)


@mcp.tool()
async def render_video(path: str = "video.mp4", frame_start: int | None = None,
                       frame_end: int | None = None,
                       quality: Literal["draft", "preview", "final", "cycles"] = "preview",
                       resolution: Resolution | None = None, vertical: bool = False,
                       width: int | None = None, height: int | None = None,
                       fps: int | None = None, wait: bool = False,
                       subtitles: bool | None = None, credits: bool = True, target: str = 'local',
                       consent_upload: bool = False, confirm_cost: bool = False,
                       quote_id: str | None = None, max_budget_usd: float | None = None,
                       max_hours: float | None = None, fallback: str | None = None) -> dict:
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
    after the frames; an .srt is also written next to the video), False = without captions.
    Titles/transitions from add_title/add_transition always use the same compose pass.
    Crossfades render extra outgoing-camera frames; duration and audio timing stay fixed.
    target="name" uses an SSH/RunPod/Vast registry target. First upload requires
    consent_upload=True. Paid calls first return a quote without renting; repeat the
    same arguments with its quote_id and confirm_cost=True. max_budget_usd/max_hours
    can lower target caps. Remote jobs retain verified frames across disconnection/reboot;
    resume_job(job_id) resumes a failed/cancelled snapshot. Optional fallback="local" or
    an unpaid SSH target explicitly renders missing frames after the offline grace;
    another SSH upload requires its own consent. Frame provenance is in render_status."""
    if target != 'local':
        params = dict(path=path, frame_start=frame_start, frame_end=frame_end, quality=quality,
                      resolution=resolution, vertical=vertical, width=width, height=height, fps=fps,
                      subtitles=subtitles, credits=credits)
        result = await anyio.to_thread.run_sync(lambda: remote.start('video', target, params,
            consent_upload, confirm_cost, quote_id, max_budget_usd, max_hours,fallback=fallback))
        if wait and result.get('job_id'):
            return await anyio.to_thread.run_sync(lambda: remote.wait(result['job_id']))
        return result
    return await run("render_video", path=path, frame_start=frame_start, frame_end=frame_end,
                     quality=quality, resolution=resolution, vertical=vertical, width=width,
                     height=height, fps=fps, wait=wait, subtitles=subtitles, credits=credits)


SubtitleStyle = Literal["tiktok", "karaoke", "classic"]


@mcp.tool()
async def add_subtitles(style: SubtitleStyle = "tiktok",
                        position: Literal["bottom", "lower_third", "center", "top"] | None = None,
                        size: float = 1.0, color: list[float] | None = None,
                        highlight_color: list[float] | None = None,
                        highlight: bool | None = None, uppercase: bool | None = None,
                        max_words: int | None = None, lines: list[dict] | None = None,
                        audio: str | None = None, language: str | None = None,
                        start_frame: int = 1, font: str | None = None,
                        min_hold: float | None = None, hold: float | None = None,
                        max_cps: float | None = None, avoid_overlap: bool = True) -> dict:
    """Captions burned into render_video (and shown by render_frames(camera="scene")).
    Words come from lip_sync / lip_sync_audio word times automatically (all speakers).
    style: "tiktok" = 1-3 big bold words at a time, the spoken word highlighted, pop-in
    (social/vertical video); "karaoke" = a full line with the current word highlighted;
    "classic" = plain film subtitles (1-2 lines, no highlight). position default: tiktok
    lower_third, others bottom. size scales the font; colors are RGB 0..1 (highlight default
    yellow). Other sources: lines=[{"text": "...", "start": 0.5, "end": 2.8}] (seconds from
    the scene start) or audio="audio/line.wav" (local Whisper transcript placed at
    start_frame) for voice-overs without a lip-synced character. Calling it again replaces
    the settings; remove_subtitles turns them off. avoid_overlap=True measures face/mouth
    boxes and stacks captions with titles in free screen space for stills and movies."""
    words = None
    if audio:
        path = _workspace_path(audio)
        tr = await anyio.to_thread.run_sync(lambda: _transcribe_recorded(path, language))
        words = tr["words"]
    return await run("add_subtitles", style=style, position=position, size=size, color=color,
                     highlight_color=highlight_color, highlight=highlight, uppercase=uppercase,
                     max_words=max_words, lines=lines, words=words, start_frame=start_frame,
                     font=font, min_hold=min_hold, hold=hold, max_cps=max_cps, avoid_overlap=avoid_overlap)


@mcp.tool()
async def remove_subtitles() -> dict:
    """Turn captions off (render_video renders without them)."""
    return await run("remove_subtitles")


@mcp.tool()
async def layout_overlays() -> dict:
    """Keep captions clear of faces/mouths and stack titles without text overlap.
    Uses measured text and live camera projections for stills and movies; words,
    timing, colors and font choices are preserved. review_scene can apply this."""
    return await run('layout_overlays')


@mcp.tool()
async def add_transition(at_frame: int | None = None, shot: str | None = None,
                          kind: Literal["crossfade", "fade_black", "fade_white", "dip_black",
                                        "fade_in", "fade_out"] = "crossfade",
                          duration_s: float = 0.5, name: str | None = None) -> dict:
    """Add a video transition, or replace one by reusing name. Pass at_frame (the cut
    frame) OR shot (incoming shot marker/camera name). crossfade starts at the cut and
    blends extra outgoing-camera handle frames over the incoming shot for duration_s.
    Animation keeps moving; camera keys beyond the shot hold their last value. No frames
    are removed and audio stays synchronized. fade_black/dip_black and fade_white dip
    through black/white centered on the cut; fade_in/fade_out need no target and run at
    the scene start/end. Intervals must fit adjacent shots/the scene and cannot overlap.
    Applied by render_video's compose pass, including drafts; still previews show cuts."""
    return await run("add_transition", at_frame=at_frame, shot=shot, kind=kind,
                     duration_s=duration_s, name=name)


@mcp.tool()
async def add_title(text: str, subtitle: str | None = None, start_s: float = 0.0,
                     duration_s: float = 3.0,
                     style: Literal["center", "lower_third", "corner"] = "center",
                     name: str | None = None, size: float = 1.0,
                     color: list[float] = [1, 1, 1],
                     background_color: list[float] = [0.025, 0.035, 0.055],
                     background_opacity: float = 0.7,
                     animation: Literal["fade", "slide", "none"] | None = None,
                     animation_s: float = 0.3, font: str | None = None, avoid_overlap: bool = True) -> dict:
    """Add a title card or name/role tag over the shot timeline; reuse name to replace.
    start_s/duration_s are seconds from scene start. center = centered title/subtitle;
    lower_third = name + role on a translucent bar at bottom left; corner = top left.
    size scales text; colors are RGB 0..1 and background_opacity is 0..1 (0 hides the
    box). Text wraps/shrinks to fit. animation defaults to fade for center, slide for
    tags; animation_s is the in/out time (clamped to half the title). font is a local
    TTF/OTF path. Shows in render_frames(camera='scene') and render_video with captions;
    color fades cover the combined picture. avoid_overlap=True stacks around captions
    and visible faces, retaining the requested placement when clear. No scene geometry is added."""
    return await run("add_title", text=text, subtitle=subtitle, start_s=start_s,
                     duration_s=duration_s, style=style, name=name, size=size, color=color,
                     background_color=background_color, background_opacity=background_opacity,
                     animation=animation, animation_s=animation_s, font=font, avoid_overlap=avoid_overlap)


@mcp.tool()
async def list_graphics() -> dict:
    """List saved title and transition configs, including their names and timing."""
    return await run("list_graphics")


@mcp.tool()
async def remove_graphics(name: str | None = None, all: bool = False) -> dict:
    """Remove a named title/transition, or all graphics with all=True / name='all'.
    Captions have their own remove_subtitles tool."""
    return await run("remove_graphics", name=name, all=all)


async def _review_asr(report):
    """Optional local round-trip, outside Blender; never used by default review."""
    from engine.review import wer, issue, score, report_text
    import time
    started = time.perf_counter()
    from pathlib import Path
    segments = report.get('asr_segments', [])
    for scene in report.get('scenes', []):
        segments.extend(scene.get('asr_segments', []))
    results = []
    if not segments:
        report['asr_note'] = 'No stored voice-line references; round-trip WER is unavailable.'
    for segment in segments:
        try:
            tr = await anyio.to_thread.run_sync(lambda: _transcribe_recorded(segment['path'], None))
            error = wer(segment['text'], tr['text'])
            results.append(dict(segment, transcript=tr['text'], wer=round(error, 4)))
            if error > .25:
                report['issues'].append(issue('asr_words', 'sound', 'warn',
                    'Whisper differs from the stored voice line.', dict(wer=round(error, 4), transcript=tr['text'], reference=segment['text']),
                    frame=segment.get('frame'), character=segment.get('character')))
        except (RuntimeError, ValueError, OSError) as exc:
            results.append(dict(segment, unavailable=str(exc)))
    elapsed = time.perf_counter()-started
    report.setdefault('timings', {})['asr'] = round(elapsed, 4)
    report['timings']['total'] = round(report['timings'].get('total', 0)+elapsed, 4)
    if 'total_with_fix' in report['timings']:
        report['timings']['total_with_fix'] = round(report['timings']['total_with_fix']+elapsed, 4)
    report['asr'] = results
    if report.get('fix_rounds'):
        report['remaining'] = report['issues']
    report['score'], report['scores'] = score(report['issues'])
    if report.get('report_md'):
        Path(report['report_md']).write_text(report_text(report), encoding='utf-8')
        Path(report['report_md']).with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


@mcp.tool()
async def review_scene(level: Literal['quick', 'standard', 'full'] = 'standard', fix: bool = False,
                       sheet: bool = True, engine: Literal['workbench', 'eevee', 'cycles'] = 'workbench',
                       size: int = 384, asr: bool = False, frames: list[int] | None = None) -> dict:
    """Review sound, rhythm, camera, performance, continuity and readability with measured
    evidence and concrete tool suggestions. Low-resolution workbench stills, no ASR by
    default. sheet=True writes labelled contact/action PNGs and a Markdown report.
    fix=True applies exactly one safe deterministic fix round, then rechecks once;
    never changes story, script, cast or voices. size 64..512. Metrics are sampled
    proxies; Workbench exposure is provisional. asr=True adds local Whisper WER."""
    report = await run('review_scene', level=level, fix=fix, sheet=sheet, engine=engine,
                       size=size, asr=asr, frames=frames)
    return await _review_asr(report) if asr else report


@mcp.tool()
async def review_film(name: str | None = None, level: Literal['quick', 'standard', 'full'] = 'standard',
                      fix: bool = False, sheet: bool = True,
                      engine: Literal['workbench', 'eevee', 'cycles'] = 'workbench',
                      size: int = 384, asr: bool = False, frames: list[int] | None = None) -> dict:
    """Review every saved film scene and continuity/transition/card timing. Restores
    unsaved editor state afterwards. fix=True saves one safe fix round per scene.
    Writes a combined contact sheet and report under the film project folder."""
    report = await run('review_film', name=name, level=level, fix=fix, sheet=sheet,
                       engine=engine, size=size, asr=asr, frames=frames)
    return await _review_asr(report) if asr else report


@mcp.tool()
async def review_video(path: str, asr: bool = False) -> dict:
    """Inspect a rendered MP4 offline with PyAV/numpy, without starting Blender.
    Measures LUFS/true peak, clipping, near-black/frozen intervals, audio gaps and
    audio/video duration. Optional Whisper compares stored rendered voice lines."""
    from engine.review_media import review_video as inspect
    from pathlib import Path
    output = Path(path).expanduser()
    if not output.is_absolute():
        output = Path(engine.workspace)/'renders'/output
    sidecar = output.with_suffix('.review_lines.json')
    lines = json.loads(sidecar.read_text()) if asr and sidecar.is_file() else None
    report = await anyio.to_thread.run_sync(lambda: inspect(str(output), lines))
    return await _review_asr(report) if asr else report


@mcp.tool()
async def credits(path: str | None = None, card: bool = False, name: str | None = None) -> dict:
    """Write CREDITS.txt for assets actually referenced by this scene, or saved film
    name. Returns asset/licence/provenance JSON, including unknown user imports.
    card=True adds a three-second end card (saved final scene for a named film). Render tools
    write credits next to MP4 automatically; credits=False opts out."""
    return await run('credits', path=path, card=card, name=name)


@mcp.tool()
async def render_status(job_id: str | None = None) -> dict:
    """Progress of a render job (frames done, ETA, output path), or all jobs."""
    if job_id and job_id.startswith('remote_'):
        return await anyio.to_thread.run_sync(lambda: remote.report(job_id))
    result = await run("render_status", job_id=job_id)
    if job_id is None:
        result['jobs'] += await anyio.to_thread.run_sync(remote.status)
    return result


@mcp.tool()
async def cancel_render(job_id: str) -> dict:
    """Stop a running render job."""
    if job_id.startswith('remote_'):
        return await anyio.to_thread.run_sync(lambda: remote.cancel(job_id))
    return await run("cancel_render", job_id=job_id)


@mcp.tool()
async def resume_job(job_id: str, fallback: str | None = None, consent_upload: bool = False) -> dict:
    """Resume a failed/cancelled SSH render from verified durable frames on the same target.
    Optional fallback is local or another unpaid SSH target; new uploads require consent.
    Never creates/resumes a paid instance. cleanup_pending remains truthful while offline."""
    return await anyio.to_thread.run_sync(lambda:remote.resume_job(job_id,fallback,consent_upload))


@mcp.tool()
async def remote_targets() -> dict:
    """List ~/.config/char3d/targets.json and durable remote jobs/instances, costs and cleanup.
    SSH uses your own config/agent. Paid RunPod/Vast jobs first return an expiring quote;
    repeat the identical render call with quote_id and confirm_cost=True to create an instance.
    First upload to a target requires consent_upload=True. No API key is returned."""
    return await anyio.to_thread.run_sync(remote.list_targets)


@mcp.tool()
async def stop_target(name: str) -> dict:
    """Cancel all char3d jobs and terminate their paid instances for this target.
    Does not stop unrelated machines belonging to your account."""
    return await anyio.to_thread.run_sync(lambda: remote.stop_target(name))


# --- realistic humans (MPFB) --------------------------------------------------------
MpfbRig = Literal["game_engine", "rigify", "default", "default_no_toes", "mixamo", "cmu_mb", "none"]
Outfit = Literal["casual", "formal", "sport", "summer", "winter"]


@mcp.tool()
async def mpfb_assets() -> dict:
    """Realistic-human assets available for create_realistic_human: skins, hair, eyebrows,
    eyelashes, eyes, beards/moustaches, clothes (incl. shoes, hats, glasses) and rigs.
    clothing_categories groups clothing names by category; clothing_metadata gives each
    item's category, gender, display name, tags and z_depth. Includes optional CC0 packs.
    outfits lists deterministic outfit presets. Existing assets lists are unchanged."""
    return await run("mpfb_assets")


@mcp.tool()
async def create_realistic_human(name: str = "Person", gender: float = 0.5, age: float = 25,
                                 muscle: float = 0.5, weight: float = 0.5, height: float = 0.5,
                                 proportions: float = 0.5,
                                 race: dict[str, float] | None = None, skin: str = "auto",
                                 hair: str | None = None, eyebrows: str = "eyebrow001",
                                 eyelashes: str = "eyelashes01", eyes: str = "high-poly",
                                 clothes: list[str] | None = None, rig: MpfbRig = "game_engine",
                                 subdiv: int = 0, location: list[float] = [0, 0, 0],
                                 face: bool = True, beard: str | None = None,
                                 outfit: Outfit | None = None, seed: int = 0,
                                 materials: Literal["enhanced", "mpfb"] = "enhanced",
                                 style: Literal["realistic", "anime", "cartoon", "chibi"] | None = None,
                                 look: dict | None = None,
                                 hair_color: str | list[float] | None = None,
                                 skin_tone: str | list[float] | None = None) -> dict:
    """Create a REALISTIC human (MakeHuman/MPFB, CC0): textured skin, eyes, eyebrows,
    eyelashes, optional hair and clothes, already rigged with hand-made skin weights.
    gender 0 = female .. 1 = male; age in years (1-90); muscle/weight/height/proportions
    0..1 (0.5 average); race e.g. {"asian": 1} or {"african": 0.5, "caucasian": 0.5}.
    skin "auto" picks age/gender/ethnicity-matched skin. clothes: names from mpfb_assets,
    including hats/glasses; beard: a name from assets.beards (also includes moustaches).
    hair and skin accept all installed names. outfit: casual/formal/sport/summer/winter
    selects compatible installed clothes deterministically by seed and gender. Explicit
    clothes (even []) overrides outfit. Result warnings report missing outfit categories
    or overlapping exclusive clothing categories; explicit conflicts still load.
    The rig works with apply_pose, animate,
    import_mocap and camera_shot (pass the armature name `<name>_rig` as subject).
    rig="game_engine" (53 bones, best for games/glTF) or "rigify" (full animator control
    rig incl. face controls, ~930 bones; slower, ~9 s). face=True loads ARKit face shapes +
    visemes and adds teeth/tongue so set_expression / lip_sync / auto_blink work.
    materials="enhanced" preserves textures and improves skin/eyes/hair/fabric shading;
    "mpfb" keeps original shaders. upgrade_materials can switch existing characters.
    style chooses MPFB body proportions: realistic (unchanged default), anime (6.75
    heads), cartoon (4.75), chibi (2.8, 82% stature). Stylized bodies retain rig/morphs
    and use original flat toon materials. look replays a face_from_photo recipe; explicit
    style overrides the recipe. The recipe pins phenotype, face modifiers and pigment.
    Result suggests render_style('anime'); no global change.
    hair_color tints hair and brows (realistic only), keeping strand variation: black,
    dark_brown, brown, auburn, red, blonde, grey, or an sRGB triple 0..1.
    skin_tone light/medium/dark (or linear RGB) rebalances the skin texture toward that
    tone; with race unset and skin="auto" it also starts from the closest scan."""
    return await run("create_realistic_human", name=name, gender=gender, age=age, muscle=muscle,
                     weight=weight, height=height, proportions=proportions, race=race,
                     skin=skin, hair=hair, eyebrows=eyebrows, eyelashes=eyelashes, eyes=eyes,
                     clothes=clothes, rig=rig, subdiv=subdiv, location=location, face=face,
                     beard=beard, outfit=outfit, seed=seed, materials=materials, style=style, look=look,
                     hair_color=hair_color, skin_tone=skin_tone)


@mcp.tool()
async def upgrade_materials(character: str, quality: Literal["enhanced", "mpfb"] = "enhanced",
                            skin_tone: str | list[float] | None = None,
                            skin_detail: float = 1.0, hair_detail: float = 1.0) -> dict:
    """Improve an existing MPFB character's skin, eyes, hair and fabric, retaining textures.
    character is its armature or body. quality="mpfb" restores exact original materials.
    skin_tone: null samples the texture; light/medium/dark or linear RGB tunes scatter
    without recoloring the texture. Detail 0..2 scales pores/strand variation (default 1).
    Persistent in .blend/video snapshots. glTF uses a reported bake-free PBR fallback."""
    return await run("upgrade_materials", character=character, quality=quality,
                     skin_tone=skin_tone, skin_detail=skin_detail, hair_detail=hair_detail)


Expression = Literal["neutral", "smile", "big_smile", "laugh", "sad", "angry", "furious",
                     "surprised", "fear", "disgust", "smirk", "wink_left", "wink_right",
                     "eyes_closed", "pout", "kiss", "thinking", "shout", "sleepy", "look_left",
                     "look_right", "look_up", "look_down", "tongue_out"]


@mcp.tool()
async def face_from_photo(character: str, image: str, strength: float = 1.0,
                          texture: bool | None = None, consent: bool = False,
                          traits: dict | None = None, seed: int | None = None) -> dict:
    """Fit MPFB face traits from one frontal JPEG/PNG under workspace imports/.
    Requires consent=True: only your own face or a person who gave permission.
    Runs locally with installed OpenSeeFace ONNX CPU models, never uploads/downloads.
    texture=None defaults on for realistic, off for stylized characters. Generated
    UV texture/traits persist in saved .blend/exports; source photo is not copied.
    Returns projected fit error, modifier values, estimated skin/eye/hair colours,
    trait provenance, a reusable JSON look recipe and a local landmark likeness
    score (not identity verification; null if re-detection fails). traits can
    provide installed hair/beard/glasses names and colors_srgb pigment overrides.
    Install missing models with scripts/install_face_landmarks.sh; no OpenCV/torch."""
    return await run('face_from_photo', character=character, image=image,
                     strength=strength, texture=texture, consent=consent, traits=traits, seed=seed)


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
                   expression: Expression | None = None, language: str | None = None,
                   detail: Literal["phoneme", "word"] = "phoneme") -> dict:
    """Animate timed phonemes from text, with smooth coarticulation and closed m/b/p.
    language: id (Indonesian), ms (Malay), en (English), or auto/None (lexicon hit rate;
    ties use id). Spelling rules approximate pronunciation; no audio is generated.
    detail="word" keeps legacy letter-to-viseme timing. Default phoneme results include
    word, phoneme, viseme, start/end frames and peak frame (null for sub-frame phones).
    chars_per_second ~14 = normal speech. Returns next_start_frame for chaining. Word times
    are stored so talk_gestures can add meaning gestures."""
    return await run("lip_sync", character=character, text=text, start_frame=start_frame,
                     chars_per_second=chars_per_second, strength=strength, expression=expression,
                     language=language, detail=detail)


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
async def list_voices(language: str | None = None, engine: str | None = None) -> dict:
    """TTS engines, install commands, licenses, privacy and available voices/genders.
    Default catalog is offline; engine='edge' explicitly refreshes Microsoft's voice
    list (static fallback on network error). No models are downloaded. Piper is local;
    Edge and Chatterbox are online/explicit only. F5 needs a registered reference clip
    and transcript, or a built-in synthetic Piper reference: use only your own voice
    or one you have permission to use. The catalog never generates references."""
    return await anyio.to_thread.run_sync(lambda: tts.catalog(language, engine))


@mcp.tool()
async def text_to_speech(text: str, voice: str | None = None, engine: str = "piper",
                         language: str = "id", rate: float = 1.0, pitch: float = 0.0,
                         gender: float | None = None, output: str | None = None,
                         voice_reference: str | None = None, reference_text: str | None = None) -> dict:
    """Generate cached 48 kHz mono PCM WAV; path is relative to imports/, ready for
    lip_sync_audio/add_audio. voice='piper:id_ID-news_tts-medium',
    'edge:id-ID-GadisNeural', 'f5:<registered-name>' or 'chatterbox:ms'.
    rate is 0.5..2, pitch -12..12 semitones. No automatic model downloads.
    Default Piper is offline. Explicit Edge sends text to Microsoft (unofficial API);
    Chatterbox sends text to a quota-limited HF Space (no Indonesian). No fallback to
    online engines. F5 references require the user's own voice or permission to use it.
    F5 voice_reference (WAV, relative to imports or absolute) requires exact
    reference_text; built-in f5:female_adult/male_adult/elder/child use synthetic Piper.
    Returns path, duration_s, engine, voice, cached and privacy for online engines."""
    return await anyio.to_thread.run_sync(lambda: tts.synthesize(
        text, voice, engine, language, rate, pitch, gender, output, voice_reference, reference_text))


@mcp.tool()
async def cancel_tts() -> dict:
    """Cancel an active F5 inference and release its CPU worker/model RAM.
    The next F5 request starts a fresh worker. Cached WAVs remain available."""
    await anyio.to_thread.run_sync(tts.close)
    return {"stopped": True, "engine": "f5"}


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
async def auto_sfx(characters: list[str] | None = None, kinds: list[str] | None = None,
                    surface: str = "auto", volume: float = 1.0, seed: int = 0,
                    frame_start: int | None = None, frame_end: int | None = None,
                    clear: bool = False) -> dict:
    """Add original procedural footsteps, sit/stand, optional cloth, and quiet ambience.
    Run after body animation. Defaults: kinds=['footsteps','sit','ambience']; sit includes
    standing up. characters=None selects visible humanoid rigs. Footsteps use evaluated
    heel/ball/toe contacts shared with lock_feet; initial planted feet stay silent.
    surface='auto' checks ground tags/materials and the environment preset, or choose
    wood, concrete/tile, carpet, grass, gravel, sand. Seeded 48 kHz 16-bit WAVs are cached
    by content under imports/sfx/generated/. Reruns replace owned sounds in the selected
    scene range; clear=True only removes owned sounds (all kinds when kinds is omitted).
    Voice/music/manual sfx are preserved. Ambience loops with global fades at -30 dBFS RMS.
    Returns counts, strip paths/hashes/frames, and detected touchdowns. No samples/network.
    Detection is heuristic for imported motion; generic deep hip drops can resemble sitting.
    """
    return await run("auto_sfx", characters=characters, kinds=kinds, surface=surface,
                     volume=volume, seed=seed, frame_start=frame_start,
                     frame_end=frame_end, clear=clear)


@mcp.tool()
async def auto_music(mood: str = "auto", duration: float | None = None,
                     tempo: float | None = None, key: str | None = None,
                     intensity: float = .6, seed: int = 0, volume: float = .35,
                     follow_cuts: bool = True, follow_emotion: bool = True,
                     sections: list[dict] | None = None, fade_in: float = 1.,
                     fade_out: float = 2., clear: bool = False,
                     backend: Literal["auto", "soundfont", "synth"] = "auto") -> dict:
    """Compose original offline music, place it and duck -12 dB under dialog.
    Moods: happy/ceria, warm/hangat, sad/haru/sedih, romantic/romantis,
    tense/tegang, mysterious/misterius, epic/epik, calm/tenang, playful/lucu,
    nostalgic/nostalgia, dreamy, nusantara. Auto reads emotions, look, weather,
    location. Cuts/titles receive tonal accents; emotion peaks shape dynamics.
    duration defaults to scene range (seconds, max 600); tempo 40..180 BPM;
    key e.g. D minor. sections=[{frame, name?, intensity?}] adds dynamic cues.
    backend=auto uses a local GM SoundFont when installed, otherwise numpy synth.
    No downloads/network. Stereo 48 kHz 16-bit WAV,
    about -16 LUFS/-1 dBTP before volume/fades/ducking. Content-hash cache in
    imports/audio/music/generated. Reruns replace only owned scores; clear removes
    those scores. Returns mood/key/tempo, frames, sections, accents, path/hash,
    measured loudness and timings. Rule-based scoring, approximate LUFS/true peak.
    """
    return await run("auto_music", mood=mood, duration=duration, tempo=tempo, key=key,
        intensity=intensity, seed=seed, volume=volume, follow_cuts=follow_cuts,
        follow_emotion=follow_emotion, sections=sections, fade_in=fade_in, fade_out=fade_out, clear=clear,
        backend=backend)


@mcp.tool()
async def duck_music(music_strip: str | None = None, amount_db: float = -12,
                     attack: float = 0.15, release: float = 0.4) -> dict:
    """Lower music during speech using volume keys. music_strip=None selects all music;
    a strip name selects that track and its repeats. Ducks for audible parts of voice
    strips, including legacy untagged strips, and lip-sync words without a voice strip.
    Gaps <= 0.5 s are merged. amount_db <= 0 is relative to the original track volume;
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


def _transcribe_recorded(path, language=None):
    """Keep only model/source provenance under the workspace, never extra transcripts."""
    result = speech.transcribe(path, language)
    from pathlib import Path
    # Whisper itself serializes model inference. Registry writes are atomic too.
    lock = _transcribe_recorded.lock
    with lock:
        registry = Path(engine.workspace)/'imports/audio/asr_provenance.json'
        registry.parent.mkdir(parents=True, exist_ok=True)
        try:
            records = json.loads(registry.read_text())
        except (OSError, ValueError):
            records = {}
        records[str(Path(path).resolve())] = os.environ.get('CHAR3D_WHISPER_MODEL', 'tiny')
        temporary = registry.with_suffix('.tmp')
        temporary.write_text(json.dumps(records), encoding='utf-8')
        temporary.replace(registry)
    return result


import threading as _threading
_transcribe_recorded.lock = _threading.Lock()


@mcp.tool()
async def transcribe_audio(audio: str, language: str | None = None) -> dict:
    """Speech-to-text with word timestamps, fully local (Whisper). language e.g. "en", "id";
    None = auto-detect. First use downloads the model once (~75 MB)."""
    path = _workspace_path(audio)
    result = await anyio.to_thread.run_sync(lambda: _transcribe_recorded(path, language))
    return result


@mcp.tool()
async def lip_sync_audio(character: str, audio: str, start_frame: int = 1,
                         text: str | None = None,
                         timing: Literal["auto", "whisper", "text", "audio"] = "auto",
                         language: str | None = None, strength: float = 0.9,
                         add_sound: bool = True, volume: float = 1.0,
                         expression: Expression | None = None,
                         detail: Literal["phoneme", "word"] = "phoneme") -> dict:
    """Lip-sync a character's mouth to a voice recording and (add_sound) put the audio on the
    timeline so render_video has sound. timing: "whisper" = local speech recognition gives
    exact word times (best; any language); "text" = spread the given `text` over the voiced
    parts; "audio" = guess mouth shapes from the sound alone; "auto" = whisper if available,
    else text if given, else audio. With whisper/text, detail="phoneme" distributes
    spelling-derived phonemes INSIDE each word, with duration weights, rounding anticipation,
    full m/b/p closure and f/v contact. detail="word" keeps the old letter mapping.
    language: id/ms/en or auto/None (lexicon hit rate; ties use id). Whisper detects the
    transcription language when auto. Phoneme timing is approximate, not forced alignment.
    Results include language and phonemes with start/end/peak frames; audio-only mode
    stays acoustic (detail="audio"). Combine with set_expression/auto_blink for life."""
    path = _workspace_path(audio)
    words, transcript = None, None
    use_whisper = timing == "whisper" or (timing == "auto" and speech.available())
    if use_whisper:
        from engine.phonemes import choose_language
        asr_language = choose_language("", language) if language and language.lower() != "auto" else None
        tr = await anyio.to_thread.run_sync(lambda: _transcribe_recorded(path, asr_language))
        words, transcript = tr["words"], tr["text"]
    r = await run("lip_sync_audio", character=character, audio=path, start_frame=start_frame,
                  words=words, text=None if timing == "audio" or words else text,
                  strength=strength, add_sound=add_sound, expression=expression, volume=volume,
                  language=language, detail=detail)
    if transcript is not None:
        r["mode"] = "whisper"
        r["transcript"] = transcript
    return r


@mcp.tool()
async def talk_motion(character: str, frame_start: int | None = None, frame_end: int | None = None,
                      intensity: float = 1.0, head: bool = True, eyes: bool = True,
                      brows: bool = True, look_at_camera: bool = True, seed: int = 3,
                      look_at: str | None = None, listen_to: str | list[str] | None = None, life: float = 1.0) -> dict:
    """Make a speaking character feel alive: speech-driven head nods on stressed words,
    life=1 adds seeded micro-expressions, blink variation, micro-saccades and breathing
    in independent morphs; life=0 disables that layer (range 0..2).
    gentle head drift and phrase tilts, brow flashes, and eye saccades with occasional
    'thinking' glances. Rhythm comes from timeline voice audio (or the lip-sync keys).
    Layered on top: neck/head and brow/eye-gaze keys follow live posed head targets.
    Targets over 70 degrees to the side also turn the chest slightly; legs/root stay
    intact. look_at_camera turns eyes (and partly the head) toward the
    shot camera. Run it LAST, after animate/lip_sync_audio/camera_shot (re-running animate
    over the same frames would overwrite the head). intensity 0.5 = calm, 1.5 = animated.
    look_at = another character/object to look at instead of the camera; listen_to = a
    character to watch whose stressed words get small listener nods while this one is silent
    (the `dialog` tool sets both automatically)."""
    return await run("talk_motion", character=character, frame_start=frame_start,
                     frame_end=frame_end, intensity=intensity, head=head, eyes=eyes, brows=brows,
                     look_at_camera=look_at_camera, seed=seed, look_at=look_at,
                     listen_to=listen_to, life=life)


@mcp.tool()
async def face_life(character: str, frame_start: int | None = None, frame_end: int | None = None,
                    intensity: float = 1.0, seed: int = 3,
                    listen_to: str | list[str] | None = None, clear: bool = False) -> dict:
    """Bake seeded micro-expressions, held gaze/micro-saccades, varied emotion/cut
    blinks, listener reactions and breathing as independent additive morphs.
    Run after expressions/lip sync/gaze/cameras. Original viseme/body/arm keys stay
    intact; m/b/p closures gate mouth motion. intensity 0..2; 0/clear removes only
    this layer in range. Repeating the same seed replaces it deterministically.
    Eyelids follow vertical gaze. Authored pupil morphs are optional; eyeballs are
    never scaled. Wordless lip sync uses voice/viseme phrase timing.
    Saved native morph animation also works in video snapshots."""
    return await run('face_life', character=character, frame_start=frame_start,
                     frame_end=frame_end, intensity=intensity, seed=seed,
                     listen_to=listen_to, clear=clear)


@mcp.tool()
async def talk_gestures(character: str, frame_start: int | None = None,
                        frame_end: int | None = None,
                        style: Literal["calm", "presenter", "energetic"] = "presenter",
                        hands: Literal["both", "right", "left"] = "both",
                        intensity: float = 1.0, seed: int = 5, fingers: bool = True,
                        semantic: bool = True, cues: list[dict] | None = None, collisions: bool = True) -> dict:
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
                     seed=seed, fingers=fingers, semantic=semantic, cues=cues, collisions=collisions)


# --- Mode bebas: closed declarative world recipes -----------------------------
@mcp.tool()
async def world_schema() -> dict:
    """Published closed JSON Schema, generator catalog, parameter ranges and hard budgets.
    Pure local data, no Blender. Use this before composing original worlds."""
    from engine.world import world_schema as contract
    return contract()


@mcp.tool()
async def compose_world(recipe: dict, build: bool = True) -> dict:
    """Validate a declarative world. build=False returns normalized recipe, warnings,
    exact geometry estimate and budgets without starting Blender or changing a scene.
    Build replaces only the previous owned world; returns hero camera and staging.
    No authored Python, expressions, external assets or network are executed."""
    if not build:
        from engine.world import validate_recipe
        return {**await anyio.to_thread.run_sync(lambda: validate_recipe(recipe)), 'built': False}
    return await run('compose_world', recipe=recipe)


@mcp.tool()
async def clear_world() -> dict:
    """Remove only world-owned objects/data and restore owned atmosphere. Characters,
    user props and cameras survive. Recipes saved under worlds/ remain on disk."""
    return await run('clear_world')


@mcp.tool()
async def save_world(name: str, recipe: dict | None = None) -> dict:
    """Save the current or supplied validated recipe as workspace/worlds/name.json.
    Name is a simple identifier, never a filesystem path. Does not build."""
    return await run('save_world', name=name, recipe=recipe)


@mcp.tool()
async def load_world(name: str, build: bool = True) -> dict:
    """Load a saved world recipe. build=False validates/estimates without scene edits;
    True composes it. Use DUNIA: name or WORLD: name in a script."""
    return await run('load_world', name=name, build=build)


@mcp.tool()
async def direct_world(idea: str, generator: str = 'auto', consent: bool = False,
                       seed: int = 0, look: str | None = None) -> dict:
    """Idea → original world recipe, art-direction brief, warnings and budget estimate.
    offline uses ten seeded archetypes, no network/Blender. Claude API is paid;
    claude_cli uses subscription quota. Both require consent=True to send idea/options
    to Anthropic. One schema repair, then visible offline fallback on failure.
    Does not build or save; edit then compose_world(build=False), build and inspect."""
    from providers.director.world import direct_world as direct
    return await anyio.to_thread.run_sync(lambda: direct(idea, generator, consent, seed, look))


# --- dialog --------------------------------------------------------------------------
@mcp.tool()
async def director_status() -> dict:
    """Available draft generators, configured yes/no, privacy and pricing. No requests
    to Anthropic, no auth probe, no Blender. CLI login is checked on the first call."""
    from providers.director import status
    return await anyio.to_thread.run_sync(status)


@mcp.tool()
async def direct_scene(idea: str, generator: str = "auto", language: str = "id",
                        duration_s: float = 30, characters: int | None = None,
                        style: str | None = None, look: str | None = None,
                        location: str | None = None, seed: int = 0,
                        consent: bool = False) -> dict:
    """Idea → detailed director brief + validated char3d text script, without Blender
    or building a scene. Prefer writing scripts yourself as an agent; this drafts for
    the web UI/quick ideas. offline is free and seeded. claude uses the paid API;
    claude_cli uses Claude Code subscription quota. Both send the idea/options to
    Anthropic and require consent=True. auto prefers CLI, then API ONLY with consent;
    otherwise offline with a note. Failure returns offline with an explicit warning.
    Includes structured treatment and cue map, parse-only plan, usage and API cost estimate.
    Edit the script then call script_to_scene to preview/build it."""
    from providers.director import direct
    return await anyio.to_thread.run_sync(lambda: direct(
        idea, generator, language, duration_s, characters, style, look, location, seed, consent))


@mcp.tool()
async def script_to_scene(script: dict | str, name: str | None = None,
                          environment: str | None = None, lighting: str = "studio",
                          camera: Literal["directed", "emotional", "emosi", "mixed", "singles", "two_shot", "none"] = "directed",
                          subtitles: bool = True, language: str = "auto", seed: int = 0,
                          build: bool = True, sound: bool = True, voice: bool = True,
                          tts_engine: str = "piper", voices: dict | None = None,
                          look: str | dict | None = None,
                          body_language: bool = True, style: str | None = None,
                          life: float = 1.0, music: str | None = "auto",
                          treatment: dict | None = None, collisions: bool = True) -> dict:
    """Turn a short dict screenplay or Indonesian/English text into a renderable scene.

    camera="directed" (emosi/emotional) follows emotional intensity, adds OTS and
    visible listener reactions, and returns emotion_curve plus shot reasons.
    Explicit KAMERA/CAMERA cues override it; mixed retains speaker-only coverage.
    style="animated_film" or GAYA:/STYLE: animasi unifies the render look.
    life=1 enables seeded additive face life; 0 disables it (range 0..2).
    Optional look="golden_hour" or SUASANA:/LOOK:/MOOD: senja selects atmosphere.
    look=None with no header keeps existing output/cost; plan recommends a look.
    Text: JUDUL/TITLE: ..., LOKASI/LOCATION: podcast_studio, then
    ANA (perempuan, 28, rambut bob): Halo! and [Ana duduk di kursi].
    Dict: {title, environment, characters: [{id, gender, age, hair, clothes, race,
    outfit?, beard?, accessories?}],
    beats: [{say: id, text, audio?, emotion?}, {do: walk, who: id, to: [x,y]},
    {do: sit, who: id, on: chair}, {do: stand/hold/gesture/pose/look/pause, ...},
    {do: interact, who: id, with: partner, kind: handshake/hug/high_five/fist_bump/handover/pat_shoulder}]}.
    VRM actors: {id:'Nara', vrm:'vrm/model.vrm', gender?:0, age?:27}, or
    NARA (vrm: model.vrm, perempuan, 27): Halo! Paths stay under imports/;
    bare names prefer imports/vrm/. Parse-only reports embedded title/author/licence
    without importing. Gender/age are voice hints; wardrobe/hair/outfit descriptors
    warn and are ignored. The model's licence remains the user's responsibility.
    Text contacts: [Ana dan Budi bersalaman], [mereka berpelukan], [Ana tos dengan Budi],
    [Ana memberikan buku kepada Budi], or English equivalents. Handovers create/hold a
    known procedural prop when needed. Contact keys survive later speaking gestures.
    build=False returns a deterministic normalized plan and estimated frames with NO
    scene changes or audio transcription. Builds use existing body/dialog/camera tools,
    captions and hair/loose-cloth motion. voice=True synthesizes text with the chosen
    tts_engine (default offline Piper); missing TTS warns and keeps mouth motion.
    Per-character voice/pitch/rate or voices={id: {voice, pitch, rate}} overrides casting.
    Text descriptors: suara: edge:id-ID-GadisNeural, suara berat/tinggi.
    Edge/Chatterbox send text online ONLY when explicitly chosen; privacy is reported.
    build=False reports casting without synthesis/network. F5 references must be your
    own voice or used with permission. Existing audio always takes precedence.
    sound=True adds procedural footsteps, sit/stand and ambience after animation;
    sound=False disables generation. Results include sfx strip counts and paths.
    music='auto' adds an original offline score; MUSIC:/MUSIK: sets its mood or
    none/tanpa. music=None disables it independently of Foley. Plans report key/tempo.
    Outfit: casual/formal/sport/summer/winter (explicit clothes overrides it).
    Beard: catalog name or True for a seeded installed choice. Text also recognizes
    gaun/dress/rok/skirt, jenggot/beard/kumis/moustache, kacamata/glasses and topi/hat;
    accessories=['glasses', 'hat'] in dicts. Pack names are checked at build time;
    missing optional assets warn and outfits fall back to installed system suits.
    Generic seats hidden behind a peer or facing away get a clear guest chair facing
    the conversation (plan.guest_chairs and warnings); explicit object seats are honored.
    Dialog gaze and coverage follow the cast after walking, turning and sitting.
    body_language=True layers sentence emotions under speech gestures, with subtle
    listener reactions. Physical motion directions keep their authored performance.
    MPFB missing: rigged mannequins retain word times, audio, gestures and captions,
    without facial animation. Returns plan, character rig/mesh map, frames, shots,
    duration_s, warnings and per-stage timings. Nothing is saved automatically.
    """
    from engine.face_life import intensity as life_intensity
    life = life_intensity(life)
    import time
    from engine.script_plan import parse_script
    started = time.perf_counter()
    prepared = parse_script(script, name=name, environment=environment, seed=seed, look=look, style=style, music=music)
    if treatment is not None:
        from providers.director.treatment import validate_treatment
        prepared['treatment'] = validate_treatment(treatment)
    parse_warnings = list(prepared["warnings"])
    casting = tts.cast(prepared["characters"], tts_engine, language, seed, voices) if voice else {}
    report = {"generated_files": [], "cache_hits": 0, "warnings": [], "privacy": [], "tts_seconds": 0}
    if build and voice:
        prepared["beats"], report = await anyio.to_thread.run_sync(
            lambda: tts.prepare(prepared["beats"], casting, language))
    audio_started = time.perf_counter()
    if build:
        for beat in prepared["beats"]:
            if beat.get("audio") and "say" in beat:
                beat["audio"] = _workspace_path(beat["audio"])
                # Known TTS text uses voiced-interval timing, preserving exact spelling
                # without ASR downloads or transcription errors.
                if not beat.pop("tts_generated", False) and speech.available():
                    asr_language = None if language == "auto" else language
                    tr = await anyio.to_thread.run_sync(lambda: _transcribe_recorded(beat["audio"], asr_language))
                    beat["words"] = tr["words"]
                    beat["text"] = tr["text"] or beat.get("text", "")
    audio_seconds = time.perf_counter() - audio_started
    r = await run("script_to_scene", script=prepared, name=name, environment=environment,
                  lighting=lighting, camera=camera, subtitles=subtitles,
                  language=language, seed=seed, build=build, sound=sound, look=look,
                  body_language=body_language, style=style, life=life, music=music, collisions=collisions)
    r["plan"]["warnings"] = list(dict.fromkeys(parse_warnings + r["plan"].get("warnings", [])))
    r["voices"] = casting
    r["generated_files"] = report["generated_files"]
    r["cache_hits"] = report["cache_hits"]
    r["warnings"] = list(dict.fromkeys(parse_warnings + r.get("warnings", []) + report["warnings"]))
    if report["privacy"]:
        r["privacy"] = report["privacy"]
    r["timings"].update(total=round(time.perf_counter() - started, 4),
                         audio_prepare=round(audio_seconds, 4), tts=report["tts_seconds"])
    return r


@mcp.tool()
async def script_to_film(script: dict | str, name: str | None = None,
                         environment: str | None = None, lighting: str = "studio",
                         camera: Literal["directed", "emotional", "emosi", "mixed", "singles", "two_shot", "none"] = "directed",
                         subtitles: bool = True, language: str = "auto", seed: int = 0,
                         build: bool = True, sound: bool = True, voice: bool = True,
                         tts_engine: str = "piper", voices: dict | None = None,
                         look: str | dict | None = None, body_language: bool = True,
                         scene_index: int | None = None, style: str | None = None,
                         life: float = 1.0, music: str | None = "auto",
                          treatment: dict | None = None) -> dict:
    """Build a film from ADEGAN/SCENE headers or {title, characters, scenes:[...]}.

    Directed coverage is the default: per-scene emotion curves/reactions are saved
    in the manifest, with a wider opening after a close ending in the previous scene.
    Each scene has name, environment, look, weather, lighting, card, transition_in,
    beats and optional cast. Declarations persist across scenes. [Ana berganti baju
    formal] / [Ana changes into formal] changes her outfit for this and later scenes.
    Use changes before the scene's action/dialogue. TRANSISI/TRANSITION between
    headers accepts cut, dissolve, fade_black/dip_black, fade_white plus seconds.
    KARTU/CARD inserts a centered card (default 2 s). Dissolves overlap scenes;
    dips preserve the cut duration. Characters retain global seeds and voice casting.
    build=False is deterministic, has no Blender/file/audio/network side effects.
    Builds save projects/<name>/scene_01.blend etc and film.json. scene_index is an
    optional one-based rebuild; other changed scenes require rebuilding all.
    This replaces the current editor scene; save existing work first. Inspect each
    scene with open_film_scene and Eevee. Then film_render_options + render_film.
    Voice/privacy and component limitations match script_to_scene.
    MUSIC:/MUSIK: selects each scene's score (auto by default); music=None disables
    all generated scores. Film renders join compatible moods and crossfade changes,
    scoring cards/cuts and ducking speech on the final timeline.
    """
    from engine.face_life import intensity as life_intensity
    life = life_intensity(life)
    from engine.film_plan import parse_film
    import copy
    plan = parse_film(script, name=name, environment=environment, seed=seed, look=look, lighting=lighting, style=style, music=music)
    if treatment is not None:
        from providers.director.treatment import validate_treatment
        plan['treatment'] = validate_treatment(treatment)
        for scene in plan['scenes']:
            scene['plan']['treatment'] = treatment
    casting = tts.cast(plan["characters"], tts_engine, language, seed, voices) if voice else {}
    plan["voices"] = casting
    if not build:
        return dict(kind="film", built=False, plan=plan, voices=casting,
                    frames=plan["estimated_frames"], duration_s=plan["duration_s"], warnings=plan["warnings"])
    prepared = copy.deepcopy(plan)
    reports = []
    for scene in prepared["scenes"]:
        if scene_index is not None and scene["index"] != scene_index:
            continue
        beats = scene["plan"]["beats"]
        report = {"generated_files": [], "cache_hits": 0, "warnings": [], "privacy": [], "tts_seconds": 0}
        if voice:
            beats, report = await anyio.to_thread.run_sync(lambda: tts.prepare(beats, casting, language))
        for beat in beats:
            if beat.get("audio") and "say" in beat:
                beat["audio"] = _workspace_path(beat["audio"])
                if not beat.pop("tts_generated", False) and speech.available():
                    tr = await anyio.to_thread.run_sync(lambda: _transcribe_recorded(
                        beat["audio"], None if language == "auto" else language))
                    beat["words"] = tr["words"]
                    beat["text"] = tr["text"] or beat.get("text", "")
        scene["plan"]["beats"] = beats
        reports.append(report)
    prepared["warnings"] = list(dict.fromkeys(prepared["warnings"] + [w for r in reports for w in r["warnings"]]))
    result = await run("script_to_film", script=script, name=plan["name"], lighting=lighting,
        camera=camera, subtitles=subtitles, language=language, seed=seed, build=True,
        sound=sound, look=look, body_language=body_language, scene_index=scene_index, _plan=prepared, style=style, life=life, music=music)
    result["voices"] = casting
    result["generated_files"] = [f for r in reports for f in r["generated_files"]]
    result["cache_hits"] = sum(r["cache_hits"] for r in reports)
    result["warnings"] = list(dict.fromkeys(result["warnings"] + [w for r in reports for w in r["warnings"]]))
    result["privacy"] = list(dict.fromkeys(p for r in reports for p in r["privacy"]))
    return result


@mcp.tool()
async def film_info(name: str | None = None) -> dict:
    """Read a saved film manifest. Omit name for the active film or available films."""
    return await run("film_info", name=name)


@mcp.tool()
async def open_film_scene(name: str, index: int) -> dict:
    """Open a film scene (one-based index). Save edits with save_project to its path.
    Replaces the current editor scene, so save outstanding edits first.
    """
    return await run("open_film_scene", name=name, index=index)


@mcp.tool()
async def film_render_options(name: str | None = None, quality: Literal["draft", "preview", "final", "cycles"] = "final",
                              vertical: bool = False, calibrate: bool = False, target: str = 'local',
                              consent_upload: bool = False, confirm_cost: bool = False,
                              quote_id: str | None = None, max_budget_usd: float | None = None,
                              max_hours: float | None = None) -> dict:
    """Per-scene and total film estimates from render_options and learned machine speed.
    Offer resolution choices to the owner before preview/final; preserves editor edits.
    Remote targets include cost; calibrate=True measures one frame of the first saved
    scene, with upload consent and paid quote confirmation when applicable.
    """
    if target != 'local':
        return await anyio.to_thread.run_sync(lambda: remote.options('film', target,
            dict(name=name, quality=quality, vertical=vertical), calibrate, consent_upload,
            confirm_cost, quote_id, max_budget_usd, max_hours))
    return await run("film_render_options", name=name, quality=quality, vertical=vertical, calibrate=calibrate)


@mcp.tool()
async def render_film(name: str | None = None, path: str = "film.mp4",
                       quality: Literal["draft", "preview", "final", "cycles"] = "draft",
                       resolution: str | None = None, width: int | None = None,
                       height: int | None = None, vertical: bool = False,
                       subtitles: bool = True, wait: bool = False, resume: bool = True,
                       credits: bool = True, target: str = 'local', consent_upload: bool = False,
                       confirm_cost: bool = False, quote_id: str | None = None,
                       max_budget_usd: float | None = None, max_hours: float | None = None,
                       fallback: str | None = None) -> dict:
    """Render saved scenes serially then compose one H.264/AAC MP4 with Blender VSE.
    Choose resolution with film_render_options first for preview/final. Scene MP4s
    include voice/music/Foley; transitions fade audio, cards have a continuous silent
    audio bed. Global subtitles and .srt use exact scene/overlap/card offsets.
    Unchanged .blend bytes + render settings reuse cached scene clips (resume=True).
    Edits must be saved. Poll render_status(job_id); cancel_render stops the whole film.
    Preserves the editor scene; only one render queue can run at a time.
    target="name" renders clips remotely and composes locally. First-target upload
    requires consent_upload=True; paid allocation requires a returned quote_id and a
    subsequent confirm_cost=True call. Caps and stop_target apply to the whole job.
    Optional fallback="local" or an unpaid SSH target renders missing scene frames
    after the offline grace (separate upload consent). resume_job resumes a failed or
    cancelled remote job; resume=True above still controls the scene clip cache.
    """
    if target != 'local':
        params = dict(name=name, path=path, quality=quality, resolution=resolution, width=width,
                      height=height, vertical=vertical, subtitles=subtitles, resume=resume, credits=credits)
        result = await anyio.to_thread.run_sync(lambda: remote.start('film', target, params,
            consent_upload, confirm_cost, quote_id, max_budget_usd, max_hours,fallback=fallback))
        if wait and result.get('job_id'):
            return await anyio.to_thread.run_sync(lambda: remote.wait(result['job_id']))
        return result
    return await run("render_film", name=name, path=path, quality=quality, resolution=resolution,
        width=width, height=height, vertical=vertical, subtitles=subtitles, wait=wait, resume=resume, credits=credits)


@mcp.tool()
async def stage_dialog(characters: list[str], layout: Literal["angled", "face_to_face",
                       "side_by_side"] = "angled", distance: float = 1.3,
                       cheat_deg: float = 35.0, center: list[float] | None = None,
                       camera: Literal["directed", "emotional", "emosi", "mixed", "singles", "two_shot", "none"] | None = None,
                       desk: bool = True) -> dict:
    """Place 2-4 characters for a conversation (left to right in the given order): they face
    each other, "cheated" cheat_deg toward the camera side (-Y) so faces stay visible
    (angled); face_to_face = exact profile; side_by_side = both toward camera. distance in m.
    Optional camera="directed" covers existing timed speech, or establishes the cast.
    desk=True seats guests consistently in existing desk sets; False keeps standing staging."""
    return await run("stage_dialog", characters=characters, layout=layout, distance=distance,
                     cheat_deg=cheat_deg, center=center or [0.0, 0.0], camera=camera, desk=desk)


@mcp.tool()
async def dialog(lines: list[dict], characters: list[str | dict] | None = None, stage: bool = True,
                 layout: Literal["angled", "face_to_face", "side_by_side"] = "angled",
                 distance: float = 1.3, start_frame: int = 1, gap_s: float = 0.35,
                 camera: Literal["directed", "emotional", "emosi", "mixed", "singles", "two_shot", "none"] = "mixed",
                 shot: Literal["medium_full", "medium", "medium_close", "close_up"] = "medium",
                 gestures: Literal["calm", "presenter", "energetic"] | None = "presenter",
                 expression: Expression | None = "smile", language: str | None = None,
                 voice: bool = False, tts_engine: str = "piper",
                 voices: dict | None = None, seed: int = 0, body_language: bool = False, life: float = 1.0, collisions: bool = True) -> dict:
    """A conversation between 2-4 characters (realistic humans with faces work best), in one
    call. lines = [{"speaker": "Ana_rig", "audio": "audio/ana1.wav"},
                   {"speaker": "Budi_rig", "text": "Wah, ide yang bagus!"}, ...]
    characters also accepts VRM dict actors {id, vrm, gender?, age?}; lines then
    use their ids. Each actor is imported once, retaining its authored rig/look.
    — each line is lip-synced back to back (audio: local Whisper word timing, the sound goes
    on the timeline; text: mouth motion by default), gap_s apart (per line "pause_s" overrides).
    voice=True synthesizes text with tts_engine (offline Piper by default). voices maps
    speaker names to engine:name strings or {voice, pitch, rate, gender, age}.
    Missing TTS warns and retains mouth motion; existing audio wins. Explicit Edge or
    Chatterbox sends text to a third party and returns a privacy note. No online fallback.
    F5 reference voices must be your own or used with permission.
    Then: characters are staged facing each other (stage=False keeps your placement),
    everyone looks at whoever talks (the talker at the person they answer), listeners nod on
    stressed words, each speaker gestures on their own words (gestures=None: off), blinks,
    a light base expression, an idle clip on rigs without animation, and cameras:
    "directed" (emosi/emotional) uses emotional sizes/moves, OTS and readable listener
    reactions over speaker audio, returning a curve and per-shot reasons. "mixed" =
    two-shot for the first line then a clean single of each speaker, cut 4 frames before
    they talk (same side of the live head-to-head action line). Gaze samples live
    head positions; singles follow actual face direction after walks/sits/turns.
    Run body clips (animate/walk) BEFORE this;
    add_subtitles afterwards for captions. body_language=True optionally layers explicit
    line emotion or locally inferred body emotion; its default is False.
    Returns turns, shots, next_start_frame."""
    from engine.face_life import intensity as life_intensity
    life = life_intensity(life)
    import time
    started = time.perf_counter()
    if not lines or any(not ln.get("speaker") or not (ln.get("audio") or ln.get("text")) for ln in lines):
        raise ValueError("each line needs speaker and audio or text")
    speakers = list(dict.fromkeys(ln["speaker"] for ln in lines))
    from engine.vrm import dialog_declarations
    characters, actor_warnings, declared = dialog_declarations(characters)
    hints = [dict(declared.get(s.casefold(), {}), id=s) for s in speakers]
    casting = tts.cast(hints, tts_engine, language, seed, voices) if voice else {}
    report = {"generated_files": [], "cache_hits": 0, "warnings": [], "privacy": [], "tts_seconds": 0}
    prepared = [dict(ln) for ln in lines]
    if voice:
        prepared, report = await anyio.to_thread.run_sync(lambda: tts.prepare(prepared, casting, language))
    for ln in prepared:
        if ln.get("audio"):
            ln["audio"] = _workspace_path(ln["audio"])
            if not ln.pop("tts_generated", False) and speech.available():
                tr = await anyio.to_thread.run_sync(lambda: _transcribe_recorded(
                    ln["audio"], None if language == "auto" else language))
                ln["words"] = tr["words"]
                ln["text"] = tr["text"] or ln.get("text", "")
    d = await run("dialog", lines=prepared, characters=characters or speakers, stage=stage,
                  layout=layout, distance=distance, start_frame=start_frame, gap_s=gap_s,
                  camera=camera, shot=shot, gestures=gestures, expression=expression, language=language,
                  body_language=body_language, life=life, seed=seed, collisions=collisions)
    d.update(voices=casting, generated_files=report["generated_files"], cache_hits=report["cache_hits"])
    d["warnings"] = list(dict.fromkeys(actor_warnings + d.get("warnings", []) + report["warnings"]))
    d["timings"] = {"tts": report["tts_seconds"], "total": round(time.perf_counter() - started, 4)}
    if report["privacy"]:
        d["privacy"] = report["privacy"]
    return d


HandShape = Literal["relaxed", "open", "palm", "beat", "point", "fist", "thumbs_up", "peace",
                    "three", "four", "ok", "grip"]


@mcp.tool()
async def set_hand_pose(character: str, shape: HandShape = "relaxed",
                        side: Literal["both", "left", "right"] = "both", strength: float = 1.0,
                        frame: int | None = None, keyframe: bool = False) -> dict:
    """Pose the fingers: relaxed, open, palm, beat (half fist), point (index), fist,
    thumbs_up, peace (V), ok, grip (handshake). Works on rigs with finger bones (create_realistic_human with
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
    await anyio.to_thread.run_sync(tts.close)
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
