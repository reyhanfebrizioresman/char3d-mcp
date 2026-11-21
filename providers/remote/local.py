"""Local fallback uses the same native snapshot worker/Blender encoder, without SSH."""
from pathlib import Path
import shutil

from engine import remote_agent
from .transport import ROOT, file_hash
from .config import RemoteError


class LocalWorker:
    def __init__(self, target):
        self.target=target

    def rpc(self,action,**params):
        remote_agent.SOURCE=(ROOT/'engine/remote_agent.py').read_text(encoding='utf-8')
        try:return remote_agent.rpc(dict(root=self.target['remote_dir'],action=action,**params))
        except Exception as exc:raise RemoteError(str(exc)) from None

    def upload(self,files,blob_dir):
        root=Path(self.target['remote_dir'])/'blobs';root.mkdir(parents=True,exist_ok=True)
        mapping={}
        for name,path in files.items():
            h=file_hash(path);mapping[name]=h
            if not (root/h).exists():shutil.copyfile(path,root/h)
        return mapping

    def download(self,ident,name,dest):
        dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(self.target['remote_dir'])/'jobs'/ident/name,dest)
