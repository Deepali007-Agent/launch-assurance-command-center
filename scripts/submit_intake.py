"""Seal a CSV folder and atomically deliver it to local intake."""
import argparse,hashlib,json,shutil,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def submit(source,inbox,batch,name,actor,owners=None):
    source=Path(source);inbox=Path(inbox);inbox.mkdir(parents=True,exist_ok=True)
    revisions=[]
    for file in inbox.glob('*/manifest.json'):
        try:
            existing=json.loads(file.read_text(encoding='utf-8-sig'))
            if existing.get('batch_key')==batch:revisions.append(int(existing['revision']))
        except (OSError,ValueError,KeyError):continue
    identifier=uuid.uuid4().hex
    staging=inbox.parent/('staging-'+identifier);staging.mkdir()
    manifest={'submission_id':identifier,'revision':max(revisions,default=0)+1,'batch_key':batch,'launch_name':name,'submitted_by':actor,'files':{},'owners':owners or {}}
    for role in ('vendor','catalog','po','inventory','shipments'):
        path=source/(role+'.csv')
        if not path.exists():
            if role in ('vendor','catalog','po'):raise ValueError('Missing '+path.name)
            continue
        target=staging/path.name;shutil.copyfile(path,target)
        manifest['files'][role]={'name':path.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    metadata=source/'launch.json'
    if metadata.exists():
        config=json.loads(metadata.read_text(encoding='utf-8-sig'))
        for key in ('launch_date','horizon'):
            if key in config:manifest[key]=config[key]
    (staging/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    # Same filesystem rename: watcher never sees an unfinished submission.
    target=inbox/identifier;staging.rename(target)
    return target

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--batch',required=True);p.add_argument('--name',required=True);p.add_argument('--actor',required=True)
    p.add_argument('--inbox',type=Path,default=ROOT/'local_intake/inbox')
    a=p.parse_args();print(submit(a.source,a.inbox,a.batch,a.name,a.actor))
if __name__=='__main__':main()
