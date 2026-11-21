"""Browser read-model, CSRF and ownership tests against the local course database."""

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

from pathlib import Path
import json
import os
import sys
import unittest
import uuid

from local_runtime import load_runtime
load_runtime()
from app import app, engine
from auth import password_hash
from web_ui import register_web
register_web(app)


class WebWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with engine.connect() as db:
            records = db.exec_driver_sql('SELECT id,login,role,station_id,operator_id FROM account ORDER BY id').mappings().all()
        cls.actors = {}
        for record in records:
            cls.actors.setdefault(record['role'], dict(record))

    def client(self, role=None):
        client = app.test_client()
        if role:
            with client.session_transaction() as cookie:
                cookie['user'] = self.actors[role]['id']
        return client

    def token(self, client):
        return client.get('/ui/session').get_json()['csrf_token']

    def headers(self, token, origin='http://localhost'):
        return {'Origin': origin, 'X-UI-Request': '1', 'X-CSRF-Token': token}

    def test_session_is_safe_and_anonymous(self):
        response = self.client().get('/ui/session')
        self.assertEqual(response.status_code, 200)
        record = response.get_json()
        self.assertFalse(record['authenticated'])
        self.assertIsNone(record['user'])
        self.assertGreater(len(record['csrf_token']), 30)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')

    def test_browser_write_requires_csrf(self):
        client = self.client()
        payload = {'login': 'missing-' + uuid.uuid4().hex, 'password': 'invalid-test-password'}
        self.assertEqual(client.post('/auth/login', json=payload, headers={'Origin': 'http://localhost'}).status_code, 403)
        self.assertEqual(client.post('/auth/login', json=payload, headers=self.headers('wrong')).status_code, 403)
        self.assertEqual(client.post('/auth/login', json=payload, headers=self.headers(self.token(client))).status_code, 401)

    def test_cross_origin_is_rejected_even_with_token(self):
        client = self.client()
        token = self.token(client)
        for origin in ('https://attacker.example', 'http://localhost:9999', 'null', 'http://['):
            self.assertEqual(client.post('/auth/logout', headers=self.headers(token, origin)).status_code, 403)
        headers = self.headers(token)
        headers['Sec-Fetch-Site'] = 'cross-site'
        self.assertEqual(client.post('/auth/logout', headers=headers).status_code, 403)

    def test_login_rotates_csrf_and_logout_invalidates_identity(self):
        client = self.client()
        login, password = 'ui-login-' + uuid.uuid4().hex, uuid.uuid4().hex
        with engine.begin() as db:
            uid = db.exec_driver_sql("INSERT INTO account(login,password_hash,role) VALUES(%s,%s,'driver')", (login, password_hash(password))).lastrowid
        try:
            old = self.token(client)
            self.assertEqual(client.post('/auth/login', json={'login': login, 'password': password}, headers=self.headers(old)).status_code, 200)
            response = client.get('/ui/session').get_json()
            self.assertTrue(response['authenticated'])
            self.assertEqual(response['user']['id'], uid)
            self.assertNotEqual(old, response['csrf_token'])
            self.assertNotIn('password_hash', json.dumps(response))
            self.assertEqual(client.post('/auth/logout', headers=self.headers(old)).status_code, 403)
            self.assertEqual(client.post('/auth/logout', headers=self.headers(response['csrf_token'])).status_code, 204)
            self.assertFalse(client.get('/ui/session').get_json()['authenticated'])
        finally:
            with engine.begin() as db:
                db.exec_driver_sql('DELETE FROM account WHERE id=%s', (uid,))

    def test_all_role_dashboards_and_lookup_serialization(self):
        for role in self.actors:
            with self.subTest(role=role):
                client = self.client(role)
                dashboard = client.get('/ui/api/dashboard')
                lookups = client.get('/ui/api/lookups')
                self.assertEqual(dashboard.status_code, 200)
                self.assertEqual(lookups.status_code, 200)
                self.assertTrue(dashboard.get_json()['metrics'])
                serialized = lookups.get_data(as_text=True)
                for secret in ('password_hash', 'phone_cipher', 'plate_cipher'):
                    self.assertNotIn(secret, serialized)
                self.assertIsInstance(lookups.get_json()['stations'], list)
                if role == 'driver':
                    self.assertIn('available_balance', dashboard.get_json()['wallet'])
                    self.assertTrue(all(x['account_id'] == self.actors[role]['id'] for x in lookups.get_json()['vehicles']))
                if role == 'maintenance':
                    self.assertTrue(all(x['id'] == self.actors[role]['station_id'] for x in lookups.get_json()['stations']))
                    self.assertEqual(lookups.get_json()['users'], [])

    def test_anonymous_and_driver_cannot_read_admin_models(self):
        for path in ('/ui/api/dashboard', '/ui/api/lookups', '/ui/api/users', '/ui/api/asset-requests'):
            self.assertEqual(self.client().get(path).status_code, 401)
        driver = self.client('driver')
        for path in ('/ui/api/users', '/ui/api/asset-requests', '/ui/api/telemetry', '/ui/api/invoice-requests', '/ui/api/settlements/1/evidence'):
            self.assertEqual(driver.get(path).status_code, 403)

    def test_driver_order_read_models_preserve_ownership(self):
        client = self.client('driver')
        uid = self.actors['driver']['id']
        records = client.get('/ui/api/orders').get_json()
        self.assertTrue(all(x['account_id'] == uid for x in records))
        with engine.connect() as db:
            own = db.exec_driver_sql('SELECT id FROM charge_order WHERE account_id=%s ORDER BY id LIMIT 1', (uid,)).scalar()
            other = db.exec_driver_sql('SELECT id FROM charge_order WHERE account_id<>%s ORDER BY id LIMIT 1', (uid,)).scalar()
        self.assertIsNotNone(own)
        detail = client.get(f'/ui/api/orders/{own}')
        self.assertEqual(detail.status_code, 200)
        self.assertTrue({'order', 'segments', 'payments', 'refunds', 'invoices', 'requests', 'progress'} <= detail.get_json().keys())
        if other:
            self.assertEqual(client.get(f'/ui/api/orders/{other}').status_code, 404)
            self.assertEqual(client.post(f'/ui/api/orders/{other}/stop', json={}).status_code, 404)

    def test_fleet_queries_only_return_owned_cards_and_orders(self):
        client, uid = self.client('fleet'), self.actors['fleet']['id']
        cards = client.get('/ui/api/fleet-cards').get_json()
        self.assertTrue(all(x['manager_id'] == uid for x in cards))
        allowed = {x['id'] for x in cards}
        orders = client.get('/ui/api/orders').get_json()
        self.assertTrue(all(x['fleet_card_id'] in allowed for x in orders))
        with engine.connect() as db:
            other = db.exec_driver_sql('SELECT o.id FROM charge_order o WHERE NOT EXISTS(SELECT 1 FROM fleet_card fc JOIN fleet f ON f.id=fc.fleet_id WHERE fc.id=o.fleet_card_id AND f.manager_id=%s) ORDER BY o.id LIMIT 1', (uid,)).scalar()
        if other:
            self.assertEqual(client.get(f'/ui/api/orders/{other}').status_code, 404)

    def test_operator_evidence_scope(self):
        client, oid = self.client('operator'), self.actors['operator']['operator_id']
        with engine.connect() as db:
            own = db.exec_driver_sql('SELECT id FROM settlement WHERE operator_id=%s ORDER BY id LIMIT 1', (oid,)).scalar()
            other = db.exec_driver_sql('SELECT id FROM settlement WHERE operator_id<>%s ORDER BY id LIMIT 1', (oid,)).scalar()
        self.assertIsNotNone(own)
        response = client.get(f'/ui/api/settlements/{own}/evidence')
        self.assertEqual(response.status_code, 200)
        self.assertTrue({'items', 'adjustments', 'external', 'imports', 'signatures', 'opinions'} <= response.get_json().keys())
        if other:
            self.assertEqual(client.get(f'/ui/api/settlements/{other}/evidence').status_code, 404)

    def test_acceptance_request_roundtrip_and_duplicate_rejection(self):
        client = self.client('admin')
        with engine.begin() as db:
            station = db.exec_driver_sql('SELECT id FROM station ORDER BY id LIMIT 1').scalar_one()
            charger = db.exec_driver_sql("INSERT INTO charger(station_id,model,rated_kw,protocol) VALUES(%s,%s,60,'test')", (station, 'ui-asset-' + uuid.uuid4().hex)).lastrowid
        try:
            response = client.post('/ui/api/asset-requests', json={'charger_id': charger, 'kind': 'acceptance', 'payload': {'note': 'synthetic test'}})
            self.assertEqual(response.status_code, 201)
            request_id = response.get_json()['id']
            self.assertEqual(client.post('/ui/api/asset-requests', json={'charger_id': charger}).status_code, 409)
            self.assertEqual(client.post(f'/admin/chargers/{charger}/commission', json={'request': request_id}).status_code, 204)
            with engine.connect() as db:
                self.assertIsNotNone(db.exec_driver_sql('SELECT commissioned_on FROM charger WHERE id=%s', (charger,)).scalar_one())
                self.assertEqual(db.exec_driver_sql('SELECT state FROM asset_request WHERE id=%s', (request_id,)).scalar_one(), 'approved')
        finally:
            with engine.begin() as db:
                db.exec_driver_sql('DELETE FROM asset_request WHERE charger_id=%s', (charger,))
                db.exec_driver_sql('DELETE FROM charger WHERE id=%s', (charger,))

    def test_order_evidence_includes_all_samples_and_review(self):
        client = self.client('admin')
        with engine.connect() as db:
            order_id = db.exec_driver_sql('SELECT order_id FROM meter_sample GROUP BY order_id HAVING COUNT(*)>=3 ORDER BY order_id LIMIT 1').scalar_one()
            expected = db.exec_driver_sql('SELECT sampled_at,reading FROM meter_sample WHERE order_id=%s ORDER BY sampled_at', (order_id,)).all()
            review_order = db.exec_driver_sql('SELECT order_id FROM order_review ORDER BY order_id LIMIT 1').scalar()
        result = client.get(f'/ui/api/orders/{order_id}')
        self.assertEqual(result.status_code, 200)
        record = result.get_json()
        self.assertEqual(len(record['samples']), len(expected))
        self.assertEqual([x['reading'] for x in record['samples']], [str(x.reading) for x in expected])
        self.assertIn('review', record)
        if review_order:
            review = client.get(f'/ui/api/orders/{review_order}').get_json()['review']
            self.assertEqual(review['order_id'], review_order)
            self.assertIn('reason', review)
            self.assertIn('last_reading', review)

    def test_reset_import_clears_private_draft_evidence_and_signatures(self):
        client = self.client('admin')
        operator_id = station_id = settlement_id = account_id = None
        suffix = uuid.uuid4().hex
        try:
            with engine.begin() as db:
                operator_id = db.exec_driver_sql('INSERT INTO operator(name) VALUES(%s)', ('ui-reset-' + suffix,)).lastrowid
                station_id = db.exec_driver_sql("INSERT INTO station(operator_id,name,address,spaces) VALUES(%s,%s,'synthetic',1)", (operator_id, 'ui-reset-' + suffix)).lastrowid
                settlement_id = db.exec_driver_sql("INSERT INTO settlement(station_id,operator_id,period) VALUES(%s,%s,'2026-11-01')", (station_id, operator_id)).lastrowid
                account_id = db.exec_driver_sql("INSERT INTO account(login,password_hash,role,operator_id) VALUES(%s,%s,'operator',%s)", ('ui-reset-' + suffix, password_hash(uuid.uuid4().hex), operator_id)).lastrowid
            payload = 'order_id,kwh,amount,paid\n900000001,1,2,true\n'
            self.assertEqual(client.post(f'/settlements/{settlement_id}/import?batch=private-test', data=payload, content_type='text/csv').status_code, 204)
            with engine.begin() as db:
                difference = db.exec_driver_sql('SELECT id FROM recon_diff WHERE settlement_id=%s', (settlement_id,)).scalar_one()
                db.exec_driver_sql("CALL confirm_difference(%s,%s,'reject')", (difference, self.actors['admin']['id']))
                db.exec_driver_sql("CALL confirm_difference(%s,%s,'reject')", (difference, account_id))
                db.exec_driver_sql('CALL confirm_settlement(%s,%s)', (settlement_id, self.actors['admin']['id']))
            evidence = client.get(f'/ui/api/settlements/{settlement_id}/evidence').get_json()
            self.assertEqual(len(evidence['external']), 1)
            self.assertEqual(len(evidence['opinions']), 2)
            self.assertEqual(len(evidence['signatures']), 1)
            endpoint = f'/ui/api/settlements/{settlement_id}/reset-import'
            self.assertEqual(client.post(endpoint, json={'confirmed': False}).status_code, 400)
            operator_client = app.test_client()
            with operator_client.session_transaction() as cookie:
                cookie['user'] = account_id
            self.assertEqual(operator_client.post(endpoint, json={'confirmed': True}).status_code, 403)
            self.assertEqual(client.post(endpoint, json={'confirmed': True}).status_code, 204)
            result = client.get(f'/ui/api/settlements/{settlement_id}/evidence').get_json()
            for collection in ('external', 'imports', 'opinions', 'signatures', 'adjustments'):
                self.assertEqual(result[collection], [], collection)
            self.assertEqual(client.get(f'/settlements/{settlement_id}').get_json()['differences'], [])
            self.assertEqual(client.get(f'/settlements/{settlement_id}').get_json()['settlement']['state'], 'draft')
            self.assertEqual(client.post(endpoint, json={'confirmed': True}).status_code, 409)
        finally:
            with engine.begin() as db:
                if settlement_id:
                    db.exec_driver_sql('CALL reset_bill_import(%s)', (settlement_id,))
                    db.exec_driver_sql('DELETE FROM settlement WHERE id=%s', (settlement_id,))
                if account_id:
                    db.exec_driver_sql('DELETE FROM account WHERE id=%s', (account_id,))
                if station_id:
                    db.exec_driver_sql('DELETE FROM station WHERE id=%s', (station_id,))
                if operator_id:
                    db.exec_driver_sql('DELETE FROM operator WHERE id=%s', (operator_id,))


if __name__ == '__main__':
    unittest.main(verbosity=2)
