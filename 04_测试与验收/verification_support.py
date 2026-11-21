"""Shared paths and safe result locations for the integrated validation tools."""
from pathlib import Path
import os
import sys
from datetime import datetime

for _base in Path(__file__).resolve().parents:
    if (_base / '01_平台工程/project_paths.py').is_file():
        sys.path.insert(0, str(_base / '01_平台工程'))
        break
else:
    raise RuntimeError('Cannot locate integrated project')
from project_paths import PROCESS_ROOT, CURRENT_RECORDS


def output_directory():
    supplied = os.environ.get('CHARGE_TEST_OUTPUT')
    target = Path(supplied) if supplied else CURRENT_RECORDS / '验证结果' / ('手动_' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    target = target.resolve()
    if not target.is_relative_to(PROCESS_ROOT.resolve()):
        raise RuntimeError('Validation output must remain within the project process folder')
    target.mkdir(parents=True, exist_ok=True)
    return target
