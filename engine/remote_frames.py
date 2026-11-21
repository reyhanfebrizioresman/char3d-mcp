"""Durable frame index shared by standalone Blender workers and encoders; no network."""
import hashlib
import json
import os
from pathlib import Path
import struct
import uuid
import zlib


def read_index(root):
    try:
        return json.loads((Path(root)/'frames.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'version':1,'files':{}}


def write_index(root, index):
    path=Path(root)/'frames.json'
    tmp=path.with_name('frames.'+uuid.uuid4().hex+'.tmp')
    with open(tmp,'w',encoding='utf-8') as stream:
        json.dump(index,stream)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp,path)


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def plan(spec):
    out=[]
    for channel,start,end,camera in [('main',spec['start'],spec['start']+spec['frames']-1,None)]+[
        ('handle_'+str(i),h['frames'][0],h['frames'][1],h['camera']) for i,h in enumerate(spec.get('handles',[]))]:
        out.extend(dict(path=f'frames/{channel}/{f:08d}.png',frame=f,channel=channel,camera=camera)
                   for f in range(start,end+1))
    return out


def valid_png(path, size):
    """Recover an atomically renamed frame even if power failed before index update."""
    try:
        with open(path,'rb') as stream:
            if stream.read(8)!=b'\x89PNG\r\n\x1a\n': return False
            first=True
            while True:
                header=stream.read(8)
                if len(header)!=8: return False
                length,kind=struct.unpack('>I4s',header)
                if length>64*2**20: return False
                data=stream.read(length); crc=stream.read(4)
                if len(data)!=length or len(crc)!=4 or zlib.crc32(kind+data)!=struct.unpack('>I',crc)[0]: return False
                if first:
                    if kind!=b'IHDR' or list(struct.unpack('>II',data[:8]))!=list(size): return False
                    first=False
                if kind==b'IEND': return stream.read(1)==b''
    except (OSError,ValueError,struct.error):
        return False


def provenance(index):
    groups={}
    for entry in index.get('files',{}).values():
        if 'frame' in entry:
            groups.setdefault(entry.get('source','unknown'),{}).setdefault(entry['channel'],[]).append(entry['frame'])
    for channels in groups.values():
        for channel,frames in channels.items():
            ranges=[]
            for frame in sorted(set(frames)):
                if ranges and frame==ranges[-1][1]+1: ranges[-1][1]=frame
                else:ranges.append([frame,frame])
            channels[channel]=ranges
    return groups
