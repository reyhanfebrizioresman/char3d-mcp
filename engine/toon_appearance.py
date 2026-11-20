"""Small deterministic albedo/UV helpers, shared by Blender and offline tests."""
import numpy as np


def downsample_rgba(pixels, limit=128):
    """Area means, including non-power-of-two textures; no row-stride aliasing."""
    p=np.asarray(pixels,dtype=np.float32)
    h,w=p.shape[:2];nh,nw=min(h,limit),min(w,limit)
    ys=np.linspace(0,h,nh+1,dtype=int);xs=np.linspace(0,w,nw+1,dtype=int)
    q=np.add.reduceat(p,ys[:-1],axis=0)/np.diff(ys)[:,None,None]
    q=np.add.reduceat(q,xs[:-1],axis=1)/np.diff(xs)[None,:,None]
    return q.astype(np.float32)


def uv_mask(triangles, width, height):
    """Rasterize only the UV islands actually used by this material's faces."""
    mask=np.zeros((height,width),bool)
    for tri in np.asarray(triangles):
        t=tri*[width,height]
        lo=np.maximum(0,np.floor(t.min(0)).astype(int));hi=np.minimum([width-1,height-1],np.ceil(t.max(0)).astype(int))
        if np.any(hi<lo):continue
        a,b=t[1]-t[0],t[2]-t[0];det=a[0]*b[1]-a[1]*b[0]
        if abs(det)<1e-9:continue
        yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1];x=xx+.5-t[0,0];y=yy+.5-t[0,1]
        u=(x*b[1]-y*b[0])/det;v=(a[0]*y-a[1]*x)/det
        mask[lo[1]:hi[1]+1,lo[0]:hi[0]+1]|=(u>=-.001)&(v>=-.001)&(u+v<=1.001)
    return mask


def visible_albedo(pixels, triangles):
    """Median in occupied opaque UVs; unused white atlas margins are excluded."""
    p=np.asarray(pixels);mask=uv_mask(triangles,p.shape[1],p.shape[0])&(p[:,:,3]>.5)
    selected=p[:,:,:3][mask]
    if not len(selected):raise ValueError('Garment has no opaque albedo texels in its material UVs')
    return np.median(selected,axis=0),mask
