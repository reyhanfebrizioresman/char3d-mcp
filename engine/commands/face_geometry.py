"""Read-only face landmarks shared by cameras, overlays and scene review."""
import json
import bpy
from mathutils import Vector
from .anim import semantic_map
from .gaze import head_frame


def speech_ranges(rig):
    ranges = []
    for obj in rig.children_recursive:
        try:
            ranges.extend((float(w[1]), float(w[2])) for w in json.loads(obj.get('char3d_words', '[]')))
        except (ValueError, TypeError, IndexError):
            pass
    from .audio import _sound_strips
    ranges.extend((s.frame_final_start, s.frame_final_end) for s in _sound_strips(bpy.context.scene)
                  if not s.mute and s.get('char3d_speaker') == rig.name
                  and s.get('char3d_audio_kind', 'voice') == 'voice')
    return ranges


class FaceGeometry:
    def __init__(self, rig, height):
        self.rig, self.height = rig, height
        self.mapping = semantic_map(rig)
        self.bone = self.mapping.get('head')
        self.width = .045 * height
        self.sites = None
        if not self.bone:
            return
        from .motion import face_sites
        if all(k in self.mapping for k in ('hips', 'thigh.L', 'thigh.R')):
            self.sites = face_sites(rig, self.mapping, height)
        # Head-weighted body vertices scale the probe to large/stylised heads.
        # Do not include hair cards or clothing in the anatomical face width.
        xs = []
        orient = rig.matrix_world.to_quaternion().inverted()
        for obj in rig.children_recursive:
            keys = obj.data.shape_keys if obj.type == 'MESH' else None
            if not keys or 'jawOpen' not in keys.key_blocks:
                continue
            group = obj.vertex_groups.get(self.bone)
            if group:
                xs.extend((orient @ (obj.matrix_world @ v.co)).x for v in obj.data.vertices
                          if any(g.group == group.index and g.weight > .6 for g in v.groups))
        if xs:
            self.width = max(.025*height, (max(xs)-min(xs))*.37)

    def points(self):
        if not self.bone:
            return None
        rig = self.rig
        matrix = rig.matrix_world @ rig.pose.bones[self.bone].matrix
        center, orient = head_frame(rig)
        up, right = orient @ Vector((0,0,1)), orient @ Vector((1,0,0))
        if self.sites:
            mouth, chin, brow = [matrix @ self.sites[k] for k in ('mouth','chin','forehead')]
            eyes = matrix @ self.sites['eyes']
        else:
            eyes = center + orient @ Vector((0,-.06,.015))*self.height
            mouth = eyes-up*(.045*self.height)
            chin, brow = mouth-up*(.025*self.height), eyes+up*(.025*self.height)
        # The evaluated authored eyeballs provide a better eye plane than a bone.
        if any(o.type=='MESH' and (o.get('c3d_material_part','').lower() in ('high-poly','low-poly','eyes','eye')
               or o.name.rsplit('.',1)[-1].lower() in ('eyes','eyeballs')) for o in rig.children_recursive):
            from .ots import eye_point
            eyes = eye_point(rig)
        grid = [chin.lerp(brow, t)+right*(x*self.width)
                for t in (0,.25,.5,.75,1) for x in (-1,-.5,0,.5,1)]
        eye_points = [eyes+right*(x*self.width) for x in (-.45,.45)]
        lips = [mouth+right*(x*self.width)+up*(y*self.height)
                for x in (-.5,0,.5) for y in (-.012,.012)]
        crown = eyes+up*max(.055*self.height, self.width*1.6, (brow-eyes).length*1.6)
        return dict(face=grid+eye_points+lips, eyes=eye_points, mouth=lips,
                    eye=eyes, chin=chin, crown=crown, fit=grid+eye_points+lips+[crown])


def box(points, project):
    values = [project(p) for p in points]
    return [min(p.x for p in values),min(p.y for p in values),
            max(p.x for p in values),max(p.y for p in values)]
