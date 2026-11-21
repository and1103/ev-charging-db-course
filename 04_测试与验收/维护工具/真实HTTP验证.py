"""Actual local HTTP checks; cookies and demo credentials stay in memory."""

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
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = APP_ROOT
from verification_support import output_directory
from local_runtime import load_runtime


def main():
    load_runtime()
    base = 'http://127.0.0.1:5000'
    client = build_opener(HTTPCookieProcessor(CookieJar()))
    checks = []

    def request(label, path, expected=200, method='GET', body=None, token=None, origin=None):
        headers = {'X-UI-Request': '1'}
        if token:
            headers['X-CSRF-Token'] = token
        if origin:
            headers['Origin'] = origin
        if body is not None:
            body = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        try:
            response = client.open(Request(base+path, data=body, method=method, headers=headers), timeout=12)
        except HTTPError as response_error:
            response = response_error
        raw = response.read()
        status = response.status
        checks.append({'check': label, 'method': method, 'path': path,
                       'expected_status': expected, 'actual_status': status, 'passed': status == expected})
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode('utf-8')

    request('页面及样式可访问', '/ui/login')
    request('匿名业务拒绝', '/ui/api/orders', 401)
    anonymous = request('获取匿名会话', '/ui/session')
    token = anonymous['csrf_token']
    request('缺失CSRF拒绝', '/auth/login', 403, 'POST', {'login': 'driver1', 'password': 'invalid'})
    request('跨源写入拒绝', '/auth/login', 403, 'POST', {'login': 'driver1', 'password': 'invalid'}, token, 'https://invalid.example')
    request('合成车主登录', '/auth/login', 200, 'POST',
            {'login': 'driver1', 'password': os.environ['CHARGE_DEMO_PASSWORD']}, token, base)
    authenticated = request('恢复真实身份', '/ui/session')
    checks.append({'check': '登录后令牌轮换', 'passed': authenticated['authenticated'] and authenticated['csrf_token'] != token})
    token = authenticated['csrf_token']
    html = request('工作台HTML', '/ui/')
    checks.append({'check': '工作台模板包含真实入口', 'passed': isinstance(html, str) and 'js/app.js' in html and 'view-content' in html})
    request('角色总览', '/ui/api/dashboard')
    request('本人订单列表', '/ui/api/orders')
    detail = request('本人账单及原始读数', '/ui/api/orders/1')
    checks.append({'check': '固定订单金额独立核对',
                   'passed': str(detail['order']['gross']) == '11.40' and str(detail['order']['discount']) == '2.00'
                   and str(detail['order']['received']) == '9.40' and str(detail['order']['outstanding']) == '0.00'
                   and len(detail['samples']) >= 3})
    request('他人订单拒绝', '/ui/api/orders/2', 404)
    request('管理用户接口拒绝', '/ui/api/users', 403)
    request('注销', '/auth/logout', 204, 'POST', token=token, origin=base)
    request('注销后拒绝', '/ui/api/orders', 401)
    result = {'checked_at': datetime.now().isoformat(timespec='seconds'),
              'transport': 'Actual local HTTP, in-memory cookies; no browser automation.',
              'passed': all(x['passed'] for x in checks), 'checks': checks}
    (output_directory() / '真实HTTP验证结果.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'test_count':len(checks)},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
