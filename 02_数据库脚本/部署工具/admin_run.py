"""Run an explicit administrator task with a password prompted only in memory."""
from pathlib import Path
import sys
for _base in Path(__file__).resolve().parents:
    if (_base/'01_平台工程/project_paths.py').is_file():
        sys.path.insert(0,str(_base/'01_平台工程'))
        break
else:
    raise RuntimeError('Cannot locate the second edition')
from project_paths import SQL_ROOT, TEST_ROOT, BACKUP_ROOT

import argparse
from getpass import getpass
import os
import runpy


def main():
    parser=argparse.ArgumentParser(description='Explicit DBA task; password is prompted, not stored in a file or command history.')
    parser.add_argument('task',choices=['init','schema','sql-regression','explain','clean-build','backup-restore'])
    args,extra=parser.parse_known_args()
    from local_runtime import load_runtime, SCHEMA
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import URL
    load_runtime()
    if not os.environ.get('CHARGE_DEMO_PASSWORD'):
        parser.error('Configure this Windows user first; runtime keys and demo credentials are required.')
    previous=os.environ.get('CHARGE_ADMIN_DSN')
    url=URL.create('mysql+pymysql',username='root',password=getpass('Local MySQL root password (not saved): '),
                   host='127.0.0.1',port=3307,database=SCHEMA,query={'charset':'utf8mb4'})
    os.environ['CHARGE_ADMIN_DSN']=url.render_as_string(hide_password=False)
    try:
        if args.task=='init':
            if extra:
                parser.error('init does not accept extra options')
            engine=create_engine(url)
            try:
                with engine.connect() as db:
                    count=db.execute(text('SELECT '
                        '(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE())+'
                        '(SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema=DATABASE())+'
                        '(SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE())+'
                        '(SELECT COUNT(*) FROM information_schema.events WHERE event_schema=DATABASE())')).scalar_one()
                    if count:
                        raise RuntimeError('init requires the newly created empty course schema; existing objects are never reset.')
            finally:
                engine.dispose()
            jobs=[(SQL_ROOT/'部署工具/deploy_local.py',['--demo']),
                  (SQL_ROOT/'初始化与样例/seed_extended.py',[]),
                  (SQL_ROOT/'初始化与样例/seed_fleet.py',[])]
        else:
            mapping={'schema':(TEST_ROOT/'维护工具/inspect_schema.py',['--admin']),
                     'sql-regression':(TEST_ROOT/'run_checks.py',['sql-regression']),
                     'explain':(TEST_ROOT/'查询与并发/check_queries.py',['--explain']),
                     'clean-build':(SQL_ROOT/'部署工具/verify_clean_build.py',[]),
                     'backup-restore':(BACKUP_ROOT/'工具/backup_validate.py',[])}
            script,defaults=mapping[args.task]
            jobs=[(script,defaults+extra)]
        for script,arguments in jobs:
            sys.argv=[str(script),*arguments]
            runpy.run_path(str(script),run_name='__main__')
        return 0
    except Exception as error:
        # Raw DBAPI text may include connection strings; keep the failure controlled.
        print('Administrator task stopped ('+type(error).__name__+'). Inspect the task requirements and recorded sanitized results.',file=sys.stderr)
        return 1
    finally:
        if previous is None:
            os.environ.pop('CHARGE_ADMIN_DSN',None)
        else:
            os.environ['CHARGE_ADMIN_DSN']=previous


if __name__=='__main__':
    raise SystemExit(main())
