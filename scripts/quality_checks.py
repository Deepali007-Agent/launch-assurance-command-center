"""Report per-app coverage without claiming untested paths are covered."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'quality';OUT.mkdir(exist_ok=True)
subprocess.run([sys.executable,'-m','ruff','check','apps','scripts','streamlit_app.py','--select','E9,F63,F7,F82'],cwd=ROOT,check=True)
subprocess.run([sys.executable,'-m','compileall','-q','apps','scripts','streamlit_app.py'],cwd=ROOT,check=True)
summary=[]
for app in ('retail','onboarding','catalog','po'):
 folder=ROOT/'apps'/app
 subprocess.run([sys.executable,'-m','pytest','tests','-q','--cov=.','--cov-config='+str(ROOT/'.coveragerc'),'--cov-report=json:'+str(OUT/(app+'.json')),'--cov-report=term:skip-covered'],cwd=folder,check=True)
 report=json.loads((OUT/(app+'.json')).read_text())
 summary.append({'app':app,**report['totals']})
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
subprocess.run([sys.executable,'-m','pytest','tests','-q'],cwd=ROOT,check=True)
