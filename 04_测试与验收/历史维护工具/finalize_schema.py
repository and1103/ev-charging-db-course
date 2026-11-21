"""Explicit, reviewed upgrade of the already-owned course schema. Preserves data."""

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
from pathlib import Path
from verification_support import output_directory
from deploy import mysql_engine, migration_path, sql_statements


def main():
    if '--allow-historical-maintenance' not in sys.argv:
        raise RuntimeError('Historical database-modifying tool: review source and explicitly add --allow-historical-maintenance; not part of normal validation.')
    output = []
    with mysql_engine().connect() as db:
        if db.exec_driver_sql('SELECT DATABASE()').scalar_one() != 'charge_course_20261114':
            raise RuntimeError('Incremental upgrade is restricted to the course database')
        if not db.exec_driver_sql("SHOW COLUMNS FROM wallet_entry LIKE 'topup_ref'").first():
            db.exec_driver_sql("ALTER TABLE wallet_entry ADD COLUMN topup_ref varchar(64) CHARACTER SET ascii COLLATE ascii_bin NULL UNIQUE, ADD CONSTRAINT wallet_entry_topup_shape CHECK(topup_ref IS NULL OR (`change`>0 AND payment_id IS NULL AND refund_id IS NULL))")
            output.append('wallet_entry: added topup_ref, exact unique key and shape CHECK')
        if not db.exec_driver_sql("SHOW COLUMNS FROM alarm LIKE 'connector_id'").first():
            db.exec_driver_sql('ALTER TABLE alarm ADD connector_id bigint AFTER charger_id, ADD CONSTRAINT alarm_connector_fk FOREIGN KEY(connector_id) REFERENCES connector(id), ADD scope_connector bigint GENERATED ALWAYS AS (COALESCE(connector_id,0)) STORED, ADD CONSTRAINT alarm_positive_connector CHECK(connector_id IS NULL OR connector_id>0), DROP INDEX one_live_alarm, ADD UNIQUE KEY one_live_alarm(live_charger,scope_connector,code)')
            output.append('alarm: added gun scope, FK, ownership guards and scoped uniqueness')
        previous = db.exec_driver_sql('SELECT @@GLOBAL.log_bin_trust_function_creators').scalar_one()
        names = {'alarm_connector_insert', 'alarm_connector_update', 'raise_alarm_scope', 'raise_alarm', 'recover_alarm', 'v_live_alarm', 'v_late_alarm'}
        try:
            if not previous:
                db.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=1')
            for source in sql_statements(migration_path('C/07_monitor.sql').read_text(encoding='utf-8')):
                match = re.match(r'CREATE\s+(TRIGGER|PROCEDURE|FUNCTION|VIEW)\s+(\w+)', source, re.I)
                if not match or match[2] not in names:
                    continue
                kind, name = match.groups()
                if kind == 'VIEW':
                    db.exec_driver_sql(source.replace('CREATE VIEW', 'CREATE OR REPLACE VIEW', 1))
                else:
                    db.exec_driver_sql(f'DROP {kind} IF EXISTS `{name}`')
                    db.exec_driver_sql(source)
                output.append('refreshed ' + kind + ' ' + name)
            for source in sql_statements(migration_path('D/10_wallet.sql').read_text(encoding='utf-8')):
                db.exec_driver_sql('DROP FUNCTION IF EXISTS mock_wallet_topup')
                db.exec_driver_sql(source)
            db.exec_driver_sql("INSERT IGNORE INTO charge_migration VALUES ('D/10_wallet.sql')")
            db.commit()
        finally:
            if not previous:
                db.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=0')
        output.append('mock_wallet_topup installed; global routine setting restored')
    target = output_directory()/'历史增量升级.log'
    target.write_text('\n'.join(output)+'\n', encoding='utf-8')
    print('\n'.join(output))


if __name__ == '__main__':
    main()
