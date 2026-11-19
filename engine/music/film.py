"""Continuous score across film cards/cuts, independent of picture transitions."""
import numpy as np

from .compose import compose
from .dsp import RATE, render, metrics, write_cached


def duck_envelope(frames, ranges, fps, amount_db=-12, attack=.15, release=.4):
    gain = np.ones(len(frames))
    floor = 10**(amount_db/20)
    # Match scene duck_music: union including short gaps; minimum of each ramp.
    merged = []
    for a, b in sorted(ranges):
        if merged and a-merged[-1][1] <= .5*fps:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    for a, b in merged:
        envelope = np.full(len(frames), floor)
        before, after = frames < a, frames > b
        envelope[before] = floor+(1-floor)*np.clip((a-frames[before])/(attack*fps), 0, 1)
        envelope[after] = floor+(1-floor)*np.clip((frames[after]-b)/(release*fps), 0, 1)
        gain = np.minimum(gain, envelope)
    return gain


def score_film(scenes, fps, total_frames, directory):
    """Same mood extends one composition; different moods overlap with smooth tails.

    Scene preview scores are replaced in render snapshots only. Manual music stays
    in the child clips. Disabled scenes have no generated score, including cards.
    """
    groups = []
    speech, cuts, emotions, custom = [], [], [], []
    for scene in scenes:
        cfg = scene.get("score")
        offset = scene["film_frames"][0]-scene["frames"][0]
        speech.extend([[a+offset, b+offset] for a, b in scene.get("speech", [])])
        if cfg and cfg.get('follow_cuts', True):
            cuts.extend([f+offset for f in scene.get("score_cuts", [])])
        if cfg and cfg.get('follow_emotion', True):
            emotions.extend([dict(e, frame=e["frame"]+offset) for e in scene.get("score_emotions", [])])
        if cfg:
            custom.extend([dict(e, frame=e['frame']+offset) for e in cfg.get('custom_sections', [])])
        if not cfg:
            groups.append(dict(start=scene["segment_start"], end=scene["film_frames"][1]+1, cfg=None))
            continue
        start, end = scene["segment_start"], scene["film_frames"][1]+1
        same = ("mood", "key", "tempo", "seed", "volume", "intensity", "backend")
        if groups and groups[-1]["cfg"] and all(groups[-1]["cfg"].get(k) == cfg.get(k) for k in same):
            groups[-1]["end"] = end
        else:
            groups.append(dict(start=start, end=end, cfg=cfg))
        if cfg.get('follow_cuts', True):
            cuts.append(start)
    enabled = [g for g in groups if g["cfg"]]
    if not enabled:
        return None
    samples = np.zeros((round(total_frames/fps*RATE), 2), np.float32)
    report = []
    for index, group in enumerate(groups):
        if not group["cfg"]:
            continue
        cfg = group["cfg"]
        lo, hi = group["start"], group["end"]
        # At a hard cut use a 0.6 s overlap centered on that cut. Dissolves keep
        # their original overlap. Explicitly disabled neighbors never receive tails.
        before = index > 0 and groups[index-1]["cfg"] is not None
        after = index+1 < len(groups) and groups[index+1]["cfg"] is not None
        def overlap_with(neighbor):
            return min(round(.30*fps), max(1, (hi-lo)//8), max(1, (neighbor['end']-neighbor['start'])//8))
        pre = overlap_with(groups[index-1]) if before else 0
        post = overlap_with(groups[index+1]) if after else 0
        a = max(1, lo-pre)
        b = min(total_frames+1, hi+post)
        duration = (b-a)/fps
        score = compose(duration, cfg["mood"], cfg["tempo"], cfg["key"], cfg.get("intensity", .6),
                        cfg["seed"], cuts=[f for f in cuts if a <= f < b],
                        emotions=[e for e in emotions if a <= e["frame"] < b],
                        sections=[e for e in custom if a <= e['frame'] < b], fps=fps, first=a)
        x = render(score, backend=cfg.get("backend", "auto"))
        frame_grid = np.arange(a, b+1)
        envelope = duck_envelope(frame_grid, speech, fps)*cfg.get("volume", .35)
        if before:
            end = groups[index-1]['end']+pre
            envelope *= np.sin(np.clip((frame_grid-a)/max(1, end-a), 0, 1)*np.pi/2)**2
        else:
            envelope *= np.clip((frame_grid-a)/max(1, fps*cfg.get("fade_in", 1)), 0, 1)
        if after:
            start = groups[index+1]['start']-post
            envelope *= np.sin(np.clip((b-frame_grid)/max(1, b-start), 0, 1)*np.pi/2)**2
        else:
            envelope *= np.clip((b-frame_grid)/max(1, fps*cfg.get("fade_out", 2)), 0, 1)
        # Frame envelopes become sample-smooth ramps, including a fractional fps.
        gain = np.interp(np.arange(len(x))/RATE*fps+a, frame_grid, envelope)
        x *= gain[:, None]
        at = round((a-1)/fps*RATE)
        count = min(len(x), len(samples)-at)
        samples[at:at+count] += x[:count]
        report.append(dict(mood=cfg["mood"], tempo=cfg["tempo"], key=cfg["key"], frames=[a, b-1],
                           renderer=score['renderer'], transition="crossfade" if before else "start", sections=score["sections"]))
    # Preserve intended quiet dialog level; peak guard only, never renormalize it.
    from .dsp import true_peak
    samples *= min(1, 10**(-1.05/20)/max(true_peak(samples), 1e-12))
    path, digest = write_cached(samples, directory)
    return dict(path=path, hash=digest, sections=report, speech_ranges=speech,
                loudness=metrics(samples), volume_baked=True)
