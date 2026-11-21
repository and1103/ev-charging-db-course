"""Reproduce the complete build in one NEW, explicitly named local schema.

Run with CHARGE_ADMIN_DSN supplied by the administrator. Existing databases,
users, passwords and the DPAPI runtime file are never replaced or removed.
"""

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
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote, quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from local_runtime import load_runtime

ROOT = APP_ROOT

BEIJING = timezone(timedelta(hours=8))
EXPECTED_BUSINESS_TABLES = 44


class VerificationFailure(RuntimeError):
    """Contains only a deliberately safe diagnostic."""


def safe_text(value, secrets):
    value = re.sub(r'mysql(?:\+pymysql)?://[^\s\'"<>]+', '<redacted-dsn>', value)
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            value = value.replace(secret, '<redacted>')
    value = re.sub(r'(?:scrypt:|pbkdf2:|\$argon2)[^\s\'"<>]+', '<redacted-password-hash>', value)
    return value


def main():
    parser=argparse.ArgumentParser(description='Build into one NEW schema; existing schemas are never overwritten.')
    parser.add_argument('--target',required=True,help='Explicit NEW database name, never charge_course_20261114')
    args=parser.parse_args()
    TARGET=args.target
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,63}',TARGET) or TARGET=='charge_course_20261114':
        parser.error('Target must be a valid new, non-primary database name')
    started = datetime.now(BEIJING)
    out = CURRENT_RECORDS / '空库复现' / started.strftime('%Y%m%d-%H%M%S-%f')
    out.mkdir(parents=True, exist_ok=False)
    report = {'target_database': TARGET, 'started_at': started.isoformat(), 'created_new_database': False,
              'existing_database_policy': 'refuse; never drop or overwrite', 'steps': [], 'passed': False}
    secrets = []
    engine = None

    def save():
        (out / 'clean_build_result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def run_step(script, *arguments):
        tick = time.perf_counter()
        script_path={'deploy_local.py':SQL_ROOT/'部署工具/deploy_local.py','seed_extended.py':SQL_ROOT/'初始化与样例/seed_extended.py','seed_fleet.py':SQL_ROOT/'初始化与样例/seed_fleet.py'}[script]
        process = subprocess.run([sys.executable, str(script_path), *arguments], cwd=PROJECT_ROOT,
                                 env=dict(os.environ, PYTHONIOENCODING='utf-8'), capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=240)
        name = Path(script).stem
        # Never persist exception tracebacks: DBAPI diagnostics can contain parameters.
        log = f'script={script}; returncode={process.returncode}\n' + safe_text(process.stdout, secrets)
        if process.stderr:
            log += '\nstderr was present; sensitive diagnostics were not persisted.\n'
        (out / f'{name}.log').write_text(log, encoding='utf-8')
        report['steps'].append({'script': script, 'arguments': list(arguments), 'returncode': process.returncode,
                                'seconds': round(time.perf_counter()-tick, 3), 'log': f'{name}.log'})
        save()
        if process.returncode:
            raise VerificationFailure(f'{script} returned a nonzero exit status; the new schema was retained for inspection.')

    try:
        supplied_admin = os.environ.get('CHARGE_ADMIN_DSN')
        if not supplied_admin:
            raise VerificationFailure('CHARGE_ADMIN_DSN must be explicitly supplied by the administrator.')
        # Preserve the existing demo password, PII key and session secret in memory.
        # load_runtime uses setdefault and does not rewrite its encrypted file.
        load_runtime()
        for key in ('CHARGE_DEMO_PASSWORD', 'CHARGE_PII_KEY', 'CHARGE_SESSION_SECRET'):
            if not os.environ.get(key):
                raise VerificationFailure('The existing DPAPI runtime must provide demo, PII and session configuration.')
        url = make_url(supplied_admin)
        if url.drivername != 'mysql+pymysql' or url.username != 'root':
            raise VerificationFailure('A mysql+pymysql root administrator connection is required.')
        if url.host not in ('127.0.0.1', 'localhost', '::1') or (url.port or 3306) != 3307:
            raise VerificationFailure('Refusing a server other than the dedicated local MySQL instance on port 3307.')
        for key, value in os.environ.items():
            if key.startswith('CHARGE_') and any(word in key for word in ('PASSWORD', 'SECRET', 'KEY', 'DSN', 'URL')):
                secrets.extend((value, quote(value, safe=''), quote_plus(value)))
        if url.password:
            secrets.extend((url.password, quote(url.password, safe=''), quote_plus(url.password)))
        server_url = URL.create(url.drivername, username=url.username, password=url.password,
                                host=url.host, port=url.port, query=url.query)
        engine = create_engine(server_url, isolation_level='AUTOCOMMIT',
                               connect_args={'init_command': "SET time_zone = '+08:00'"})
        with engine.connect() as server:
            version = server.exec_driver_sql('SELECT VERSION()').scalar_one()
            if not re.match(r'^8\.4\.', version):
                raise VerificationFailure('The clean reproduction requires MySQL 8.4.')
            report['mysql_version'] = version
            if server.execute(text('SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=:schema'), {'schema': TARGET}).scalar():
                raise VerificationFailure('The verification schema already exists; refusing to reuse, delete or overwrite it.')
            server.exec_driver_sql(f'CREATE DATABASE `{TARGET}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
            report['created_new_database'] = True
            report['routine_creation_setting_before'] = int(server.exec_driver_sql('SELECT @@GLOBAL.log_bin_trust_function_creators').scalar_one())
        verify_dsn = url.set(database=TARGET).render_as_string(hide_password=False)
        secrets.append(verify_dsn)
        os.environ['CHARGE_ADMIN_DSN'] = verify_dsn
        os.environ['CHARGE_DATABASE_URL'] = verify_dsn
        save()
        run_step('deploy_local.py', '--demo')
        run_step('seed_extended.py')
        run_step('seed_fleet.py')
        verify = create_engine(url.set(database=TARGET), isolation_level='READ COMMITTED',
                               connect_args={'init_command': "SET time_zone = '+08:00'"})
        try:
            with verify.connect() as db:
                names = db.execute(text('SELECT TABLE_NAME FROM information_schema.TABLES '
                                        "WHERE TABLE_SCHEMA=:schema AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"), {'schema': TARGET}).scalars().all()
                tables = []
                for name in names:
                    quoted = '`' + name.replace('`', '``') + '`'
                    count = int(db.exec_driver_sql(f'SELECT COUNT(*) FROM {quoted}').scalar_one())
                    tables.append({'table': name, 'rows': count, 'business_table': name != 'charge_migration'})
                report['tables'] = tables
                business = [item for item in tables if item['business_table']]
                report['business_table_count'] = len(business)
                report['all_business_tables_at_least_20_rows'] = all(item['rows'] >= 20 for item in business)
                report['control_table_exclusion'] = 'charge_migration records deployment versions, not course business test data.'
                report['views'] = db.execute(text('SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA=:schema ORDER BY TABLE_NAME'), {'schema': TARGET}).scalars().all()
                report['routines'] = [dict(row) for row in db.execute(text('SELECT ROUTINE_NAME name,ROUTINE_TYPE type FROM information_schema.ROUTINES '
                                                                          'WHERE ROUTINE_SCHEMA=:schema ORDER BY ROUTINE_TYPE,ROUTINE_NAME'), {'schema': TARGET}).mappings()]
                report['triggers'] = db.execute(text('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=:schema ORDER BY TRIGGER_NAME'), {'schema': TARGET}).scalars().all()
                report['view_count'] = len(report['views'])
                report['procedure_count'] = sum(item['type'] == 'PROCEDURE' for item in report['routines'])
                report['function_count'] = sum(item['type'] == 'FUNCTION' for item in report['routines'])
                report['trigger_count'] = len(report['triggers'])
                report['routine_creation_setting_after'] = int(db.exec_driver_sql('SELECT @@GLOBAL.log_bin_trust_function_creators').scalar_one())
                report['checks'] = {
                    'exactly_44_business_tables': len(business) == EXPECTED_BUSINESS_TABLES,
                    'each_business_table_at_least_20_rows': report['all_business_tables_at_least_20_rows'],
                    'at_least_15_views': report['view_count'] >= 15,
                    'at_least_5_procedures': report['procedure_count'] >= 5,
                    'at_least_5_triggers': report['trigger_count'] >= 5,
                    'routine_creation_setting_restored': report['routine_creation_setting_before'] == report['routine_creation_setting_after'],
                }
                report['passed'] = all(report['checks'].values())
        finally:
            verify.dispose()
        if not report['passed']:
            raise VerificationFailure('Build completed, but one or more course-object/data checks did not pass; see the JSON counts.')
    except VerificationFailure as error:
        report['error'] = str(error)
    except Exception as error:
        # No repr/traceback: connection errors may carry URLs or SQL parameters.
        report['error'] = 'Verification failed; exception details were not persisted.'
        report['error_type'] = type(error).__name__
        original = getattr(error, 'orig', None)
        if original and original.args and isinstance(original.args[0], int):
            report['mysql_error_number'] = original.args[0]
    finally:
        if engine is not None:
            engine.dispose()
        report['finished_at'] = datetime.now(BEIJING).isoformat()
        save()
    print(json.dumps({'passed': report['passed'], 'created_new_database': report['created_new_database'],
                      'target_database': TARGET, 'report': str(out / 'clean_build_result.json')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
