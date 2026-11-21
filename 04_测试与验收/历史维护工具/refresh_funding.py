"""Refresh only the reviewed funding routines; no tables or demo data are replaced."""

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

import sys
from pathlib import Path as _ProjectPath
import re
from deploy import mysql_engine, migration_path, sql_statements


def main():
    if '--allow-historical-maintenance' not in sys.argv:
        raise RuntimeError('Historical database-modifying tool: review source and explicitly add --allow-historical-maintenance; not part of normal validation.')
    names = ['check_fleet_credit_current', 'open_charge', 'finish_charge', 'authorize_more', 'approve_review']
    selected = {}
    for path in ('B/03_schema.sql', 'A/04_queue.sql', 'B/06_payment.sql'):
        for statement in sql_statements(migration_path(path).read_text(encoding='utf-8')):
            match = re.match(r'CREATE\s+(PROCEDURE|FUNCTION)\s+(\w+)', statement, re.I)
            if match and match[2] in names:
                selected[match[2]] = (match[1], statement)
    if set(selected) != set(names):
        raise RuntimeError('Expected routine definitions were not all found')
    with mysql_engine().connect() as db:
        previous = db.exec_driver_sql('SELECT @@GLOBAL.log_bin_trust_function_creators').scalar_one()
        try:
            if not previous:
                db.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=1')
            for name in names:
                kind, source = selected[name]
                db.exec_driver_sql(f'DROP {kind} IF EXISTS `{name}`')
                db.exec_driver_sql(source)
                print('refreshed', name)
            db.commit()
        finally:
            if not previous:
                db.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=0')


if __name__ == '__main__':
    main()
