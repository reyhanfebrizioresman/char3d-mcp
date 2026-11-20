"""Original MPFB proportion presets and continuous rest-space deformation.

Pure numpy; the same map is used on skin, all morph targets, fitted proxies and
bone endpoints. No pose-scale constraints or dependency-graph handlers are needed.
"""
import numpy as np

PRESETS = {
    'realistic': dict(heads=7.5, eye_width=1., eye_height=1., chin=1., cheek=1., cranium=1.,
                      nose=1., mouth=1., stature=1., body_width=1., depth=1., arm=1., hand=1., foot=1., leg=.60),
    'anime': dict(heads=6.75, eye_width=1.65, eye_height=2.65, chin=.62, cheek=.94, cranium=1.10,
                  nose=.22, mouth=.68, stature=1., body_width=.94, depth=.92, arm=.98, hand=.90, foot=.90, leg=.63),
    'cartoon': dict(heads=4.75, eye_width=1.43, eye_height=3.05, chin=1.18, cheek=1.15, cranium=1.08,
                    nose=.12, mouth=.75, stature=1., body_width=.91, depth=1.05, arm=.78, hand=.80, foot=.78, leg=.52),
    'chibi': dict(heads=2.8, eye_width=1.60, eye_height=3.25, chin=1.15, cheek=1.12, cranium=1.16,
                  nose=.14, mouth=.55, stature=.82, body_width=.83, depth=1.18, arm=.90, hand=.68, foot=.65, leg=.52),
}
ALIASES = {'kartun': 'cartoon', 'realistis': 'realistic'}
# Full HM08 palpebral boundary, outer canthus -> inner canthus. The upper
# curve has one more segment; a repeated lower vertex keeps the closed curves
# identical without changing the MPFB topology or leaving corner pinholes.
UPPER_RIM=(24,21,18,15,12,9,6,0,1,54,57,60,63,66)
LOWER_RIM=(24,27,30,33,36,41,44,47,50,53,72,69,66)
LID_PAIRS={'R':tuple(zip(UPPER_RIM,(LOWER_RIM[i] for i in (0,1,2,3,4,5,6,6,7,8,9,10,11,12))))}
LID_PAIRS['L']=tuple((a+6784,b+6784) for a,b in LID_PAIRS['R'])


def style_name(value):
    if not isinstance(value, str):
        raise ValueError('character style must be realistic, anime, cartoon or chibi')
    value = ALIASES.get(value, value)
    if not isinstance(value, str) or value not in PRESETS:
        raise ValueError('character style must be realistic, anime, cartoon or chibi')
    return value


def smooth(value):
    t = np.clip(value, 0, 1)
    return t*t*(3-2*t)


def lid_taper(t):
    """Finite fractional taper even when sin(pi) rounds just below zero."""
    return np.maximum(0.,np.sin(np.pi*np.clip(t,0.,1.)))**.4


def monotone(value, xs, ys, endpoint_slopes=None):
    """C1 monotone cubic interpolation, with linear end extrapolation (no scipy)."""
    x,y=np.asarray(xs,float),np.asarray(ys,float)
    h=np.diff(x);d=np.diff(y)/h
    m=np.r_[d[0],(d[:-1]+d[1:])*.5,d[-1]]
    if endpoint_slopes is not None:m[0],m[-1]=endpoint_slopes
    for i,slope in enumerate(d):
        if abs(slope)<1e-12:m[i:i+2]=0;continue
        norm=np.hypot(m[i]/slope,m[i+1]/slope)
        if norm>3:
            if endpoint_slopes is not None and i==0:
                m[1]=slope*np.sqrt(max(0.,9-(m[0]/slope)**2))
            elif endpoint_slopes is not None and i==len(d)-1:
                m[-2]=slope*np.sqrt(max(0.,9-(m[-1]/slope)**2))
            else:m[i:i+2]*=3/norm
    v=np.asarray(value,float);i=np.clip(np.searchsorted(x,v)-1,0,len(h)-1)
    t=np.clip((v-x[i])/h[i],0,1)
    out=((2*t**3-3*t**2+1)*y[i]+(t**3-2*t**2+t)*h[i]*m[i]
         +(-2*t**3+3*t**2)*y[i+1]+(t**3-t**2)*h[i]*m[i+1])
    return np.where(v<x[0],y[0]+(v-x[0])*m[0],np.where(v>x[-1],y[-1]+(v-x[-1])*m[-1],out))


