"""Back up only the course database and validate restoration in a fresh database."""

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
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import re
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = APP_ROOT

SOURCE = 'charge_course_20261114'



def rewrite_database_identifiers(sql, source, target):
    # Rewrite SQL identifiers, including executable MySQL comments; preserve all data strings.
    result = []
    position = 0
    while position < len(sql):
        char = sql[position]
        if char in "'\"":
            quote = char
            end = position + 1
            while end < len(sql):
                if sql[end] == '\\':
                    end += 2
                elif sql[end] == quote:
                    if end + 1 < len(sql) and sql[end + 1] == quote:
                        end += 2
                    else:
                        end += 1
                        break
                else:
                    end += 1
            result.append(sql[position:end])
            position = end
        elif char == '`':
            end = position + 1
            while end < len(sql):
                if sql[end] == '`':
                    if end + 1 < len(sql) and sql[end + 1] == '`':
                        end += 2
                    else:
                        end += 1
                        break
                else:
                    end += 1
            token = sql[position:end]
            result.append('`' + target + '`' if token == '`' + source + '`' else token)
            position = end
        else:
            result.append(char)
            position += 1
    return ''.join(result)


def inventory(engine):
    with engine.connect() as db:
        tables = list(db.exec_driver_sql("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME").scalars())
        rows = {}
        for table in tables:
            # Sort encoded full rows so partition tables without a single-column key are covered too.
            content = sorted(json.dumps(list(row), ensure_ascii=False, default=str, separators=(',', ':'))
                             for row in db.exec_driver_sql(f'SELECT * FROM `{table}`'))
            rows[table] = {'rows': len(content), 'sha256': hashlib.sha256('\n'.join(content).encode()).hexdigest()}
        objects = {}
        for label, query in {
            'views': 'SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA=DATABASE()',
            'routines': 'SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()',
            'triggers': 'SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()',
        }.items():
            objects[label] = sorted(db.exec_driver_sql(query).scalars())
        for view in objects['views']:
            db.exec_driver_sql(f'SELECT * FROM `{view}` LIMIT 0')
        return {'tables': rows, 'objects': objects}


def main():
    parser=argparse.ArgumentParser(description='Full backup plus isolated restore into one explicitly NEW schema.')
    parser.add_argument('--target',required=True,help='NEW restore database; never the source schema')
    parser.add_argument('--mysql-bin',default=os.environ.get('CHARGE_MYSQL_BIN',r'C:\Program Files\MySQL\MySQL Server 8.4\bin'),help='Directory containing mysqldump.exe and mysql.exe')
    args=parser.parse_args()
    RESTORE=args.target
    BIN=Path(args.mysql_bin).resolve()
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,63}',RESTORE) or RESTORE==SOURCE:
        parser.error('Target must be a valid new, non-source database name')
    if not all((BIN/name).is_file() for name in ('mysqldump.exe','mysql.exe')):
        parser.error('mysql-bin must contain mysqldump.exe and mysql.exe')
    if not os.environ.get('CHARGE_ADMIN_DSN'):
        parser.error('Explicit CHARGE_ADMIN_DSN with administrative permissions is required')
    url = make_url(os.environ['CHARGE_ADMIN_DSN'])
    if url.database != SOURCE or url.host not in ('localhost', '127.0.0.1') or url.port != 3307:
        raise RuntimeError('Backup validation is restricted to the dedicated local course database')
    out = CURRENT_RECORDS / '备份恢复' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out.mkdir(parents=True, exist_ok=True)
    dump = out / 'charge_course_20261114.sql'
    restore_sql = out / '恢复专用.sql'
    source_engine = create_engine(url)
    server_engine = create_engine(url.set(database=None))
    with server_engine.connect() as server:
        if server.exec_driver_sql('SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (RESTORE,)).scalar():
            raise RuntimeError('Restore schema already exists; refusing to overwrite it')
        server_state = dict(server.exec_driver_sql('SELECT VERSION() version,@@port port,@@log_bin log_bin,@@binlog_format binlog_format').mappings().one())
    started = time.perf_counter()
    cli = ['--no-defaults', '--protocol=tcp', '--host=' + url.host, '--port=' + str(url.port),
           '--user=' + url.username, '--default-character-set=utf8mb4']
    env = dict(os.environ, MYSQL_PWD=url.password)
    command = [str(BIN / 'mysqldump.exe'), *cli, '--single-transaction', '--routines', '--triggers',
               '--events', '--source-data=2', '--set-gtid-purged=OFF', '--no-tablespaces', '--hex-blob', '--tz-utc',
               '--result-file=' + str(dump), SOURCE]
    process = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=180)
    if process.returncode:
        raise RuntimeError('mysqldump returned a nonzero status; no raw diagnostics persisted')
    backup_seconds = round(time.perf_counter() - started, 3)
    before = inventory(source_engine)
    sql = dump.read_text(encoding='utf-8')
    coordinate = re.search(r"CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='([^']+)', SOURCE_LOG_POS=(\d+)", sql)
    if not coordinate:
        raise RuntimeError('Backup binlog coordinate is missing')
    restore_sql.write_text(rewrite_database_identifiers(sql, SOURCE, RESTORE), encoding='utf-8')
    restore_started = time.perf_counter()
    with server_engine.connect() as server:
        server.exec_driver_sql(f'CREATE DATABASE `{RESTORE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        previous = server.exec_driver_sql('SELECT @@GLOBAL.log_bin_trust_function_creators').scalar_one()
        try:
            if not previous:
                server.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=1')
            with restore_sql.open('rb') as source:
                process = subprocess.run([str(BIN / 'mysql.exe'), *cli, '--database=' + RESTORE],
                                         env=env, stdin=source, capture_output=True, timeout=180)
            if process.returncode:
                raise RuntimeError('restore returned a nonzero status; isolated target retained for inspection')
        finally:
            if not previous:
                server.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=0')
    restored_engine = create_engine(url.set(database=RESTORE))
    after = inventory(restored_engine)
    with restored_engine.connect() as db:
        wrong_views = list(db.exec_driver_sql('SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA=DATABASE() AND VIEW_DEFINITION LIKE %s', ('%`' + SOURCE + '`.%',)).scalars())
    report = {'checked_at': datetime.now().isoformat(timespec='seconds'), 'source': SOURCE, 'restore': RESTORE,
              'server': server_state, 'backup_file': dump.name, 'backup_bytes': dump.stat().st_size,
              'backup_sha256': hashlib.sha256(dump.read_bytes()).hexdigest(), 'backup_seconds': backup_seconds,
              'backup_binlog_file': coordinate[1], 'backup_binlog_position': int(coordinate[2]),
              'restore_and_validation_seconds': round(time.perf_counter() - restore_started, 3),
              'all_rows_and_objects_equal': before == after, 'views_referencing_source': wrong_views,
              'source_inventory': before, 'restore_inventory': after,
              'scope': 'Full logical backup and isolated full restore. Binlog point-in-time replay was not executed.'}
    (out / '恢复验证.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if before != after or wrong_views:
        raise RuntimeError('Restored data, objects, or view isolation did not match')
    print(json.dumps({k: v for k, v in report.items() if 'inventory' not in k}, ensure_ascii=False))


if __name__ == '__main__':
    main()
