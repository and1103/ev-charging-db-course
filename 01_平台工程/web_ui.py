"""Local browser workspace: scoped read models and same-origin browser protection.

The existing JSON endpoints remain the only implementations of pricing, payment,
repair and settlement rules. These read models expose only fields needed by the UI.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
import hmac
import json
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, abort, g, redirect, render_template, request, session


def register_web(app):
    if 'workspace' in app.blueprints:
        return
    # When app.py is run as __main__, importing app would create a second server.
    backend = app.view_functions['health'].__globals__
    tx, query, rows = (backend[k] for k in ('tx', 'query', 'rows'))
    data, number = (backend[k] for k in ('data', 'number'))
    order_progress = backend['order_progress']
    all_roles = ('admin', 'driver', 'maintenance', 'settlement', 'operator', 'fleet')
    staff = ('admin', 'settlement')
    bp = Blueprint('workspace', __name__)
    original_default = app.json.default

    def json_default(value):
        if isinstance(value, timedelta):
            seconds = int(value.total_seconds())
            sign = '-' if seconds < 0 else ''
            seconds = abs(seconds)
            return f'{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        return original_default(value)

    app.json.default = json_default

    @app.before_request
    def browser_write_protection():
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return
        is_browser = any(request.headers.get(k) for k in ('Origin', 'Sec-Fetch-Site', 'X-UI-Request'))
        if not is_browser:
            return
        origin = request.headers.get('Origin')
        if origin:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                abort(403, '浏览器请求来源格式不正确')
            if parsed.scheme not in ('http', 'https') or parsed.netloc != request.host or parsed.scheme != request.scheme:
                abort(403, '浏览器请求来源不匹配，请从本平台页面提交')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            abort(403, '拒绝跨站写入请求')
        expected, supplied = session.get('ui_csrf'), request.headers.get('X-CSRF-Token', '')
        if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), supplied.encode()):
            abort(403, '页面令牌已失效，请刷新后重试')

    @app.after_request
    def browser_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if request.path.startswith('/ui/') or request.path in ('/me', '/auth/login', '/auth/logout'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.get('/')
    def home():
        return redirect('/ui/')

    @bp.get('/ui/')
    def workspace():
        if 'user' not in session:
            return redirect('/ui/login')
        return render_template('workspace.html')

    @bp.get('/ui/login')
    def login_page():
        return render_template('login.html')

    @bp.get('/ui/session')
    @tx()
    def browser_session():
        user = None
        if 'user' in session:
            result = rows('SELECT id,login,role,station_id,operator_id FROM account WHERE id=:id', id=session['user'])
            user = result[0] if result else None
            if not user:
                session.pop('user', None)
        if 'ui_csrf' not in session:
            session['ui_csrf'] = secrets.token_urlsafe(32)
        return {'authenticated': bool(user), 'user': user, 'csrf_token': session['ui_csrf'],
                'server_time': query('SELECT SYSDATE(6)').scalar_one()}

    def order_predicate(alias='o'):
        role = g.actor['role']
        if role in staff:
            return 'true'
        if role == 'fleet':
            return f'EXISTS(SELECT 1 FROM fleet_card fc JOIN fleet f ON f.id=fc.fleet_id WHERE fc.id={alias}.fleet_card_id AND f.manager_id=:uid)'
        return f'{alias}.account_id=:uid'

    def order_parameters():
        return {'uid': g.actor['id']}

    def permitted_settlement(key):
        result = rows('SELECT * FROM v_invoice_balance WHERE id=:id AND (:staff OR operator_id=:operator)',
                      id=key, staff=g.actor['role'] in staff, operator=g.actor['operator_id'])
        if not result:
            abort(404)
        return result[0]

    def cards():
        return rows('SELECT fc.*,f.name fleet_name,f.manager_id,a.login driver_login,v.model,v.plate_mask '
                    'FROM fleet_card fc JOIN fleet f ON f.id=fc.fleet_id JOIN account a ON a.id=fc.driver_id '
                    'JOIN vehicle v ON v.id=fc.vehicle_id '
                    'WHERE (:admin OR (:driver AND fc.driver_id=:uid) OR (:manager AND f.manager_id=:uid)) ORDER BY fc.id',
                    admin=g.actor['role'] == 'admin', driver=g.actor['role'] == 'driver',
                    manager=g.actor['role'] == 'fleet', uid=g.actor['id'])

    def campaign_list():
        return rows('SELECT c.*,COALESCE(v.issued,0) issued,COALESCE(v.redeemed,0) redeemed,co.id coupon_id, '
                    'co.id IS NOT NULL claimed, '
                    '(co.id IS NULL AND NOW()>=c.starts AND NOW()<c.expires AND COALESCE(v.issued,0)<c.stock '
                    'AND (c.tier IS NULL OR c.tier=a.tier)) claimable, '
                    "CASE WHEN co.id IS NOT NULL THEN '已领取' WHEN NOW()<c.starts THEN '尚未开始' "
                    "WHEN NOW()>=c.expires THEN '活动已结束' WHEN COALESCE(v.issued,0)>=c.stock THEN '已领完' "
                    "WHEN c.tier IS NOT NULL AND c.tier<>a.tier THEN '会员等级不符' ELSE '可领取' END reason "
                    'FROM campaign c JOIN account a ON a.id=:uid LEFT JOIN v_campaign_stats v ON v.id=c.id '
                    'LEFT JOIN coupon co ON co.campaign_id=c.id AND co.account_id=:uid ORDER BY c.id DESC LIMIT 100', uid=g.actor['id'])

    @bp.get('/ui/api/lookups')
    @tx(*all_roles)
    def lookups():
        role, uid = g.actor['role'], g.actor['id']
        result = {name: [] for name in ('stations', 'operators', 'chargers', 'connectors', 'vehicles',
                                       'users', 'technicians', 'fleets', 'campaigns', 'tariffs', 'alarm_rules')}
        scope = '(:broad OR (:tech AND s.id=:station) OR (:operator AND s.operator_id=:operator_id))'
        params = {'broad': role not in ('maintenance', 'operator'), 'tech': role == 'maintenance',
                  'station': g.actor['station_id'], 'operator': role == 'operator', 'operator_id': g.actor['operator_id']}
        result['stations'] = rows('SELECT s.* FROM station s WHERE ' + scope + ' ORDER BY s.id LIMIT 500', **params)
        result['chargers'] = rows('SELECT c.* FROM charger c JOIN station s ON s.id=c.station_id WHERE ' + scope + ' ORDER BY c.id LIMIT 1000', **params)
        result['connectors'] = rows('SELECT g.*,c.station_id FROM connector g JOIN charger c ON c.id=g.charger_id '
                                    'JOIN station s ON s.id=c.station_id WHERE ' + scope + ' ORDER BY g.id LIMIT 2000', **params)
        if role in ('admin', 'settlement', 'operator'):
            result['operators'] = rows('SELECT id,name FROM operator WHERE (:all OR id=:id) ORDER BY id LIMIT 500',
                                       all=role in staff, id=g.actor['operator_id'])
        if role == 'admin':
            result['users'] = rows('SELECT id,login,role,phone_mask,verified,tier,station_id,operator_id FROM account ORDER BY id LIMIT 500')
            result['vehicles'] = rows('SELECT v.id,v.model,v.plate_mask,v.capacity_kwh,v.max_kw,v.supports_dc,v.interface,'
                                      'b.account_id,b.account_id owner_id,a.login FROM vehicle v LEFT JOIN vehicle_binding b '
                                      'ON b.vehicle_id=v.id AND b.binding_end IS NULL LEFT JOIN account a ON a.id=b.account_id ORDER BY v.id LIMIT 500')
        elif role in ('driver', 'fleet'):
            ownership = 'b.account_id=:uid' if role == 'driver' else 'EXISTS(SELECT 1 FROM fleet_card fc JOIN fleet f ON f.id=fc.fleet_id WHERE fc.vehicle_id=v.id AND f.manager_id=:uid)'
            result['vehicles'] = rows('SELECT DISTINCT v.id,v.model,v.plate_mask,v.capacity_kwh,v.max_kw,v.supports_dc,v.interface,'
                                      'b.account_id,b.account_id owner_id,a.login FROM vehicle v JOIN vehicle_binding b '
                                      'ON b.vehicle_id=v.id AND b.binding_end IS NULL JOIN account a ON a.id=b.account_id WHERE ' + ownership + ' ORDER BY v.id LIMIT 500', uid=uid)
            result['users'] = rows('SELECT a.id,a.login,a.role,a.verified FROM account a WHERE a.id=:uid OR '
                                   '(:manager AND EXISTS(SELECT 1 FROM fleet_card fc JOIN fleet f ON f.id=fc.fleet_id WHERE fc.driver_id=a.id AND f.manager_id=:uid)) ORDER BY a.id LIMIT 500',
                                   uid=uid, manager=role == 'fleet')
        if role in ('admin', 'maintenance'):
            result['technicians'] = rows("SELECT id,login,station_id FROM account WHERE role='maintenance' AND (:admin OR id=:uid) ORDER BY id LIMIT 500", admin=role == 'admin', uid=uid)
        if role in ('admin', 'fleet'):
            result['fleets'] = rows('SELECT id,name,manager_id FROM fleet WHERE (:admin OR manager_id=:uid) ORDER BY id LIMIT 500', admin=role == 'admin', uid=uid)
        if role in ('admin', 'driver'):
            result['campaigns'] = campaign_list()
        if role == 'admin':
            result['alarm_rules'] = rows('SELECT code,severity,response_minutes FROM alarm_rule ORDER BY code')
        if role not in ('maintenance',):
            result['tariffs'] = rows('SELECT t.* FROM tariff t JOIN station s ON s.id=t.station_id WHERE ' + scope +
                                      ' AND (:admin OR t.fleet_id IS NULL OR EXISTS(SELECT 1 FROM fleet f LEFT JOIN fleet_card fc ON fc.fleet_id=f.id '
                                      'WHERE f.id=t.fleet_id AND (f.manager_id=:uid OR fc.driver_id=:uid))) ORDER BY t.id DESC LIMIT 100',
                                      **params, admin=role == 'admin', uid=uid)
            for tariff in result['tariffs']:
                tariff['bands'] = rows('SELECT * FROM tariff_band WHERE tariff_id=:id ORDER BY minute_from', id=tariff['id'])
        return result

    @bp.get('/ui/api/dashboard')
    @tx(*all_roles)
    def dashboard():
        role, uid = g.actor['role'], g.actor['id']
        result = {'role': role, 'metrics': [], 'recent_orders': [], 'recent_alarms': [], 'recent_settlements': [],
                  'server_time': query('SELECT SYSDATE(6)').scalar_one()}
        def metric(label, value, hint=''):
            result['metrics'].append({'label': label, 'value': value, 'hint': hint})
        if role == 'driver':
            result['wallet'] = rows('SELECT balance,reserved_balance,balance-reserved_balance available_balance FROM account WHERE id=:id', id=uid)[0]
            metric('钱包可用', result['wallet']['available_balance'], '元 · 扣除冻结额度')
            metric('进行中订单', query("SELECT COUNT(*) FROM charge_order WHERE account_id=:uid AND state IN ('starting','charging','finishing','review')", uid=uid).scalar_one())
            metric('可用优惠券', query('SELECT COUNT(*) FROM v_unused_coupon WHERE account_id=:uid', uid=uid).scalar_one())
            metric('排队中', query("SELECT COUNT(*) FROM queue_entry WHERE account_id=:uid AND state IN ('waiting','called')", uid=uid).scalar_one())
        elif role == 'admin':
            metric('运营场站', query('SELECT COUNT(*) FROM station WHERE enabled').scalar_one(), '已启用')
            metric('当前可用枪', query('SELECT COALESCE(SUM(available),0) FROM v_station_availability').scalar_one(), '心跳与营业状态实时判定')
            metric('活动告警', query('SELECT COUNT(*) FROM alarm WHERE restored_at IS NULL').scalar_one())
            metric('待复核订单', query("SELECT COUNT(*) FROM charge_order WHERE state='review'").scalar_one())
        elif role == 'maintenance':
            metric('待处理工单', query('SELECT COUNT(*) FROM work_order WHERE technician_id=:uid AND closed_at IS NULL', uid=uid).scalar_one(), '仅本人派单')
            metric('本站活动告警', query('SELECT COUNT(*) FROM alarm a JOIN charger c ON c.id=a.charger_id WHERE a.restored_at IS NULL AND c.station_id=:sid', sid=g.actor['station_id']).scalar_one())
            metric('已关闭工单', query('SELECT COUNT(*) FROM work_order WHERE technician_id=:uid AND closed_at IS NOT NULL', uid=uid).scalar_one())
        elif role == 'fleet':
            own_cards = cards()
            metric('企业充电卡', len(own_cards))
            metric('冻结额度', sum((x['reserved_amount'] for x in own_cards), Decimal(0)), '元')
            metric('待付订单', query('SELECT COUNT(*) FROM v_order_balance o WHERE ' + order_predicate() + ' AND o.outstanding>0', uid=uid).scalar_one())
        else:
            totals = rows('SELECT COUNT(*) bills,COALESCE(SUM(due),0) due,COALESCE(SUM(state=\'draft\'),0) drafts FROM v_settlement WHERE (:staff OR operator_id=:oid)', staff=role in staff, oid=g.actor['operator_id'])[0]
            metric('结算账单', totals['bills'])
            metric('账单应结合计', totals['due'], '元 · 当前可见全部账期')
            metric('待确认账单', totals['drafts'])
            if role == 'settlement':
                metric('待开票申请', query("SELECT COUNT(*) FROM consumer_invoice_request WHERE state='pending'").scalar_one())
        if role in ('driver', 'fleet', *staff):
            result['recent_orders'] = rows('SELECT id,state,station_id,account_id,gross,discount,received,refunded,outstanding,started_at FROM v_order_balance o WHERE ' + order_predicate() + ' ORDER BY id DESC LIMIT 6', **order_parameters())
        if role in ('admin', 'maintenance'):
            result['recent_alarms'] = rows('SELECT * FROM v_live_alarm WHERE (:admin OR station_id=:sid) ORDER BY deadline LIMIT 6', admin=role == 'admin', sid=g.actor['station_id'])
        if role in (*staff, 'operator'):
            result['recent_settlements'] = rows('SELECT * FROM v_invoice_balance WHERE (:staff OR operator_id=:oid) ORDER BY period DESC,id DESC LIMIT 6', staff=role in staff, oid=g.actor['operator_id'])
        return result

    @bp.get('/ui/api/orders')
    @tx('driver', 'fleet', *staff)
    def ui_orders():
        return rows('SELECT * FROM v_order_balance o WHERE ' + order_predicate() +
                    " AND (:state='' OR o.state=:state) ORDER BY id DESC LIMIT 30 OFFSET :off",
                    **order_parameters(), state=request.args.get('state', ''), off=max(0, request.args.get('offset', 0, type=int)))

    @bp.get('/ui/api/orders/<int:key>')
    @tx('driver', 'fleet', *staff)
    def ui_order(key):
        record = rows('SELECT * FROM v_order_balance o WHERE o.id=:id AND ' + order_predicate(), id=key, **order_parameters())
        if not record:
            abort(404)
        latest, progress = order_progress(record[0])
        review = rows('SELECT * FROM order_review WHERE order_id=:id', id=key)
        return {'order': record[0], 'segments': rows('SELECT * FROM fee_detail WHERE order_id=:id ORDER BY begins', id=key),
                'samples': rows('SELECT sampled_at,reading FROM meter_sample WHERE order_id=:id ORDER BY sampled_at', id=key),
                'review': review[0] if review else None,
                'payments': rows('SELECT * FROM payment WHERE order_id=:id ORDER BY id', id=key),
                'refunds': rows('SELECT r.* FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=:id ORDER BY r.id', id=key),
                'invoices': rows('SELECT * FROM consumer_invoice WHERE order_id=:id ORDER BY id', id=key),
                'requests': rows('SELECT * FROM consumer_invoice_request WHERE order_id=:id ORDER BY id', id=key),
                'latest_meter': latest, 'progress': progress}

    @bp.post('/ui/api/orders/<int:key>/stop')
    @tx('driver', *staff)
    def request_stop(key):
        record = query('SELECT id,state,stop_requested_at FROM charge_order WHERE id=:id AND (:staff OR account_id=:uid) FOR UPDATE',
                       id=key, staff=g.actor['role'] in staff, uid=g.actor['id']).mappings().one_or_none()
        if not record:
            abort(404)
        if record['state'] not in ('starting', 'charging', 'finishing'):
            abort(409, '当前订单状态不能申请停止')
        query('UPDATE charge_order SET stop_requested_at=COALESCE(stop_requested_at,SYSDATE(6)) WHERE id=:id', id=key)
        return {'requested': True, 'order': rows('SELECT id,state,stop_requested_at FROM charge_order WHERE id=:id', id=key)[0],
                'message': '已记录停止请求，等待设备结束并上传计量；演示时由管理员模拟结束'}

    @bp.get('/ui/api/campaigns')
    @tx('driver', 'admin')
    def campaigns():
        return campaign_list()

    @bp.get('/ui/api/fleet-cards')
    @tx('driver', 'fleet', 'admin')
    def fleet_cards():
        return cards()

    @bp.patch('/ui/api/fleet-cards/<int:key>')
    @tx('fleet', 'admin')
    def edit_fleet_card(key):
        value = data('credit_limit', 'enabled')
        limit = number(value['credit_limit'], 0, Decimal('9999999999.99'))
        if limit != limit.quantize(Decimal('.01')) or not isinstance(value['enabled'], bool):
            abort(400, '额度须为两位小数，启用状态须为布尔值')
        if not query('SELECT fc.id FROM fleet_card fc JOIN fleet f ON f.id=fc.fleet_id WHERE fc.id=:id AND (:admin OR f.manager_id=:uid) FOR UPDATE',
                     id=key, admin=g.actor['role'] == 'admin', uid=g.actor['id']).scalar():
            abort(404)
        # The existing current-read procedure checks this month's used amount and all reservations.
        query('UPDATE fleet_card SET credit_limit=:limit,enabled=:enabled WHERE id=:id', limit=limit, enabled=value['enabled'], id=key)
        query("CALL check_fleet_credit_current(:id,0,CAST(DATE_FORMAT(NOW(),'%Y-%m-01') AS DATE),0,0,0)", id=key)
        return {'id': key, 'credit_limit': limit, 'enabled': value['enabled']}

    @bp.get('/ui/api/users')
    @tx('admin')
    def users():
        return rows('SELECT id,login,role,phone_mask,verified,tier,registered_at,station_id,operator_id FROM account '
                    'WHERE login LIKE :name ORDER BY id LIMIT 50 OFFSET :off', name='%' + request.args.get('name', '') + '%',
                    off=max(0, request.args.get('offset', 0, type=int)))

    @bp.get('/ui/api/telemetry')
    @tx('admin', 'maintenance')
    def recent_telemetry():
        return rows('SELECT t.*,c.station_id FROM telemetry t JOIN charger c ON c.id=t.charger_id '
                    'WHERE (:admin OR c.station_id=:sid) AND (:charger=0 OR t.charger_id=:charger) '
                    'ORDER BY t.sampled_at DESC,t.charger_id LIMIT :limit', admin=g.actor['role'] == 'admin',
                    sid=g.actor['station_id'], charger=request.args.get('charger', 0, type=int),
                    limit=min(max(request.args.get('limit', 100, type=int), 1), 500))

    @bp.get('/ui/api/settlements/<int:key>/evidence')
    @tx(*staff, 'operator')
    def settlement_evidence(key):
        permitted_settlement(key)
        return {'items': rows('SELECT * FROM settlement_item WHERE settlement_id=:id ORDER BY order_id', id=key),
                'adjustments': rows('SELECT * FROM settlement_adjustment WHERE settlement_id=:id ORDER BY id', id=key),
                'external': rows('SELECT * FROM external_bill WHERE settlement_id=:id ORDER BY order_id', id=key),
                'imports': rows('SELECT * FROM settlement_import WHERE settlement_id=:id', id=key),
                'signatures': rows('SELECT c.*,a.login FROM settlement_confirmation c JOIN account a ON a.id=c.actor WHERE c.settlement_id=:id ORDER BY side', id=key),
                'opinions': rows('SELECT c.*,a.login FROM diff_confirmation c JOIN recon_diff d ON d.id=c.diff_id '
                                 'JOIN account a ON a.id=c.actor WHERE d.settlement_id=:id ORDER BY c.diff_id,c.side', id=key)}

    @bp.get('/ui/api/invoice-requests')
    @tx(*staff)
    def invoice_requests():
        return rows('SELECT r.*,o.account_id,a.login,o.net_due,v.remaining FROM consumer_invoice_request r '
                    'JOIN v_order_balance o ON o.id=r.order_id JOIN account a ON a.id=o.account_id '
                    'JOIN v_consumer_invoice_balance v ON v.order_id=r.order_id ORDER BY r.id DESC LIMIT 100')

    @bp.post('/ui/api/settlements/<int:key>/reset-import')
    @tx(*staff)
    def reset_settlement_import(key):
        if data('confirmed')['confirmed'] is not True:
            abort(400, '请明确确认将清除本次外账、差异、处理意见及账单签字')
        record = query('SELECT id,state FROM settlement WHERE id=:id FOR UPDATE', id=key).mappings().one_or_none()
        if not record:
            abort(404)
        if record['state'] != 'draft':
            abort(409, '只能重置未确认的草稿账单')
        if not query('SELECT settlement_id FROM settlement_import WHERE settlement_id=:id', id=key).scalar():
            abort(409, '账单没有可重置的外账批次')
        query('CALL reset_bill_import(:id)', id=key)
        return '', 204

    @bp.get('/ui/api/asset-requests')
    @tx('admin')
    def asset_requests():
        return rows('SELECT r.*,c.station_id,c.model FROM asset_request r JOIN charger c ON c.id=r.charger_id ORDER BY r.id DESC LIMIT 100')

    @bp.post('/ui/api/asset-requests')
    @tx('admin')
    def add_asset_request():
        value = data('charger_id')
        kind = value.get('kind', 'acceptance')
        if kind not in ('acceptance', 'amendment', 'offline') or not isinstance(value.get('payload', {}), dict):
            abort(400, '申请类型或参数不正确')
        if not query('SELECT id FROM charger WHERE id=:id FOR UPDATE', id=value['charger_id']).scalar():
            abort(404)
        if query("SELECT id FROM asset_request WHERE charger_id=:id AND kind=:kind AND state='pending'", id=value['charger_id'], kind=kind).scalar():
            abort(409, '该设备已有同类待处理申请')
        key = query('INSERT INTO asset_request(charger_id,kind,payload) VALUES(:id,:kind,:payload)',
                    id=value['charger_id'], kind=kind, payload=json.dumps(value.get('payload', {}), ensure_ascii=False)).lastrowid
        return {'id': key}, 201

    app.register_blueprint(bp)
