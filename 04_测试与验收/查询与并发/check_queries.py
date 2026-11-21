"""Compare 15 canonical query pairs in a read-only snapshot; EXPLAIN is opt-in."""
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

import argparse
import json
from datetime import datetime
from local_runtime import load_runtime
from deploy import mysql_engine, sql_statements
from verification_support import output_directory

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--explain',action='store_true',help='EXPLAIN ANALYZE first pair per line; requires SHOW VIEW permission')
    args=parser.parse_args()
    load_runtime()
    report={'checked_at':datetime.now().isoformat(timespec='seconds'),'scope':'Read-only equivalence check; empty results do not prove positive business coverage.','pairs':[],'execution_plans':[]}
    with mysql_engine('CHARGE_ADMIN_DSN' if args.explain else 'CHARGE_DATABASE_URL').connect().execution_options(isolation_level='REPEATABLE READ') as db:
        db.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        try:
            for member in BUSINESS_SQL_DIRS:
                path=business_sql_path(member,'queries.sql')
                queries=list(sql_statements(path.read_text(encoding='utf-8')))
                assert len(queries)==6,(member,'expected 6 statements')
                for index in range(0,6,2):
                    left,right=queries[index:index+2]
                    a,b=db.exec_driver_sql(left).all(),db.exec_driver_sql(right).all()
                    matched=a==b
                    report['pairs'].append({'line':member,'question':index//2+1,'rows_left':len(a),'rows_right':len(b),'matched':matched,'nonempty':bool(a)})
                    assert matched,(member,index//2+1,'result mismatch')
                    if args.explain and index==0:
                        for query in (left,right):
                            report['execution_plans'].append({'line':member,'plan':[row[0] for row in db.exec_driver_sql('EXPLAIN ANALYZE '+query)]})
        finally:
            db.rollback()
    report.update(passed=all(x['matched'] for x in report['pairs']),pair_count=len(report['pairs']),nonempty_pairs=sum(x['nonempty'] for x in report['pairs']))
    report['empty_pairs']=report['pair_count']-report['nonempty_pairs']
    (output_directory()/'查询等价结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','pair_count','nonempty_pairs','empty_pairs')},ensure_ascii=False))
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
