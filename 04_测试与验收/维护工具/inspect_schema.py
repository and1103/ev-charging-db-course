"""Export actual deployed MySQL metadata without credentials or personal data."""

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
from datetime import datetime
import json
import os
import re
from verification_support import output_directory
from deploy import MIGRATIONS, migration_path, mysql_engine, sql_statements


def declared_objects():
    """Read the canonical DDL names; these are source declarations, not DB observations."""
    names = {kind: set() for kind in ('TABLE', 'VIEW', 'PROCEDURE', 'FUNCTION', 'TRIGGER')}
    for migration in MIGRATIONS:
        for statement in sql_statements(migration_path(migration).read_text(encoding='utf-8')):
            match = re.match(r'^\s*CREATE\s+(TABLE|VIEW|PROCEDURE|FUNCTION|TRIGGER)\s+`?(\w+)`?', statement, re.I)
            if match:
                names[match[1].upper()].add(match[2])
    return {kind: sorted(values) for kind, values in names.items()}


def main():
    parser = argparse.ArgumentParser(description='Read-only schema checks; default scope excludes full trigger verification.')
    parser.add_argument('--admin', action='store_true', help='Require explicitly supplied CHARGE_ADMIN_DSN and verify complete trigger names')
    args = parser.parse_args()
    supplied_admin = os.environ.get('CHARGE_ADMIN_DSN')
    if args.admin and not supplied_admin:
        parser.error('--admin requires explicitly supplied CHARGE_ADMIN_DSN')
    from local_runtime import load_runtime
    load_runtime()
    if args.admin:
        # Do not silently replace an absent admin connection with the runtime's application fallback.
        os.environ['CHARGE_ADMIN_DSN'] = supplied_admin
    target = output_directory()
    declared = declared_objects()
    with mysql_engine('CHARGE_ADMIN_DSN' if args.admin else 'CHARGE_DATABASE_URL').connect() as db:
        tables=[x[0] for x in db.exec_driver_sql("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' AND TABLE_NAME<>'charge_migration' ORDER BY TABLE_NAME")]
        columns=[dict(x) for x in db.exec_driver_sql("SELECT c.TABLE_NAME,c.COLUMN_NAME,c.COLUMN_TYPE,c.IS_NULLABLE,c.COLUMN_DEFAULT,c.COLUMN_KEY,c.EXTRA FROM information_schema.COLUMNS c JOIN information_schema.TABLES t ON t.TABLE_SCHEMA=c.TABLE_SCHEMA AND t.TABLE_NAME=c.TABLE_NAME WHERE c.TABLE_SCHEMA=DATABASE() AND t.TABLE_TYPE='BASE TABLE' AND c.TABLE_NAME<>'charge_migration' ORDER BY c.TABLE_NAME,c.ORDINAL_POSITION").mappings()]
        fks=[dict(x) for x in db.exec_driver_sql('SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME,CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION').mappings()]
        counts={t:db.exec_driver_sql('SELECT COUNT(*) FROM `' + t.replace('`','``') + '`').scalar_one() for t in tables}
        visible_triggers=[x[0] for x in db.exec_driver_sql('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() ORDER BY TRIGGER_NAME')]
        result={'checked_at':datetime.now().isoformat(timespec='seconds'),
                'version':db.exec_driver_sql('SELECT VERSION()').scalar_one(),'database':db.exec_driver_sql('SELECT DATABASE()').scalar_one(),
                'scope':'administrator_complete_metadata' if args.admin else 'application_visible_core_metadata',
                'tables':tables,'columns':columns,'foreign_keys':fks,'row_counts':counts,
                'routines':[dict(x) for x in db.exec_driver_sql('SELECT ROUTINE_NAME,ROUTINE_TYPE FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE() ORDER BY ROUTINE_TYPE,ROUTINE_NAME').mappings()],
                'views':[x[0] for x in db.exec_driver_sql('SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME')]}
    procedures=sorted(x['ROUTINE_NAME'] for x in result['routines'] if x['ROUTINE_TYPE']=='PROCEDURE')
    functions=sorted(x['ROUTINE_NAME'] for x in result['routines'] if x['ROUTINE_TYPE']=='FUNCTION')
    result['checks']={
        'business_tables':{'expected':44,'actual':len(tables),'passed':len(tables)==44 and sorted(tables)==declared['TABLE']},
        'business_base_columns':{'expected':320,'actual':len(columns),'passed':len(columns)==320 and {x['TABLE_NAME'] for x in columns}==set(tables)},
        'views':{'expected':19,'actual':len(result['views']),'passed':len(result['views'])==19 and sorted(result['views'])==declared['VIEW']},
        'procedures':{'expected':25,'actual':len(procedures),'passed':len(procedures)==25 and procedures==declared['PROCEDURE']},
        'functions':{'expected':15,'actual':len(functions),'passed':len(functions)==15 and functions==declared['FUNCTION']},
        'minimum_rows':{'expected_at_least':20,'actual_minimum':min(counts.values()) if counts else None,'passed':bool(counts) and all(n>=20 for n in counts.values())},
        'ddl_trigger_declarations':{'expected':54,'actual':len(declared['TRIGGER']),'passed':len(declared['TRIGGER'])==54,'source':'canonical DDL only; not a live database trigger check'},
    }
    matched=visible_triggers==declared['TRIGGER']
    trigger_status=('verified' if matched else 'failed') if args.admin else 'not_verified'
    result['declared_triggers']=declared['TRIGGER']
    # An empty visible list under a restricted account does not mean the DB has zero triggers.
    result['triggers']=visible_triggers if args.admin else None
    result['trigger_metadata']={'status':trigger_status,'visible_triggers':visible_triggers,
                                'visible_count':len(visible_triggers),'ddl_declared_count':len(declared['TRIGGER']),
                                'reason':'Explicit administrator observation compared with canonical DDL.' if args.admin else 'Application metadata visibility is insufficient for a complete trigger inventory; no live trigger pass is claimed.',
                                'missing_from_visible':sorted(set(declared['TRIGGER'])-set(visible_triggers)) if args.admin else None,
                                'unexpected_visible':sorted(set(visible_triggers)-set(declared['TRIGGER'])) if args.admin else None}
    result['core_checks_passed']=all(check['passed'] for check in result['checks'].values())
    result['complete_metadata_verified']=result['core_checks_passed'] and args.admin and matched
    result['passed']=result['core_checks_passed'] and (not args.admin or matched)
    (target/'数据库结构.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'tables':len(tables),'business_columns':len(columns),
                      'views':len(result['views']),'procedures':len(procedures),'functions':len(functions),
                      'routines':len(result['routines']),'triggers':len(visible_triggers) if args.admin else 'not_verified',
                      'ddl_declared_triggers':len(declared['TRIGGER']),
                      'complete_metadata_verified':result['complete_metadata_verified'],
                      'minimum_rows':min(counts.values()) if counts else None},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
