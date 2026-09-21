"""Local process-safe locks and verified, non-destructive backup recovery."""
from contextlib import contextmanager, closing
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import zipfile
from uuid import uuid4

@contextmanager
def _os_lock(path, timeout=10):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    handle=open(path,'a+b');handle.seek(0,2)
    if handle.tell()==0:handle.write(b'0');handle.flush()
    end=time.monotonic()+timeout
    while True:
        try:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            break
        except (OSError,BlockingIOError):
            if time.monotonic()>=end:
                handle.close();raise ValueError('This local record is being updated. Retry after the current operation completes.')
            time.sleep(.05)
    try:yield
    finally:
        handle.seek(0)
        if os.name=='nt': msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()


def create_backup(data, destination):
    data=Path(data).resolve();destination=Path(destination).resolve()
    if destination.is_relative_to(data):raise ValueError('Backups must be outside the live data directory.')
    destination.mkdir(parents=True,exist_ok=True)
    archive=destination/('retail-'+uuid4().hex+'.zip');manifest={}
    with local_lock(data/'maintenance.lock',timeout=1), tempfile.TemporaryDirectory() as scratch:
        try:
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as target:
                for source in sorted(data.rglob('*')):
                    if not source.is_file() or source.suffix in {'.lock','.tmp'} or source.name.endswith(('-wal','-shm','-journal')):continue
                    relative=source.relative_to(data).as_posix()
                    parts=source.relative_to(data).parts
                    if len(parts)>1 and parts[0]=='workspace_runs' and not (data/parts[0]/parts[1]/'result.json').exists():continue
                    if source.suffix=='.db':
                        snapshot=Path(scratch)/'snapshot.db'
                        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(snapshot)) as dst:
                            src.backup(dst);dst.commit()
                        payload=snapshot.read_bytes();snapshot.unlink()
                    else:payload=source.read_bytes()
                    manifest[relative]=hashlib.sha256(payload).hexdigest();target.writestr(relative,payload)
                target.writestr('BACKUP-MANIFEST.json',json.dumps({'version':1,'files':manifest},indent=2))
            verify_backup(archive)
        except Exception:
            archive.unlink(missing_ok=True);raise
    return archive


def verify_backup(archive):
    with zipfile.ZipFile(archive) as source:
        manifest=json.loads(source.read('BACKUP-MANIFEST.json'))['files']
        if len(source.namelist())!=len(set(source.namelist())):raise ValueError('Duplicate backup members.')
        if set(source.namelist())!=set(manifest)|{'BACKUP-MANIFEST.json'}:raise ValueError('Unexpected backup members.')
        for name,digest in manifest.items():
            path=Path(name)
            if path.is_absolute() or '..' in path.parts or ':' in name:raise ValueError('Unsafe backup path.')
            if hashlib.sha256(source.read(name)).hexdigest()!=digest:raise ValueError('Backup checksum mismatch.')
    return manifest


def restore_copy(archive,destination):
    manifest=verify_backup(archive);destination=Path(destination)
    if destination.exists():raise ValueError('Restore destination must be a new directory; live data will not be overwritten.')
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        for name in manifest:
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read(name))
    return destination


import threading
from functools import wraps
_MUTEX=threading.RLock()
_THREAD_LOCKS={}
_HELD=threading.local()

@contextmanager
def local_lock(path, timeout=10):
    key=str(Path(path).resolve())
    with _MUTEX: guard=_THREAD_LOCKS.setdefault(key,threading.RLock())
    if not guard.acquire(timeout=timeout):raise ValueError('Another local operation is in progress. Retry shortly.')
    held=getattr(_HELD,'paths',set());_HELD.paths=held
    try:
        if key in held:yield
        else:
            with _os_lock(path,timeout):
                held.add(key)
                try:yield
                finally:held.remove(key)
    finally:guard.release()

def guarded_write(method):
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        root=self.path.parent.parent if self.path.suffix=='.json' else self.path.parent
        with local_lock(root/'maintenance.lock',timeout=300):
            return method(self,*args,**kwargs)
    return wrapped
