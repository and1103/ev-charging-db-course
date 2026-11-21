"""One entry for the integrated project's checks; administrator work is opt-in."""
from pathlib import Path
import sys
for _base in Path(__file__).resolve().parents:
    if (_base / '01_平台工程/project_paths.py').is_file():
        sys.path.insert(0, str(_base / '01_平台工程'))
        break
else:
    raise RuntimeError('Cannot locate integrated project')
from project_paths import APP_ROOT, PROJECT_ROOT, TEST_ROOT, CURRENT_RECORDS

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import shutil
import subprocess
import time

QUICK = ['unit', 'schema', 'queries', 'client-contract']
ALL = QUICK + ['api', 'workbench', 'http', 'dom']
GROUPS = ALL + ['sql-regression', 'legacy-gun']
BEIJING = timezone(timedelta(hours=8))


def sanitized(raw):
    """Persist outcomes, never raw SQL, parameters, credentials or tracebacks."""
    lines, types = [], set()
    for original in raw.splitlines():
        line = original.strip()
        match = re.match(r'^(test_\w+) \([^)]*\) \.\.\. (ok|FAIL|ERROR|skipped)\b', line)
        if match:
            lines.append(f'{match[1]} ... {match[2]}')
        elif re.fullmatch(r'(?:Ran \d+ tests? in [0-9.]+s|OK|FAILED \([^)]*\))', line):
            lines.append(line)
        elif line.startswith(('PASS ', 'FAIL ')):
            lines.append(line.split(' UNEXPECTED_', 1)[0][:160])
        else:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    summary = {k: value[k] for k in ('passed', 'test_count', 'case_count', 'pair_count', 'nonempty_pairs', 'empty_pairs', 'tables', 'views', 'routines', 'triggers', 'statements', 'result_grids') if k in value and isinstance(value[k], (bool, int, float, str))}
                    if summary:
                        lines.append(json.dumps(summary, ensure_ascii=False))
            except ValueError:
                pass
        exception = re.match(r'^(?:[\w.]+\.)?([A-Za-z_]\w*(?:Error|Exception))(?::|\s|$)', line)
        if exception:
            types.add(exception[1])
    if types:
        lines.append('exception_types=' + ','.join(sorted(types)))
    return '\n'.join(lines) + '\nRaw diagnostics and SQL parameters are not persisted.\n'


def jobs(group):
    py = lambda p: [sys.executable, str(p)]
    if group == 'unit':
        return [('launcher', py(TEST_ROOT / '自动化测试/test_web_launcher.py')),
                ('runtime-paths', py(TEST_ROOT / '自动化测试/test_runtime_paths.py')),
                ('admin-dispatch', py(TEST_ROOT / '自动化测试/test_admin_tasks.py'))]
    if group == 'api':
        return [(Path(p).stem, py(TEST_ROOT / '自动化测试' / p)) for p in
                ['test_backend_api.py', 'test_wallet_progress.py', 'test_funding_concurrency.py', 'test_alarm_api.py', 'test_web_ui.py']]
    if group == 'schema':
        return [('schema', py(TEST_ROOT / '维护工具/inspect_schema.py')),
                ('dictionary', py(TEST_ROOT / '维护工具/dictionary.py'))]
    single = {'schema': '维护工具/inspect_schema.py', 'queries': '查询与并发/check_queries.py',
              'workbench': 'Workbench/执行SQL核验.py', 'http': '维护工具/真实HTTP验证.py',
              'legacy-gun': '查询与并发/concurrency.py'}
    if group in single:
        return [(group, py(TEST_ROOT / single[group]))]
    if group == 'client-contract':
        return [('client-contract', ['node', str(TEST_ROOT / '维护工具/operations_contract_check.mjs')])]
    if group == 'dom':
        return [('capture', py(TEST_ROOT / 'DOM模块测试/capture_api.py')),
                ('render', ['node', str(TEST_ROOT / 'DOM模块测试/render_modules.mjs')])]
    if group == 'sql-regression':
        sqls = [TEST_ROOT / 'SQL回归' / p for p in ['B_regression_funding.sql', 'E_regression_settlement.sql', 'C_smoke.sql', 'C_regression_monitor.sql']]
        sqls += [TEST_ROOT / 'SQL回归' / p for p in ['regression_tariff_boundaries.sql', 'regression_alarm_scope.sql']]
        return [(p.stem, py(TEST_ROOT / '维护工具/run_sql.py') + [str(p)]) for p in sqls]
    raise ValueError('Unknown group')


