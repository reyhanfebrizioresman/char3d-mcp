"""Blender-free render log metrics, including Blender 5.2's timestamped output."""
import re


def _seconds(value):
    result = 0.
    for part in value.split(':'):
        result = result*60 + float(part)
    return result


def _values(pattern, text):
    out = []
    for value in re.findall(pattern, text, re.M):
        try:
            out.append(_seconds(value))
        except ValueError:
            pass
    return out


def frame_times(log_text):
    """Per-frame seconds. New logs give cumulative timestamps, old logs durations."""
    durations = _values(r'\bTime: ([\d:.]+)', log_text)
    if durations:
        return durations
    timestamps = _values(r'^\s*([\d:.]+)\s+render\s*\|\s*Video append frame\s+\d+', log_text)
    return [t-(timestamps[i-1] if i else 0.) for i, t in enumerate(timestamps)
            if i == 0 or t > timestamps[i-1]]


def progress_cursor(log_text):
    """Exclusive completed frame index (legacy Fra lines announce a started frame)."""
    frames = [int(v) for v in re.findall(r'\bFra:\s*(\d+)', log_text)]
    frames += [int(v)+1 for v in re.findall(r'Video append frame\s+(\d+)', log_text)]
    return max(frames) if frames else None
