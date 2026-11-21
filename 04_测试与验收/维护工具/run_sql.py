"""Execute explicitly selected project SQL; this tool commits, so it is not a preview."""
# Resolve the integrated project by its marker, not by a fragile parent count.
from pathlib import Path as _BootstrapPath
import sys as _bootstrap_sys
for _base in _BootstrapPath(__file__).resolve().parents:
    _app_candidate = _base / '01_平台工程'
    if (_app_candidate / 'project_paths.py').is_file():
        _bootstrap_sys.path.insert(0, str(_app_candidate))
        _bootstrap_sys.path.insert(0, str(_base / '04_测试与验收'))
        break
else:
    raise RuntimeError('Cannot locate the integrated project root')
from project_paths import APP_ROOT, PROJECT_ROOT, SQL_ROOT, TEST_ROOT, DESIGN_ROOT, BACKUP_ROOT, PROCESS_ROOT, CURRENT_RECORDS, BUSINESS_SQL_DIRS, business_sql_path

from pathlib import Path
import argparse
import json
from local_runtime import load_runtime
from deploy import mysql_engine,sql_statements

def main():
    parser=argparse.ArgumentParser(description='Execute and COMMIT a selected project SQL file; review its scope first.')
    parser.add_argument('file')
    args=parser.parse_args()
    path=Path(args.file)
    path=path.resolve() if path.is_absolute() else (PROJECT_ROOT/path).resolve()
    if path.suffix!='.sql' or not any(path.is_relative_to(base.resolve()) for base in (SQL_ROOT,TEST_ROOT)):
        parser.error('SQL must be a .sql file within the database or validation directories')
    load_runtime()
    statements=0;grids=0
    with mysql_engine().connect() as db:
        try:
            for sql in sql_statements(path.read_text(encoding='utf-8')):
                result=db.exec_driver_sql(sql);statements+=1
                if result.returns_rows:
                    result.fetchall();grids+=1
            db.commit()
        except Exception:
            db.rollback()
            raise
    print(json.dumps({'passed':True,'statements':statements,'result_grids':grids},ensure_ascii=False))
if __name__=='__main__':main()