def main():
    parser = argparse.ArgumentParser(description='第二版统一验证；默认quick，不启动网页')
    parser.add_argument('groups', nargs='*', help='quick/all/unit/api/queries/schema/workbench/http/dom/client-contract/sql-regression/legacy-gun')
    parser.add_argument('--start-http', action='store_true', help='HTTP测试需要时临时启动本版服务，并在finally关闭')
    args = parser.parse_args()
    selected = []
    for group in args.groups or ['quick']:
        expanded = QUICK if group == 'quick' else ALL if group == 'all' else [group]
        for item in expanded:
            if item not in GROUPS:
                parser.error('Unknown group: ' + item)
            if item not in selected:
                selected.append(item)
    explicit_admin = os.environ.get('CHARGE_ADMIN_DSN')
    started = datetime.now(BEIJING)
    output = CURRENT_RECORDS / '验证结果' / started.strftime('%Y%m%d-%H%M%S-%f')
    output.mkdir(parents=True, exist_ok=False)
    report = {'started_at': started.isoformat(timespec='seconds'), 'edition': '数据库设计第二版',
              'groups': {}, 'passed': False,
              'scope': 'Executed results only. Historical evidence is not reused as a current pass.',
              'side_effects': ['api/legacy-gun can refresh seeded charger 1 and retain cancelled synthetic orders.',
                               'Most other API fixtures are private UUID rows removed during cleanup.',
                               'workbench rolls back its private workflow; AUTO_INCREMENT gaps can remain.',
                               'sql-regression creates/drops temporary routines and requires an explicitly supplied administrator.',
                               'dom is code-only rendering, not actual browser or end-to-end UI acceptance.']}
    def save():
        (output / '结果.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (output.parent / '最近一次.json').write_text(json.dumps({'report': str((output / '结果.json').relative_to(PROJECT_ROOT)), 'passed': report['passed']}, ensure_ascii=False, indent=2), encoding='utf-8')
    runtime_loaded = False
    save()
    for group in selected:
        group_out = output / group
        group_out.mkdir()
        result = {'passed': False, 'jobs': []}
        report['groups'][group] = result
        temporary_http = False
        try:
            if group not in ('unit', 'client-contract') and not runtime_loaded:
                from local_runtime import load_runtime
                load_runtime()
                runtime_loaded = True
            env = dict(os.environ, PYTHONIOENCODING='utf-8', CHARGE_TEST_OUTPUT=str(group_out))
            if group != 'sql-regression' and os.environ.get('CHARGE_DATABASE_URL'):
                env['CHARGE_ADMIN_DSN'] = os.environ['CHARGE_DATABASE_URL']
            if group == 'sql-regression':
                if not explicit_admin:
                    raise RuntimeError('Explicit CHARGE_ADMIN_DSN is required for sql-regression')
                from sqlalchemy.engine import make_url
                url = make_url(explicit_admin)
                if url.host not in ('127.0.0.1', 'localhost') or url.port != 3307 or url.database != 'charge_course_20261114':
                    raise RuntimeError('Administrator target must be the dedicated local course schema')
                env['CHARGE_ADMIN_DSN'] = explicit_admin
            if group in ('dom', 'client-contract') and not shutil.which('node'):
                raise RuntimeError('Node.js is required for this developer check')
            if group == 'dom' and not (TEST_ROOT / 'DOM模块测试/node_modules/jsdom/package.json').is_file():
                raise RuntimeError('Install DOM developer dependencies first: npm ci --prefix 04_测试与验收/DOM模块测试')
            if group == 'http':
                import web_launcher
                if not web_launcher.correct_service(web_launcher.health()):
                    if web_launcher.port_in_use():
                        raise RuntimeError('Port 5000 belongs to another edition/service; refusing to reuse it')
                    if not args.start_http:
                        raise RuntimeError('Start this edition first, or use --start-http for a temporary service')
                    temporary_http = True
                    startup = subprocess.run([sys.executable, str(APP_ROOT / 'web_launcher.py'), '--no-browser'], cwd=APP_ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
                    if startup.returncode or not web_launcher.correct_service(web_launcher.health()):
                        raise RuntimeError('Temporary HTTP service did not become ready')
            for name, command in jobs(group):
                tick = time.perf_counter()
                run = subprocess.run(command, cwd=APP_ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
                raw = run.stdout + '\n' + run.stderr
                (group_out / (name + '.log')).write_text(sanitized(raw), encoding='utf-8')
                count = re.search(r'Ran (\d+) tests? in ', raw)
                entry = {'name': name, 'passed': run.returncode == 0, 'return_code': run.returncode,
                         'seconds': round(time.perf_counter()-tick, 3), 'log': str((group_out / (name + '.log')).relative_to(output))}
                if count:
                    entry['test_count'] = int(count[1])
                    entry['passed'] = entry['passed'] and re.search(r'^OK\s*$', raw, re.M) is not None
                result['jobs'].append(entry)
                print(group, name, 'PASS' if entry['passed'] else 'FAIL')
                save()
                if not entry['passed']:
                    break
            result['passed'] = bool(result['jobs']) and all(x['passed'] for x in result['jobs'])
        except Exception as error:
            result['error_type'] = type(error).__name__
            # Persist only our controlled preflight messages, never a DBAPI URL or SQL.
            result['error'] = str(error) if type(error) is RuntimeError else 'Details omitted; check local environment and permissions.'
            print(group, 'FAIL/INCOMPLETE', result['error_type'])
        finally:
            if temporary_http:
                try:
                    stopped = subprocess.run([sys.executable, '-X', 'utf8', str(APP_ROOT / 'web_launcher.py'), '--stop'], cwd=APP_ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
                    result['temporary_http_stop_succeeded'] = stopped.returncode == 0
                except Exception as error:
                    result['temporary_http_stop_succeeded'] = False
                    result['stop_error_type'] = type(error).__name__
                if not result['temporary_http_stop_succeeded']:
                    result['passed'] = False
            save()
    report['passed'] = all(report['groups'][g]['passed'] for g in selected)
    report['finished_at'] = datetime.now(BEIJING).isoformat(timespec='seconds')
    save()
    print('Evidence:', output / '结果.json')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
