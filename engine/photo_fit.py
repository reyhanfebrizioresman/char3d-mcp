"""Local frontal-photo geometry fitting, image sampling and consent validation.

The fit is weak-perspective 2D, not a reconstruction of unseen facial depth.
MPFB supplies the 3D basis and modifier deltas. All array operations use numpy.
"""
import math
from pathlib import Path

import numpy as np


def validate(consent, strength):
    if consent is not True:
        raise ValueError('face_from_photo requires consent=True: use only your own face or a person who gave permission. Photos are processed locally only.')
    if isinstance(strength, bool) or not isinstance(strength,(float,int)) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('strength must be finite in 0..1')


def photo_path(workspace, image):
    workspace = Path(workspace).resolve()
    root = (workspace/'imports').resolve()
    if not root.is_relative_to(workspace):
        raise ValueError('Workspace imports/ must resolve inside the workspace; local photo data must stay there.')
    path = Path(image).expanduser()
    path = path.resolve() if path.is_absolute() else (root/path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Photo must be a local JPEG/PNG inside workspace imports/ (including symlink targets). Never uploaded.')
    if path.suffix.lower() not in ('.jpg','.jpeg','.png'):
        raise ValueError('Photo must be JPEG or PNG')
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def project(points, camera):
    """camera = scale, roll radians, image x/y translation; front is -Y."""
    scale, roll, tx, ty = camera[:4]
    points=np.asarray(points)
    yaw=camera[4] if len(camera)>4 else 0.
    pitch=camera[5] if len(camera)>5 else 0.
    depth=-points[:,0]*np.sin(yaw)+points[:,1]*np.cos(yaw)
    p=np.c_[points[:,0]*np.cos(yaw)+points[:,1]*np.sin(yaw),-points[:,2]*np.cos(pitch)-depth*np.sin(pitch)]
    rotation = np.array([[np.cos(roll),-np.sin(roll)],[np.sin(roll),np.cos(roll)]])
    return scale*p @ rotation.T + [tx,ty]


def camera_fit(points, observed):
    a = np.asarray(points)[:,[0,2]]*np.array([1.,-1.])
    b = np.asarray(observed)
    ac, bc = a.mean(axis=0), b.mean(axis=0)
    u, s, vt = np.linalg.svd((a-ac).T @ (b-bc))
    flip = np.linalg.det(u @ vt)
    rotation = u @ np.diag([1.,flip]) @ vt
    scale = (s*np.array([1.,flip])).sum()/max(1e-12,np.square(a-ac).sum())
    translation = bc-scale*ac @ rotation
    return np.array([scale,np.arctan2(rotation[0,1],rotation[0,0]),*translation])


def fit_modifiers(base, deltas, observed, confidence=None, camera=None, iterations=80, regularization=1e-7, allow_yaw=False):
    """Bounded Gauss-Newton on modifier weights and similarity camera.

    Coefficients -1..1 use paired MPFB decr/incr targets; the engine limits trait
    transfer separately. Confidence-weighted residuals suppress uncertain points.
    A supplied camera is fixed, useful for calibrated images and synthetic tests.
    """
    base, deltas, observed = [np.asarray(x,dtype=float) for x in (base,deltas,observed)]
    if base.ndim!=2 or base.shape[1]!=3 or deltas.shape[1:]!=base.shape or observed.shape!=(len(base),2):
        raise ValueError('Expected base Nx3, deltas MxNx3, observed Nx2')
    if not all(np.isfinite(x).all() for x in (base,deltas,observed)):
        raise ValueError('Landmarks must be finite')
    weight = np.ones(len(base)) if confidence is None else np.asarray(confidence,dtype=float)
    if weight.shape!=(len(base),) or np.any(weight<0) or not np.isfinite(weight).all() or np.count_nonzero(weight) < 6:
        raise ValueError('Need at least six reliable landmark weights')
    m = len(deltas)
    coeff = np.zeros(m)
    fixed = camera is not None
    camera = camera_fit(base,observed) if camera is None else np.asarray(camera,dtype=float)
    if allow_yaw and not fixed:camera=np.r_[camera,0.,0.]
    params = coeff if fixed else np.r_[coeff,np.log(camera[0]),camera[1:]]

    def unpack(p):
        cam = camera if fixed else np.r_[np.exp(p[m]),p[m+1:]]
        shape = base+np.einsum('m,mnc->nc',p[:m],deltas)
        return project(shape,cam),cam

    def residual(p):
        prediction,_ = unpack(p)
        return np.r_[((prediction-observed)*np.sqrt(weight[:,None])).ravel(),
                     p[:m]*np.sqrt(regularization)]

    initial = float(np.sqrt(np.mean(np.sum((project(base,camera)-observed)**2,axis=1))))
    for _ in range(iterations):
        error = residual(params)
        jac = []
        for i in range(len(params)):
            trial = params.copy();trial[i] += 1e-5
            jac.append((residual(trial)-error)/1e-5)
        step = np.linalg.lstsq(np.array(jac).T,-error,rcond=1e-9)[0]
        if np.linalg.norm(step) < 1e-8:
            break
        accepted = False
        for rate in (1.,.5,.25,.125,.0625):
            trial = params+step*rate
            trial[:m] = np.clip(trial[:m],-1,1)
            if allow_yaw and not fixed:trial[m+4:m+6]=np.clip(trial[m+4:m+6],-.30,.30)
            if np.linalg.norm(residual(trial)) <= np.linalg.norm(error):
                params = trial;accepted = True;break
        if not accepted:
            break
    prediction,camera = unpack(params)
    return dict(coefficients=params[:m],camera=camera,rmse_px=float(np.sqrt(np.mean(np.sum((prediction-observed)**2,axis=1)))),
                initial_rmse_px=initial,predicted=prediction)


def sample_rgb(rgb, points):
    h,w = rgb.shape[:2]
    p = np.asarray(points)
    x = np.clip(p[:,0],0,w-1);y = np.clip(p[:,1],0,h-1)
    x0,y0 = x.astype(int),y.astype(int)
    x1,y1 = np.minimum(x0+1,w-1),np.minimum(y0+1,h-1)
    dx,dy = (x-x0)[:,None],(y-y0)[:,None]
    return (rgb[y0,x0]*(1-dx)+rgb[y0,x1]*dx)*(1-dy)+(rgb[y1,x0]*(1-dx)+rgb[y1,x1]*dx)*dy


def colors(rgb, landmarks):
    """Patch medians: illumination/hair occlusion can bias all three estimates."""
    p = np.asarray(landmarks)
    h,w = rgb.shape[:2]
    eye = (p[36]+p[39]+p[42]+p[45])/4
    span = np.linalg.norm((p[36]+p[39])/2-(p[42]+p[45])/2)
    def patch(center,radius):
        y,x = np.mgrid[-2:3,-2:3]
        return np.median(sample_rgb(rgb,np.c_[x.ravel(),y.ravel()]*radius/2+center),axis=0).tolist()
    skin = np.median([patch((p[3]+p[31])/2,span*.07),patch((p[13]+p[35])/2,span*.07)],axis=0).tolist()
    center = (p[36]+p[39])/2
    y,x=np.mgrid[-3:4,-5:6]
    samples=sample_rgb(rgb,center+np.c_[x.ravel()*span*.018,y.ravel()*span*.010])
    saturation=np.ptp(samples,axis=1)/np.maximum(samples.max(1),1e-6)
    pigment=samples[(samples.mean(1)>.05)&(samples.mean(1)<.8)&(saturation>.18)]
    iris=np.median(pigment if len(pigment) else samples,axis=0)
    # Suppress the achromatic corneal highlight before transferring pigment.
    # This is an artistic estimate, not illumination-calibrated reflectance.
    if np.ptp(iris)>.06:
        linear=np.where(iris<=.04045,iris/12.92,((iris+.055)/1.055)**2.4)
        linear=np.maximum(0.,linear-linear.min()*.80)
        iris=np.where(linear<=.0031308,linear*12.92,1.055*linear**(1/2.4)-.055)
    iris=iris.tolist()
    yy,xx=np.mgrid[.75:1.7:12j,-.30:.31:9j]
    samples=sample_rgb(rgb,eye+np.c_[xx.ravel(),-yy.ravel()]*span)
    saturation=np.ptp(samples,axis=1)/np.maximum(samples.max(1),1e-6)
    distance=np.linalg.norm(samples-np.asarray(skin),axis=1)
    pigment=samples[(distance>.12)&((saturation>.12)|(samples.mean(1)<.08))]
    hair=np.median(pigment,axis=0).tolist() if len(pigment) else patch(eye+[0,-span*.95],span*.10)
    return dict(skin=skin,iris=iris,hair=hair)


def likeness_geometry(reference,candidate):
    """Similarity-aligned mean landmark error in interocular units; not biometrics."""
    a,b=np.asarray(reference,float),np.asarray(candidate,float)
    if a.shape!=(66,2) or b.shape!=a.shape or not np.isfinite([a,b]).all():raise ValueError('Need two finite 66x2 landmark arrays')
    def normalized(p):
        eyes=np.array([p[36:42].mean(0),p[42:48].mean(0)])
        return (p-eyes.mean(0))/max(1e-6,np.linalg.norm(eyes[1]-eyes[0]))
    a,b=normalized(a),normalized(b)
    u,_s,vt=np.linalg.svd(b.T@a)
    rotation=u@np.diag([1.,np.linalg.det(u@vt)])@vt
    error=float(np.linalg.norm(b@rotation-a,axis=1).mean())
    return dict(score=round(100*math.exp(-error/.20),3),normalized_landmark_error=round(error,6),
                method='66-point similarity-aligned mean error / interocular distance; 100*exp(-error/0.20)',
                identity_probability=False)
