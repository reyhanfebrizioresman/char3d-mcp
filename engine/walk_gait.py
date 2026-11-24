"""Frame-rate independent signals shared by floor gait authoring and its checks."""
import math

# Fractions of a full same-foot cycle; there are two 10% double supports.
LOADING_END = .10
MID_STANCE_END = .30
TERMINAL_END = .50
TOE_OFF = .60
DOUBLE_SUPPORT = TOE_OFF - TERMINAL_END
SPRING_OMEGA = 14.0                 # rad/s, critically damped
MAX_LEAN_DEG = 7.0
ACCEL_LEAN_GAIN = .65
BRAKE_DROP_M = .012


def smooth(u):
    u = max(0.0, min(1.0, u))
    return u*u*(3-2*u)


def contact_phase(cycle):
    """Semantic phase for a foot whose heel strike is cycle zero."""
    u = cycle % 1.0
    for end, name in ((LOADING_END, 'loading_response'), (MID_STANCE_END, 'mid_stance'),
                      (TERMINAL_END, 'terminal_stance'), (TOE_OFF, 'pre_swing')):
        if u < end:
            return name
    return 'swing'


def spring_step(value, velocity, target, dt, omega=SPRING_OMEGA):
    """Exact critically damped spring under a constant target (stable at any dt)."""
    error = value - target
    carry = velocity + omega*error
    decay = math.exp(-omega*dt)
    return target + (error + carry*dt)*decay, (velocity - omega*carry*dt)*decay


def step_variation(phase, channel=0):
    """Continuous, repeatable per-step accent; no RNG state or route/foot jitter."""
    step = math.floor(phase)
    u = smooth(phase-step)
    def sample(index):
        bits = ((index + 1)*1664525 + (channel + 11)*1013904223) & 0xffffffff
        bits ^= bits >> 16
        bits = (bits*2246822519) & 0xffffffff
        return 2*(bits/0xffffffff)-1
    return sample(step)*(1-u) + sample(step+1)*u


def momentum(samples, fps):
    """Sagittal acceleration response in degrees, with a bounded braking knee load.

    XY positions are the planned root, so hip sway cannot drive feedback. An exact
    spring filters a <=7 degree target; the final four samples are a settled hold.
    """
    n = len(samples)
    velocities = []
    for i in range(n):
        a, b = max(0, i-1), min(n-1, i+1)
        velocities.append(tuple((samples[b][0][k]-samples[a][0][k])*fps/max(1, b-a)
                                for k in (0, 1)))
    signals = []
    value = velocity = 0.0
    for i, (_pos, yaw) in enumerate(samples):
        a, b = max(0, i-1), min(n-1, i+1)
        accel = tuple((velocities[b][k]-velocities[a][k])*fps/max(1, b-a) for k in (0, 1))
        forward = accel[0]*math.sin(yaw)-accel[1]*math.cos(yaw)
        target = max(-MAX_LEAN_DEG, min(MAX_LEAN_DEG,
                     math.degrees(math.atan2(forward, 9.81))*ACCEL_LEAN_GAIN))
        value, velocity = spring_step(value, velocity, target, 1/fps)
        signals.append(value)
    # Release the small residual only after root travel ends, before the fixed hold.
    moving = [i for i in range(1, n) if any(abs(samples[i][0][k]-samples[i-1][0][k]) > 1e-8
                                           for k in (0, 1))]
    last = moving[-1] if moving else 0
    end = max(last, n-4)
    for i in range(last, n):
        signals[i] *= 1-smooth((i-last)/max(1, end-last))
    return [(v, BRAKE_DROP_M*max(0.0, -v)/MAX_LEAN_DEG) for v in signals]
