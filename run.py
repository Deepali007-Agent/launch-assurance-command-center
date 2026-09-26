"""Start one app, or all four, using the current Python environment."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
APPS={'retail':8508,'onboarding':8509,'catalog':8507,'po':8510}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app',choices=['all',*APPS],nargs='?',default='all')
    parser.add_argument('--port-offset',type=int,default=0,help='Add to every port, e.g. 100 for a separate test installation.')
    parser.add_argument('--auto-intake',action='store_true',help='Also monitor local_intake/inbox for sealed CSV batches.')
    args=parser.parse_args()
    selected=list(APPS) if args.app=='all' else [args.app]
    for name in selected:
        port=APPS[name]+args.port_offset
        with socket.socket() as check:
            try:check.bind(('127.0.0.1',port))
            except OSError:parser.error(f'Port {port} is occupied; stop the existing app or use --port-offset.')
    os.environ.update({name.upper()+'_APP_URL':f'http://localhost:{port+args.port_offset}' for name,port in APPS.items()})
    processes=[]
    try:
        if args.auto_intake:
            processes.append(subprocess.Popen([sys.executable,str(ROOT/'scripts/watch_intake.py')],cwd=ROOT))
        for name in selected:
            port=APPS[name]+args.port_offset
            processes.append(subprocess.Popen([sys.executable,'-m','streamlit','run','app.py','--server.port',str(port),'--server.address','127.0.0.1','--server.headless','true','--browser.gatherUsageStats','false'],cwd=ROOT/'apps'/name))
            print(f'{name}: http://localhost:{port}',flush=True)
        while all(p.poll() is None for p in processes):time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait()

if __name__=='__main__':main()

