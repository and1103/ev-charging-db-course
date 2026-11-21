"""Capture bounded synthetic-course API fixtures with Flask's in-process client.

No browser or HTTP client is launched. All calls are GET. Runtime secrets,
password hashes, encrypted identity fields and real CSRF tokens are not saved.
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

from datetime import datetime
from pathlib import Path
import json
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = APP_ROOT
from verification_support import output_directory
from local_runtime import load_runtime
load_runtime()
from app import app, engine


def canonical(path):
    parsed = urlsplit(path)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return parsed.path + ('?' + query if query else '')


def assert_no_secrets(value):
    if isinstance(value, dict):
        assert not {'password', 'password_hash', 'phone_cipher', 'plate_cipher', 'CHARGE_DATABASE_URL'} & value.keys()
        for item in value.values():
            assert_no_secrets(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_secrets(item)


result = {'captured_at': datetime.now().isoformat(timespec='seconds'),
          'scope': 'In-process Flask GET responses from the synthetic local course schema; not browser or HTTP verification',
          'roles': {}}
anonymous = app.test_client()
anonymous_session = anonymous.get('/ui/session').get_json()
anonymous_session['csrf_token'] = 'local-code-test-placeholder-not-a-real-token'
login_html = anonymous.get('/ui/login')
assert login_html.status_code == 200
result['anonymous'] = {'responses': {'/ui/session': {'status': 200, 'body': anonymous_session}},
                       'login_html': login_html.get_data(as_text=True)}
with engine.connect() as db:
    actors = {}
    for row in db.exec_driver_sql('SELECT id,login,role,station_id,operator_id FROM account ORDER BY id').mappings():
        actors.setdefault(row['role'], dict(row))

for role, actor in actors.items():
    client = app.test_client()
    with client.session_transaction() as cookie:
        cookie['user'] = actor['id']
    saved = {'user': actor, 'responses': {}, 'cases': []}
    workspace_html = client.get('/ui/')
    assert workspace_html.status_code == 200
    saved['workspace_html'] = workspace_html.get_data(as_text=True)
    result['roles'][role] = saved

    def get(path):
        key = canonical(path)
        if key not in saved['responses']:
            response = client.get(path)
            assert response.status_code == 200, (role, path, response.status_code)
            body = response.get_json()
            if path == '/ui/session':
                body['csrf_token'] = 'local-code-test-placeholder-not-a-real-token'
            assert_no_secrets(body)
            saved['responses'][key] = {'status': response.status_code, 'body': body}
        return saved['responses'][key]['body']

    def case(export, params='', label=None):
        saved['cases'].append({'export': export, 'params': params, 'label': label or export,
                               'source_mode': 'actual_api_snapshot'})

    session = get('/ui/session')
    lookups = get('/ui/api/lookups')
    get('/ui/api/dashboard')
    if role in ('driver', 'admin'):
        stations = get('/stations?name=&offset=0')
        case('renderStations', label='场站列表')
        if stations:
            get(f"/stations/{stations[0]['id']}/guns")
            case('renderStations', f"id={stations[0]['id']}", '场站枪详情')
        get('/ui/api/campaigns')
        case('renderMembers', label='个人车辆钱包' if role == 'driver' else '用户活动管理')
    if role == 'driver':
        get('/me')
        get('/queue')
        get('/ui/api/fleet-cards')
        case('renderQueue', label='本人排队')
    if role == 'admin':
        get('/ui/api/users?offset=0&name=')
        get('/ui/api/users?offset=50&name=')
        case('renderMembers', 'offset=50', '用户第二页')
        get('/ui/api/asset-requests')
        for table in ('operator', 'station', 'charger', 'connector'):
            get(f'/admin/assets/{table}?offset=0')
            case('renderFacilities', f'table={table}', f'设施档案-{table}')
        if lookups['stations']:
            get(f"/admin/stations/{lookups['stations'][0]['id']}/assets")
    if role in ('driver', 'fleet', 'admin', 'settlement'):
        orders = get('/ui/api/orders?offset=0&state=')
        get('/ui/api/orders?offset=0&state=paid')
        case('renderOrders', label='订单列表')
        case('renderOrders', 'state=paid', '已付订单筛选')
        selected = []
        if orders:
            selected.append(orders[0]['id'])
        paid = get('/ui/api/orders?offset=0&state=paid')
        if paid:
            selected.append(paid[0]['id'])
        for key in dict.fromkeys(selected):
            get(f'/ui/api/orders/{key}')
            case('renderOrders', f'id={key}', '订单证据详情')
    if role in ('admin', 'fleet'):
        fleets = get('/fleets')
        get('/ui/api/fleet-cards')
        case('renderFleet', label='车队与额度')
        for fleet in fleets[:2]:
            get(f"/fleets/{fleet['id']}/months")
        if len(fleets) > 1:
            case('renderFleet', f"id={fleets[1]['id']}", '第二车队月账单')
    if role != 'maintenance':
        case('renderTariffs', label='费率版本')
    if role in ('admin', 'maintenance'):
        alarms, works = get('/alarms'), get('/work')
        case('renderMonitor', label='告警工单列表')
        if alarms:
            get(f"/alarms/{alarms[0]['id']}")
            case('renderMonitor', f"alarm={alarms[0]['id']}", '告警详情')
        if works:
            get(f"/work/{works[0]['id']}")
            case('renderMonitor', f"work={works[0]['id']}", '维修工单详情')
        if lookups['chargers']:
            get(f"/ui/api/telemetry?charger={lookups['chargers'][0]['id']}&limit=100")
    if role in ('admin', 'settlement', 'operator'):
        settlements = get('/settlements')
        case('renderSettlements', label='结算列表')
        if settlements:
            key = settlements[0]['id']
            get(f'/settlements/{key}')
            get(f'/ui/api/settlements/{key}/evidence')
            case('renderSettlements', f'id={key}', '结算完整证据')
    if role in ('admin', 'settlement'):
        requests = get('/ui/api/invoice-requests')
        case('renderInvoices', label='消费开票申请')
        records = requests if isinstance(requests, list) else requests.get('requests', [])
        if records:
            key = records[0]['order_id']
            get(f'/orders/{key}/invoices')
            case('renderInvoices', f'order={key}', '消费票据详情')
    if role == 'admin':
        get('/ui/api/orders?state=charging')
        case('renderDemo', label='管理员模拟控制表单')

target = output_directory() / 'api_fixtures.json'
target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'roles': len(result['roles']),
                  'render_cases': sum(len(v['cases']) for v in result['roles'].values()),
                  'responses': sum(len(v['responses']) for v in result['roles'].values()),
                  'file': target.name}, ensure_ascii=False))
