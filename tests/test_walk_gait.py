"""Contact phase, deterministic accents and exact momentum integration (no Blender)."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.walk_gait import contact_phase, momentum, spring_step, step_variation, support_headings, knee_velocity_limit, stride_time_map, phase_edges


def main():
    assert [contact_phase(u) for u in (0, .10, .30, .50, .60, .999, 1)] == [
        'loading_response', 'mid_stance', 'terminal_stance', 'pre_swing', 'swing', 'swing', 'loading_response']
    # R7 braking pop remains rejected at every supported cadence/FPS;
    # normal 400 deg/s swing is admitted, unlike the previous 336 deg/s cap.
    for fps in (24, 30, 60):
        for speed in (.6, 1., 1.6, 4.):
            cap = math.degrees(knee_velocity_limit(speed, fps))
            assert 400/fps < cap < 23.8*24/fps
        assert abs(math.degrees(knee_velocity_limit(1.,fps))*fps-408) < 1e-9
    for dt in (1/240, 1/24, .5, 10):
        value = speed = 0.0
        for _ in range(100):
            old = value
            value, speed = spring_step(value, speed, 7, dt)
            assert old <= value <= 7+1e-12 and math.isfinite(speed)
    # The exact solution composes identically across timestep sizes.
    one = spring_step(-3, 2, 5, .5)
    a, v = -3, 2
    for _ in range(30):
        a, v = spring_step(a, v, 5, 1/60)
    assert abs(a-one[0]) < 1e-12 and abs(v-one[1]) < 1e-12
    for i in range(1000):
        p = i/20
        assert -1 <= step_variation(p) <= 1
        assert step_variation(p) == step_variation(p)
        assert abs(step_variation(round(p)-1e-6)-step_variation(round(p)+1e-6)) < 1e-5
    assert len({round(step_variation(i), 4) for i in range(12)}) > 8
    for fps in (24, 30, 60):
        samples = []
        for i in range(3*fps):
            t = i/fps
            distance = .5*t*t if t < 1 else t-.5
            if t >= 2:
                distance = 1.5+(t-2)-.5*(t-2)**2
            samples.append(((0, -distance, 0), 0))
        samples += [(samples[-1][0], 0)]*round(.4*fps)
        signal = momentum(samples, fps)
        assert max(v for v, _ in signal) > 2 and min(v for v, _ in signal) < -2
        assert max(abs(v) for v, _ in signal) <= 7
        assert signal[-4:] == [(0, 0)]*4, signal[-4:]
    for fps in (24,30,60):
        phases = [i/(fps*.5) for i in range(2*fps+1)]
        samples = [((0,0,0),math.radians(70)*i/fps) for i in range(2*fps+1)]
        planned = support_headings(samples,phases,fps,math.radians(100))
        assert planned[-1] == samples[-1] and planned[0] == samples[0]
        assert planned != samples
        assert all(p[0] == q[0] for p,q in zip(planned,samples))
        assert max(abs(b[1]-a[1])*fps for a,b in zip(planned,planned[1:])) <= math.radians(100)+1e-8
        for i in range(1,len(phases)):
            if int(phases[i]) != int(phases[i-1]):
                assert planned[i] == samples[i]
        assert support_headings(samples,phases,fps,math.radians(100)) == planned
    boundaries = list(range(0,481,12))
    identity,cycles = stride_time_map(boundaries,500,None)
    assert identity == list(range(500)) and not cycles
    for seed in (0,1,37):
        times,cycles = stride_time_map(boundaries,500,seed)
        assert (times,cycles) == stride_time_map(boundaries,500,seed)
        assert all(b>a for a,b in zip(times,times[1:]))
        assert all(abs(times[i]-identity[i])<1e-9 for i in list(range(24))+list(range(456,500)))
        assert all(abs(c['duration_ratio']-1)<.0182 for c in cycles)
        assert max(c['duration_ratio'] for c in cycles)-min(c['duration_ratio'] for c in cycles)>.005
    assert stride_time_map(boundaries,500,0) != stride_time_map(boundaries,500,1)
    assert phase_edges([max(0,(i-.2)/12) for i in range(50)]) == [0,12,24,36,48]
    print('WALK GAIT UNIT OK (phases, critical damping, 24/30/60 fps, deterministic step accents)')


if __name__ == '__main__':
    main()
