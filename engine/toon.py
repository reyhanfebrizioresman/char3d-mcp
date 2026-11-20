"""Original MPFB proportion presets and continuous rest-space deformation.

Pure numpy; the same map is used on skin, all morph targets, fitted proxies and
bone endpoints. No pose-scale constraints or dependency-graph handlers are needed.
"""
import numpy as np

PRESETS = {
    'realistic': dict(heads=7.5, eyes=1., nose=1., mouth=1., jaw=1.),
    'anime': dict(heads=6.75, eyes=1.5, nose=.65, mouth=.84, jaw=.92),
    'cartoon': dict(heads=5., eyes=1.4, nose=.72, mouth=.88, jaw=.96),
    'chibi': dict(heads=3., eyes=1.5, nose=.5, mouth=.72, jaw=.94),
}
ALIASES = {'kartun': 'cartoon', 'realistis': 'realistic'}
# HM08 central eyelid margin vertices, paired across the opening. The opposite
# eye is given by HM08's authored mirror table (first eye block +6784).
LID_PAIRS = {'R': ((0,41),(1,44),(54,47),(6,36),(9,33),(57,50))}
LID_PAIRS['L'] = tuple((a+6784,b+6784) for a,b in LID_PAIRS['R'])


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


class RestMap:
    def __init__(self, style, bottom, top, chin, eye_centers):
        self.style = style_name(style)
        self.preset = PRESETS[self.style]
        self.bottom, self.top, self.chin = bottom, top, chin
        self.eyes = np.asarray(eye_centers, dtype=float)
        self.head = top-chin
        self.scale = (top-bottom)/self.preset['heads']/self.head
        self.new_chin = top-self.head*self.scale
        self.body_scale = (self.new_chin-bottom)/(chin-bottom)

    def __call__(self, points, features=True):
        p = np.asarray(points, dtype=float).reshape(-1, 3).copy()
        if self.style == 'realistic':
            return p
        # Features are mapped before the body/head proportions. A shared smooth
        # field also carries lashes, eyeballs, teeth and their animation deltas.
        if features:
            original = p.copy()
            for center in self.eyes:
                d = original-center
                radius = np.sqrt((d[:, 0]/(.027))**2+(d[:, 2]/.021)**2)
                # A Gaussian expansion remains monotone at the socket margin;
                # a narrow flat-core falloff can fold the cheek into a ridge.
                weight = np.exp(-.5*radius*radius)
                weight *= 1-smooth((np.abs(d[:, 1])-.022)/.035)
                p[:,[0,2]] += d[:,[0,2]]*(self.preset['eyes']-1)*weight[:, None]
            ez = self.eyes[:, 2].mean()
            ey = self.eyes[:, 1].mean()
            nose = np.exp(-.5*(original[:, 0]/.018)**2-.5*((original[:, 2]-ez+.036)/.03)**2)
            nose *= smooth((ey+.015-original[:, 1])/.035)
            p[:, 1] += (self.preset['nose']-1)*(original[:, 1]-ey)*nose
            mouth = np.exp(-.5*(original[:, 0]/.036)**4-.5*((original[:, 2]-ez+.075)/.02)**4)
            mouth *= 1-smooth((original[:, 1]-ey-.02)/.04)
            p[:, 0] *= 1+(self.preset['mouth']-1)*mouth
            jaw = np.exp(-.5*((original[:, 2]-self.chin-.02)/.04)**2)
            p[:, 0] *= 1+(self.preset['jaw']-1)*jaw
        # Keep shoulder/collar widths with the torso. A broad neck transition
        # expands the top of fitted shirts into wings on a three-head body.
        blend = smooth((p[:, 2]-(self.chin-.035))/.035)
        p[:, :2] *= (self.body_scale*(1-blend)+self.scale*blend)[:, None]
        p[:, 2] = np.where(p[:, 2] < self.chin,
                           self.bottom+(p[:, 2]-self.bottom)*self.body_scale,
                           self.new_chin+(p[:, 2]-self.chin)*self.scale)
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
