"""Run local automatic intake independently of browser sessions."""
import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'apps/retail'),str(ROOT/'apps/onboarding/src'),str(ROOT/'apps/catalog'),str(ROOT/'apps/po')]
from retail_workflow.store import WorkflowStore,now
from retail_workflow.auto_intake import scan
from catalog_operations.persistence.repository import CatalogRepository

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inbox',type=Path,default=ROOT/'local_intake/inbox')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args();args.inbox.mkdir(parents=True,exist_ok=True)
    runtime=args.inbox.parent;lock=(runtime/'worker.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:raise SystemExit('An intake worker already owns this inbox.')
    store=WorkflowStore()
    def repo(batch):return CatalogRepository('sqlite:///'+str((runtime/(batch+'-catalog.db')).resolve()).replace('\\','/'))
    while True:
        results=scan(store,args.inbox,repo)
        status={'heartbeat':now(),'inbox':str(args.inbox.resolve()),'submissions':[{'Folder':a,'Result':b} for a,b in results]}
        temp=runtime/'status.tmp';temp.write_text(json.dumps(status),encoding='utf-8');temp.replace(runtime/'status.json')
        if args.once:break
        time.sleep(10)
if __name__=='__main__':main()
