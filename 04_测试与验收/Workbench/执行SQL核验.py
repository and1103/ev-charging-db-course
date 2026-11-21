"""Verify Workbench SQL through SQLAlchemy; never launch a MySQL console."""

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

from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = APP_ROOT
from verification_support import output_directory
from local_runtime import load_runtime
load_runtime()
from deploy import mysql_engine,sql_statements


def main():
    here=Path(__file__).resolve().parent
    output=output_directory()
    report={'checked_at':datetime.now().isoformat(timespec='seconds'),'execution':'SQLAlchemy real MySQL connection; separate from Workbench GUI execution','scripts':[]}
    with mysql_engine('CHARGE_DATABASE_URL').connect() as db:
        report['database']=db.exec_driver_sql('SELECT DATABASE()').scalar_one()
        if report['database']!='charge_course_20261114':
            raise RuntimeError('Dedicated course database required')
        tables=list(db.exec_driver_sql("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'").scalars())
        before={t:db.exec_driver_sql(f'SELECT COUNT(*) FROM `{t}`').scalar_one() for t in tables}
        db.rollback()
        for name in ['Workbench验证.sql','Workbench事务验证.sql']:
            outcome={'file':name,'passed':False,'result_grids':[]}
            try:
                for number,statement in enumerate(sql_statements((here/name).read_text(encoding='utf-8')),1):
                    result=db.exec_driver_sql(statement)
                    if result.returns_rows:
                        rows=[dict(x) for x in result.mappings()]
                        outcome['result_grids'].append({'statement':number,'rows':rows})
                        for row in rows:
                            for column,value in row.items():
                                if column in {'判断','功率约束'} and isinstance(value,str) and value.startswith('FAIL'):
                                    raise RuntimeError(f'{name} statement {number}: {column} failed')
                        if not rows and 'AS 判断' in statement:
                            raise RuntimeError(f'{name} statement {number}: assertion result was empty')
                db.rollback()
                outcome['passed']=True
            except Exception as error:
                db.rollback()
                outcome['error_type']=type(error).__name__
                # Error text can contain DBAPI parameters. Save only the server diagnostic.
                original=getattr(error,'orig',None)
                outcome['error']='SQL assertion or database error; parameters omitted.'
                raise
            finally:
                report['scripts'].append(outcome)
                (output/'SQL实际核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print(name,'PASS',len(outcome['result_grids']),'result grids')
        after={t:db.exec_driver_sql(f'SELECT COUNT(*) FROM `{t}`').scalar_one() for t in tables}
        report['business_row_counts_unchanged']=before==after
        report['passed']=all(x['passed'] for x in report['scripts']) and before==after
        (output/'SQL实际核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        if not report['passed']:
            raise RuntimeError('Business row counts changed after rolled-back demonstration')
        print('All business row counts unchanged after validation.')


if __name__=='__main__':
    main()
