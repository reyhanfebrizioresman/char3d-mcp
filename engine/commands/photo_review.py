"""Scoped local rerender/re-detection; reuse the editor's single render context."""
import math
from pathlib import Path
import tempfile
import bpy
from mathutils import Vector,Quaternion
from .. import context
from ..photo_fit import likeness_geometry


def likeness_check(root,body,rgb,reference,fit,directory):
    from .photo import infer,decode
    from .render import render_preview
    scene=bpy.context.scene
    objects=[root,*root.children_recursive] if root.type=='ARMATURE' else [body,*body.children_recursive]
    objects=[o for o in dict.fromkeys(objects) if o.type not in ('LIGHT','CAMERA')]
    created=[];actions=[];values=[];poses=[];hidden=[]
    try:
        keep=set(objects)
        for obj in scene.objects:
            if obj.type in ('MESH','CURVE','FONT','VOLUME') and obj not in keep and not obj.hide_render:
                hidden.append(obj);obj.hide_render=True
        for obj in objects:
            for block in (obj,obj.data.shape_keys if obj.type=='MESH' else None):
                if block is None:continue
                anim=block.animation_data
                if anim:
                    actions.append((anim,anim.action,anim.action_slot,[(n,n.mute) for n in anim.nla_tracks]))
                    anim.action=None
                    for track in anim.nla_tracks:track.mute=True
            if obj.type=='MESH' and obj.data.shape_keys:
                for key in obj.data.shape_keys.key_blocks:
                    if not key.name.startswith('$'):values.append((key,key.value));key.value=0
            if obj.type=='ARMATURE':
                for bone in obj.pose.bones:poses.append((bone,bone.matrix_basis.copy()));bone.matrix_basis.identity()
        scale,roll,tx,ty=fit['camera'][:4];yaw=fit['camera'][4] if len(fit['camera'])>4 else 0.
        pitch=fit['camera'][5] if len(fit['camera'])>5 else 0.
        height,width=rgb.shape[:2];right=Vector((math.cos(yaw),math.sin(yaw),0))
        up=Vector((-math.sin(yaw)*math.sin(pitch),math.cos(yaw)*math.sin(pitch),math.cos(pitch)))
        dx,dy=width/2-tx,height/2-ty
        cx=(math.cos(roll)*dx+math.sin(roll)*dy)/scale
        cz=(math.sin(roll)*dx-math.cos(roll)*dy)/scale
        target=body.matrix_world@(right*cx+up*cz)
        direction=body.matrix_world.to_3x3()@Vector((math.sin(yaw)*math.cos(pitch),-math.cos(yaw)*math.cos(pitch),math.sin(pitch)))
        data=bpy.data.cameras.new('__c3d_local_face_review');data.type='ORTHO';data.ortho_scale=max(width,height)/scale
        cam=bpy.data.objects.new(data.name,data);scene.collection.objects.link(cam);created.append(cam)
        cam.location=target+direction*3;cam.rotation_mode='QUATERNION'
        cam.rotation_quaternion=(-direction).to_track_quat('-Z','Y')@Quaternion((0,0,1),roll)
        # Eye-only catchlights have zero diffuse power and cannot light a face.
        if not any(o.type=='LIGHT' and o.data.diffuse_factor>0 and not o.hide_render for o in scene.objects):
            for offset,power in (((-.6,-.8,.7),100),((.6,-.6,.3),60),((0,.5,.7),80)):
                light=bpy.data.lights.new('__c3d_face_review_light','AREA');light.energy=power;light.shape='DISK';light.size=.6
                obj=bpy.data.objects.new(light.name,light);scene.collection.objects.link(obj);created.append(obj)
                obj.location=target+Vector(offset);obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()
        with tempfile.TemporaryDirectory(prefix='.face-review-',dir=Path(context.WORKSPACE)/'imports') as temporary:
            path=Path(temporary)/'fitted.png'
            render_preview(camera=cam.name,engine='eevee',width=224,height=224,filename=str(path))
            result=infer(decode(path),directory)
        return dict(likeness_geometry(reference,result['landmarks']),redetected=True,
                    mean_confidence=sum(result['confidence'])/len(result['confidence']),
                    view='neutral fitted orthographic photo projection; scoped scene state')
    except (ValueError,RuntimeError) as exc:
        return dict(score=None,redetected=False,reason=str(exc),identity_probability=False)
    finally:
        for key,value in values:key.value=value
        for bone,matrix in poses:bone.matrix_basis=matrix
        for anim,action,slot,tracks in actions:
            anim.action=action
            if slot is not None:anim.action_slot=slot
            for track,mute in tracks:track.mute=mute
        for obj in hidden:obj.hide_render=False
        for obj in created:
            data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if data.users==0:(bpy.data.cameras if isinstance(data,bpy.types.Camera) else bpy.data.lights).remove(data)
        bpy.context.view_layer.update()
