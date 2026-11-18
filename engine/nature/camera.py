"""Build-time camera coverage snapshot. Never switches LOD on an animation frame."""
import bpy
from mathutils import Vector
from .core import lod_weight as weight


def coverage(root=None):
    cameras=[o for o in bpy.context.scene.objects if o.type=='CAMERA' and not o.name.startswith('__')]
    if not cameras: return None
    from ..commands.weather import _bounds
    from ..commands.script_scene import _bones_only
    with _bones_only(): low,high=_bounds()
    if root is not None:
        bpy.context.view_layer.update()
        inverse=root.matrix_world.inverted_safe()
        corners=[inverse@Vector((x,y,z)) for x in (low.x,high.x)
                 for y in (low.y,high.y) for z in (low.z,high.z)]
        return [min(v.x for v in corners),min(v.y for v in corners),
                max(v.x for v in corners),max(v.y for v in corners)]
    return [low.x,low.y,high.x,high.y]