class RestMap:
    def __init__(self, style, bottom, top, chin, eye_centers, joints=None):
        self.style = style_name(style)
        self.preset = PRESETS[self.style]
        self.bottom, self.top, self.chin = bottom, top, chin
        self.eyes = np.asarray(eye_centers, dtype=float)
        self.head = top-chin
        self.output_top=bottom+(top-bottom)*self.preset['stature']
        self.scale = (self.output_top-bottom)/self.preset['heads']/self.head
        self.new_chin = self.output_top-self.head*self.scale
        self.body_scale = (self.new_chin-bottom)/(chin-bottom)
        self.joints=joints or {}

    def __call__(self, points, features=True):
        p=np.asarray(points,dtype=float).reshape(-1,3).copy()
        if self.style=='realistic':return p
        original=p.copy();h=self.head;c=self.chin;cfg=self.preset
        ez,ey=self.eyes.mean(axis=0)[[2,1]]
        arm_region=smooth((original[:,2]-self.bottom-.50*(c-self.bottom))/(.10*(c-self.bottom)))
        # Shared rest-space arm contraction follows real shoulder/wrist anchors,
        # including fingers, clothes and every metarig/deform bone endpoint.
        for sign,side in ((-1,'R'),(1,'L')):
            shoulder=np.asarray(self.joints.get('shoulder.'+side,[sign*.14,0,c-.45*h]))
            wrist=np.asarray(self.joints.get('wrist.'+side,[sign*.40,-.14,c-1.7*h]))
            hand=smooth((sign*original[:,0]-sign*wrist[0]+.015)/.04)
            hand*=arm_region*(1-smooth((original[:,2]-shoulder[2])/(.2*h)))
            p+=(original-wrist)*(cfg['hand']-1)*hand[:,None]
            weight=smooth((sign*original[:,0]-abs(shoulder[0])*.8)/(.45*abs(shoulder[0])))
            weight*=arm_region*(1-smooth((original[:,2]-shoulder[2])/(.3*h)))
            p+=(p-shoulder)*(cfg['arm']-1)*weight[:,None]
        foot=1-smooth((original[:,2]-self.bottom-.06)/.065)
        p[:,1]*=1+(cfg['foot']-1)*foot
        # Rebalance legs vs torso with C1 joint-height interpolation, not a head
        # enlarged on top of unchanged adult limbs. Head endpoints remain exact.
        body=self.chin-self.bottom;newbody=self.new_chin-self.bottom
        leg=cfg['leg']
        zx=np.r_[self.bottom+body*np.array([0,.05,.32,.60,.90,1.]),ez,self.top]
        zy=np.r_[self.bottom+newbody*np.array([0,.035,leg*.51,leg,.91,1.]),
                 self.new_chin+.48*h*self.scale,self.output_top]
        p[:,2]=monotone(p[:,2],zx,zy)
        u=(original[:,2]-c)/h
        bodyxy=p[:,:2]*[cfg['body_width'],cfg['body_width']*cfg['depth']]
        # Round the short torso instead of retaining the adult waist pinch.
        waist=np.exp(-.5*((original[:,2]-(self.bottom+.74*body))/(.11*body))**2
                     -(original[:,0]/(.75*h))**4)
        roundness={'anime':-.03,'cartoon':.18,'chibi':.42}[self.style]
        bodyxy[:,0]*=1+roundness*waist
        bodyxy[:,1]*=1+roundness*.4*waist
        headxy=original[:,:2].copy()
        if features:
            # Exact, broad, monotone remaps at the actual eyelid coordinates.
            # Horizontal and vertical opening scales are independently authored.
            front=1-smooth((original[:,1]-ey-.025)/(.20*h))
            eye_front=1-smooth((original[:,1]-ey-.015*h)/(.10*h))
            cx=float(np.mean(np.abs(self.eyes[:,0])))
            width=.073*h
            # Enlarging lids by squeezing the inner canthi onto the sagittal
            # plane makes a pinched vertical nasal groove. Move sockets apart
            # with their inserts instead, retaining a broad smooth bridge.
            ex=cx+width*(cfg['eye_width']-1)*.35
            ax=np.abs(original[:,0])
            xmap=monotone(ax,[0,cx-width,cx,cx+width,.43*h],
                         [0,ex-width*cfg['eye_width'],ex,ex+width*cfg['eye_width'],.46*h])
            near=smooth((u-.24)/.16)*(1-smooth((u-.56)/.12))*eye_front
            headxy[:,0]+=(np.sign(original[:,0])*xmap-original[:,0])*near
            dz=(original[:,2]-ez)/h
            zmap=monotone(dz,[-.30,-.035,0,.035,.30],[-.30,-.035*cfg['eye_height'],0,.035*cfg['eye_height'],.30],endpoint_slopes=(1.,1.))
            left=np.exp(-((original[:,0]+cx)/(.125*h))**4)
            right=np.exp(-((original[:,0]-cx)/(.125*h))**4)
            local=(1-(1-left)*(1-right))*eye_front
            moved_z=original[:,2]+(zmap-dz)*h*local
            p[:,2]=np.where(u>=0,monotone(moved_z,zx,zy),p[:,2])
            # Small smooth lower face, larger cranium. Narrow anime chin vs round
            # cartoon cheeks remain distinct at thumbnail size.
            jaw=monotone(u,[0,.32,.65,1],[cfg['chin'],cfg['cheek'],cfg['cranium'],cfg['cranium']])
            headxy[:,0]*=jaw
            nose=np.exp(-.5*(original[:,0]/(.075*h))**4-.5*((u-.34)/.095)**4)*front
            nose*=1-smooth((u-.43)/.10)
            headxy[:,0]*=1+(cfg['nose']**.5-1)*nose
            # Compress protrusion and nostril depth toward a smooth facial plane.
            plane=ey-.035*h+.10*h*(original[:,0]/(.35*h))**2
            headxy[:,1]+=(plane-original[:,1])*(1-cfg['nose'])*nose
            mouth=np.exp(-.5*(original[:,0]/(.13*h))**4-.5*((u-.245)/.065)**4)*front
            headxy[:,0]*=1+(cfg['mouth']-1)*mouth
            headxy[:,1]+=(plane-original[:,1])*.40*mouth
            cheek=np.exp(-.5*((np.abs(original[:,0])-.22*h)/(.12*h))**2-.5*((u-.32)/.15)**2)*front
            headxy[:,1]+=(ey+.015*h-original[:,1])*cheek*(.10 if self.style=='anime' else .18)
        pivot=ey+.32*h
        headxy[:,0]*=self.scale
        headxy[:,1]=pivot+(headxy[:,1]-pivot)*self.scale
        # Broad neck blend with a radial gate below the jaw: shoulders retain
        # torso width while the neck has continuous position AND tangent.
        blend=smooth((u+.35)/.35)
        radial=np.exp(-(original[:,0]/(.25*h))**4)
        jaw_blend=smooth((u+.06)/.08)
        blend*=jaw_blend+(1-jaw_blend)*radial
        p[:,:2]=bodyxy*(1-blend[:,None])+headxy*blend[:,None]
        return p


def iris_pixels(size=256, color=(.16, .38, .64)):
    """Original iris atlas: clean radial color, dark rim/pupil and two highlights."""
    y, x = np.mgrid[0:size, 0:size]/(size-1)
    r = np.hypot((x-.5)*2, (y-.5)*2)
    a = np.arctan2(y-.5, x-.5)
    shade = (.55+.45*(1-y))*(.96+.04*np.cos(a*32))
    rgb = np.asarray(color)[None, None, :]*shade[:, :, None]
    rgb *= (1-.8*smooth((r-.80)/.18))[:, :, None]
    rgb[r < .29] = (.008, .013, .025)
    rgb[r > 1] = (.96, .97, 1)
    highlight = ((x-.35)/.10)**2+((y-.70)/.13)**2 < 1
    highlight |= ((x-.65)/.045)**2+((y-.32)/.055)**2 < 1
    rgb[highlight] = (1, 1, 1)
    return np.concatenate((rgb, np.ones((size, size, 1))), axis=2).astype(np.float32)
