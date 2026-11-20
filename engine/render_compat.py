"""Blender-free compatibility and memory guidance, also shipped beside the worker."""
import re


def version_tuple(value):
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(int(x) for x in value[:3])
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', str(value))
    if not match:
        raise ValueError('Could not parse Blender version')
    return tuple(map(int, match.groups()))


def check_version(snapshot, worker, policy='minor'):
    local, remote = version_tuple(snapshot), version_tuple(worker)
    if policy not in ('exact', 'minor'):
        raise ValueError('Unknown Blender version policy')
    if local[:2] != remote[:2] or (policy == 'exact' and local != remote):
        raise ValueError('Blender version mismatch: snapshot %s, worker %s (%s policy)' %
                         ('.'.join(map(str, local)), '.'.join(map(str, remote)), policy))
    if local != remote:
        return ['Blender patch differs: snapshot %s, worker %s (minor policy); inspect output compatibility.' %
                ('.'.join(map(str, local)), '.'.join(map(str, remote)))]
    return []


def memory_warning(estimated_bytes, vram_bytes):
    if estimated_bytes and vram_bytes and estimated_bytes > vram_bytes:
        return ['Estimated scene/render memory %.2f GiB exceeds GPU VRAM %.2f GiB. '
                'Try a lower resolution; reduce textures/geometry if scene assets dominate. '
                'This is a heuristic, not a measured allocation.' %
                (estimated_bytes/2**30, vram_bytes/2**30)]
    return []
