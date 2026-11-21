"""Verified controller mirror. Completed frames survive cleanup, cancellation and resume."""
from pathlib import Path
import re

from engine.remote_frames import read_index, write_index
from .config import RemoteError
from .transport import file_hash

FRAME=re.compile(r'^frames/(main|handle_\d+)/-?\d+\.png$')


def mirror(endpoint,ident,directory,on_progress=None):
    index=endpoint.rpc('frames',id=ident)
    local=read_index(directory);changed=0
    for name,entry in index.get('files',{}).items():
        if not (FRAME.fullmatch(name) or name=='audio.wav') or not re.fullmatch('[0-9a-f]{64}',entry.get('sha256','')):
            raise RemoteError('Invalid durable frame manifest')
        dest=Path(directory)/name
        if dest.is_file() and file_hash(dest)==entry['sha256']:
            local['files'][name]=entry;continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        part=dest.with_suffix(dest.suffix+'.part')
        endpoint.download(ident,name,part)
        if file_hash(part)!=entry['sha256']:
            raise RemoteError('Durable frame checksum mismatch')
        part.replace(dest);local['files'][name]=entry;changed+=1
        write_index(directory,local)
        if on_progress:on_progress()
    write_index(directory,local)
    return local,changed


def seeds(directory):
    index=read_index(directory)
    out={name:str(Path(directory)/name) for name,e in index['files'].items()
         if (Path(directory)/name).is_file() and file_hash(Path(directory)/name)==e['sha256']}
    index['files']={name:index['files'][name] for name in out}
    write_index(directory,index)
    if out:out['frames.json']=str(Path(directory)/'frames.json')
    return out
