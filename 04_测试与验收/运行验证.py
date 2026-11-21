"""Compatibility alias; the single implementation is run_checks.py."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name('run_checks.py')), run_name='__main__')
