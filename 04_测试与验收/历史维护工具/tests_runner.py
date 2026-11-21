"""Compatibility entry for the integrated runner; defaults to API checks."""
from pathlib import Path
import runpy
import sys
for base in Path(__file__).resolve().parents:
    target=base/'04_测试与验收/run_checks.py'
    if target.is_file():break
else:raise RuntimeError('Cannot locate integrated test runner')
sys.argv=[str(target),*(sys.argv[1:] or ['api'])]
runpy.run_path(str(target),run_name='__main__')
