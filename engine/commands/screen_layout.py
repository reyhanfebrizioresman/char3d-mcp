"""One overlay layout for stills, movie PNGs and review; boxes use top-left origin."""
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from ..screen_layout import arrange
from . import subtitles, graphics
from .face_geometry import FaceGeometry, box
from .anim import semantic_map


def boundaries(sc, start=None, end=None):
    start = sc.frame_start if start is None else start
    end = sc.frame_end if end is None else end
    points = {start,end+1}
    points.update(m.frame for m in sc.timeline_markers if m.camera)
    cfg = subtitles.get_config(sc)
    if cfg:
        chunks = subtitles.chunk_words(subtitles.scene_words(sc,cfg),sc.render.fps/sc.render.fps_base,subtitles._resolved_style(cfg))
        points.update(f for c in chunks for f in (c['start'],c['end']))
    for g in graphics.get_config(sc):
        if g['type']=='title':
            a,b,_ = graphics.title_timing(sc,g)
            points.update((a,b+1))
    return sorted(p for p in points if start<=p<=end+1)


def layout_at(sc, frame, width, height):
    saved = sc.frame_current,sc.frame_subframe,sc.camera,sc.render.resolution_x,sc.render.resolution_y
    st = subtitles.state_at(sc,frame)
    cap = subtitles.caption_layout(width,height,st[0],st[2],st[3]) if st else None
    caption_bounds = list(cap['box']) if cap else None
    if cap and st[3].get('pop'):
        # Movie captions briefly reach 105% around this same drawing origin.
        # Reserve the animation envelope in stills/review as well.
        cx,cy = .5,1-cap['cy']/height
        caption_bounds = [cx+(caption_bounds[0]-cx)*1.05,cy+(caption_bounds[1]-cy)*1.05,
                          cx+(caption_bounds[2]-cx)*1.05,cy+(caption_bounds[3]-cy)*1.05]
    titles = [dict(g) for g in graphics.get_config(sc) if g['type']=='title'
              and graphics.title_timing(sc,g)[0]<=frame<=graphics.title_timing(sc,g)[1]]
    title_layouts = [graphics.title_layout(width,height,g) for g in titles]
    cuts = boundaries(sc)
    a = max((f for f in cuts if f<=frame),default=frame)
    b = min((f-1 for f in cuts if f>frame),default=frame)
    faces, mouths, geometry = {},{},{}
    try:
        sc.render.resolution_x,sc.render.resolution_y = width,height
        for f in sorted({a,(a+b)//2,b}):
            sc.frame_set(f)
            marks = sorted((m for m in sc.timeline_markers if m.camera and m.frame<=f),key=lambda m:m.frame)
            cam = marks[-1].camera if marks else sc.camera
            if not cam:
                continue
            names = cam.get('c3d_shot',{}).get('subject') or [o.name for o in sc.objects if o.type=='ARMATURE' and not o.hide_render]
            for name in names:
                rig = bpy.data.objects.get(name)
                if not rig or rig.type!='ARMATURE' or name==cam.get('c3d_foreground'):
                    continue
                if name not in geometry:
                    bone = semantic_map(rig).get('head')
                    height_m = max(.4,rig.data.bones[bone].tail_local.z*abs(rig.matrix_world.to_scale().z)) if bone else 1.7
                    geometry[name] = FaceGeometry(rig,height_m)
                points = geometry[name].points()
                if not points:
                    continue
                def project(p):
                    q = world_to_camera_view(sc,cam,p)
                    return Vector((q.x,1-q.y,q.z))
                if not any(project(p).z>0 for p in points['face']):
                    continue
                for table,key in ((faces,'face'),(mouths,'mouth')):
                    rect = box(points[key],project)
                    if rect[2]<0 or rect[0]>1 or rect[3]<0 or rect[1]>1:
                        continue
                    if name in table:
                        old = table[name]
                        rect = [min(old[0],rect[0]),min(old[1],rect[1]),max(old[2],rect[2]),max(old[3],rect[3])]
                    table[name] = rect
    finally:
        sc.render.resolution_x,sc.render.resolution_y = saved[3:]
        sc.frame_set(saved[0],subframe=saved[1]);sc.camera=saved[2]
    resolved = arrange(caption_bounds,[t['box'] for t in title_layouts],list(faces.values()),
                       st[2].get('avoid_overlap',True) if st else True,[g.get('avoid_overlap',True) for g in titles])
    style = dict(st[3]) if st else None
    if style:
        style['center_y'] = cap['cy']/height+caption_bounds[1]-resolved['caption'][1]
    placed = []
    for g,raw,rect in zip(titles,title_layouts,resolved['titles']):
        g['layout_shift_y'] = raw['box'][1]-rect[1]
        placed.append(dict(config=g,box=rect,requested_box=raw['box']))
    return dict(caption_box=resolved['caption'],caption_style=style,titles=placed,
                requested_caption_box=caption_bounds,faces=faces,mouths=mouths,clear=resolved['clear'])
