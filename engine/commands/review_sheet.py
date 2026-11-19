"""Labelled review PNGs with Blender's bundled image/font APIs, no extra packages."""
import math
import os
import bpy
import blf
import imbuf
import numpy as np
from .subtitles import _font_path, _font_id


def pixels(path):
    image=bpy.data.images.load(path,check_existing=False)
    try:
        w,h=image.size; data=np.empty(w*h*4,np.float32);image.pixels.foreach_get(data)
        return data.reshape(h,w,4).copy()
    finally:bpy.data.images.remove(image)


def resize(data,w,h):
    return data[np.linspace(0,data.shape[0]-1,h).astype(int)[:,None],np.linspace(0,data.shape[1]-1,w).astype(int)[None,:]]


def save(path,data):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    h,w=data.shape[:2];image=bpy.data.images.new('__ReviewSheet',width=w,height=h,alpha=True)
    try:
        image.pixels.foreach_set(np.ascontiguousarray(data).ravel())
        image.filepath_raw=path;image.file_format='PNG';image.save()
    finally:bpy.data.images.remove(image)


def label(path,width,text):
    ib=imbuf.new((width,25));font=_font_id(_font_path({})[0]);blf.size(font,12)
    with blf.bind_imbuf(font,ib,display_name='sRGB'):
        blf.color(font,1,1,1,1);blf.position(font,5,7,0);blf.draw_buffer(font,text)
    imbuf.write(ib,filepath=path)
    return pixels(path)


def sheet(spec,stack=False):
    items=spec['items'];width=spec.get('size',384);columns=1 if stack else spec.get('columns',4)
    panels=[];observations=[]
    for item in items:
        data=pixels(item['path']);h=round(width*data.shape[0]/data.shape[1]) if stack else round(width*spec.get('aspect',9/16))
        rgb=data[::-1,:,:3];y=rgb@np.array([.2126,.7152,.0722]);box=item.get('face_box');contrast=None
        if box:
            ih,iw=y.shape;x0,y0,x1,y1=[round(v*(iw if i%2==0 else ih)) for i,v in enumerate(box)]
            x0,x1=max(0,x0),min(iw,x1);y0,y1=max(0,y0),min(ih,y1)
            if x1>x0 and y1>y0:
                mask=np.zeros_like(y,dtype=bool);mask[y0:y1,x0:x1]=True
                surround=np.zeros_like(mask);surround[max(0,y0-12):min(ih,y1+12),max(0,x0-12):min(iw,x1+12)]=True
                surround &= ~mask
                if surround.any():contrast=round(abs(float(y[mask].mean()-y[surround].mean())),5)
        observations.append(dict(frame=item['frame'],mean=float(y.mean()),dark_fraction=float(np.mean(y<.025)),
                                 blown_fraction=float(np.mean(y>.98)),color=rgb.mean(axis=(0,1)).tolist(),contrast=contrast))
        panels.append((resize(data,width,h),item['label']))
    height=sum(p.shape[0]+25 for p,_ in panels) if stack else max(1,math.ceil(len(panels)/columns))*(panels[0][0].shape[0]+25)
    canvas=np.zeros((height,width*columns,4),np.float32);canvas[:,:,:3]=(.012,.016,.022);canvas[:,:,3]=1
    offset=0;temporary=spec['path']+'.label.png'
    try:
        for i,(panel,text) in enumerate(panels):
            ph=panel.shape[0];x=0 if stack else i%columns*width
            top=offset if stack else i//columns*(ph+25)
            lo=height-top-ph-25
            canvas[lo+25:lo+25+ph,x:x+width]=panel
            over=label(temporary,width,text);a=over[:,:,3:4]
            canvas[lo:lo+25,x:x+width,:3]=canvas[lo:lo+25,x:x+width,:3]*(1-a)+over[:,:,:3]*a
            if stack:offset+=ph+25
        save(spec['path'],canvas)
    finally:
        if os.path.isfile(temporary):os.remove(temporary)
    return dict(path=spec['path'],observations=observations)
