"""Run isolated app suites to avoid overlapping module names between apps."""
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for app in ('retail','onboarding','catalog','po'):
    subprocess.run([sys.executable,'-m','pytest','tests','-q'],cwd=ROOT/'apps'/app,check=True)
subprocess.run([sys.executable,'-m','pytest','tests','-q'],cwd=ROOT,check=True)

