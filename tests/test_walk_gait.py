"""Contact phase, deterministic accents and exact momentum integration (no Blender)."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.walk_gait import contact_phase, momentum, spring_step, step_variation


def main():
    assert [contact_phase(u) for u in (0, .10, .30, .50, .60, .999, 1)] == [
        'loading_response', 'mid_stance', 'terminal_stance', 'pre_swing', 'swing', 'swing', 'loading_response']
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
    print('WALK GAIT UNIT OK (phases, critical damping, 24/30/60 fps, deterministic step accents)')


if __name__ == '__main__':
    main()
