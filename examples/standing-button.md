# Walking to a button

This example uses a continuous take of somebody walking and slowing down to a stop. Char3D fits the take to a staged humanoid, keeps the soles grounded, and bakes a standing interaction with a movable button cap. All three tools run offline with a local BVH.

## Scene and capture

Place a rigged humanoid on a level floor facing the button. Use a separate mesh for the cap so it can travel vertically. For the Budi reference, set the scene to 30 fps and extract the converted take `16_34.bvh` to `imports/mocap/16_34.bvh`. [BVH conversion archive](https://github.com/Shriinivas/cmubvh/blob/main/Sequence-015-019/16/Data/16_34.zip)

The data used in this project was obtained from the [CMU Graphics Lab Motion Capture Database](https://mocap.cs.cmu.edu/). The database was created with funding from NSF EIA-0196217.

The source range and both feet's inclusive planted intervals refer to the scene-FPS interpretation of the BVH. The first BVH sample is frame 1. In the reference, source frames 3–86 cover the approach and settle. A different take needs its own intervals and source window.

## Bake the approach

Call `walk_approach` with the character's intended standing pelvis location in world XY metres. The starting position is determined by the take's travel and the character's heading. Name the fitted shoe mesh to correct residual outsole slip based on the actual geometry.

```json
{
  "armature": "BUDI_rig",
  "path": "mocap/16_34.bvh",
  "destination": [0.493, -0.46],
  "source_frames": [3, 86],
  "contacts": {"L": [[14, 34], [48, 86]], "R": [[3, 19], [31, 54], [64, 86]]},
  "start_frame": 1,
  "sole_mesh": "BUDI.shoes04"
}
```

The report contains the exact `footfalls` and the next free frame. The default arm swing is 5° in addition to the captured arm motion. `stance_width` can override the standing width in metres.

## Press and add footsteps

Call `press_button` after the approach. This example allows three additional frames before the gaze and reach start.

```json
{
  "character": "BUDI_rig",
  "button": "Press button",
  "start_frame": 88,
  "hand": "left",
  "target": [0.895, -0.015, 1.036],
  "travel": 0.010,
  "tip_mesh": "BUDI"
}
```

With `target` omitted, the command uses the cap's world-space top centre. `tip_mesh` fits the evaluated skin of the index fingertip. The command otherwise follows the index bone or the hand tip on a basic rig. Use the returned `frames.pressed` for a click or an indicator change. The report includes fingertip and foot IK errors in metres.

Pass the approach report's `footfalls` to `auto_sfx` together with `characters=["BUDI_rig"]`, `kinds=["footsteps"]`, and `surface="tile"`. The final sound mix then uses the scripted contact frames.

Use `render_frames` to review the last stride, the standing pose, and the button press before saving the project and rendering video.
