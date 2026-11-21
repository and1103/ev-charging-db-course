"""Compatibility alias for the current HTTP verification; server must already run."""
from pathlib import Path
import runpy
for base in Path(__file__).resolve().parents:
    target=base/'04_测试与验收/维护工具/真实HTTP验证.py'
    if target.is_file():break
else:raise RuntimeError('Cannot locate integrated HTTP check')
runpy.run_path(str(target),run_name='__main__')
