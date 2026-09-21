"""Locate the shared workflow in the release layout."""
import sys
from pathlib import Path
shared=Path(__file__).resolve().parents[1]/'retail'
if str(shared) not in sys.path:sys.path.append(str(shared))
from retail_workflow import ui as workflow
