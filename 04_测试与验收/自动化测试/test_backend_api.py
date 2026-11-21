"""Real-database API checks; use only the dedicated synthetic course database."""

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

from datetime import datetime, timedelta
import os
import sys
import unittest
import uuid
from pathlib import Path

from app import app


class BackendAPI(unittest.TestCase):
    def client(self,login=None):
        client=app.test_client()
        if login:
            result=client.post('/auth/login',json={'login':login,'password':os.environ['CHARGE_DEMO_PASSWORD']})
            self.assertEqual(result.status_code,200,result.get_json())
        return client

    def test_health_and_json_errors(self):
        c=self.client()
        self.assertEqual(c.get('/health').status_code,200)
        self.assertEqual(c.get('/orders').status_code,401)
        self.assertTrue(c.get('/orders').is_json)
        self.assertEqual(c.post('/auth/login',json=[]).status_code,400)

    def test_owner_and_roles(self):
        c=self.client('driver1')
        self.assertEqual(c.get('/orders/1').status_code,200)
        self.assertEqual(c.get('/orders/2').status_code,404)
        self.assertEqual(c.get('/admin/assets/station').status_code,403)
        self.assertEqual(c.get('/work').status_code,403)
        self.assertEqual(c.get('/stations?name=%27%20OR%201%3D1--').get_json(),[])
        self.assertNotIn('password_hash',c.get('/me').get_json()['account'])
        self.assertNotIn('phone_cipher',c.get('/me').get_json()['account'])

    def test_input_validation_and_cancel(self):
        admin=self.client('admin'); driver=self.client('driver1')
        self.assertEqual(admin.post('/demo/chargers/1/state',json={'state':'idle'}).status_code,204)
        opened=driver.post('/orders',json={'vehicle':1,'gun':1})
        self.assertEqual(opened.status_code,201,opened.get_json())
        key=opened.get_json()['id']
        try:
            result=admin.post(f'/demo/order/{key}/readings',json={'samples':[{}]})
            self.assertEqual(result.status_code,400,result.get_json())
            result=admin.post('/demo/chargers/1/telemetry',json={'samples':[None]})
            self.assertEqual(result.status_code,400,result.get_json())
            self.assertEqual(driver.post('/estimate',json={'vehicle':1,'gun':1,'at':'bad','current_soc':80,'target_soc':20}).status_code,400)
        finally:
            self.assertEqual(driver.post(f'/orders/{key}/cancel',json={}).status_code,204)
        self.assertEqual(driver.post(f'/orders/{key}/cancel',json={}).status_code,204)

    def test_maintenance_and_operator_scopes(self):
        tech=self.client('tech1')
        self.assertEqual(tech.get('/work').status_code,200)
        self.assertEqual(tech.get('/admin/stations/2/assets').status_code,403)
        operator=self.client('operator1')
        bills=operator.get('/settlements')
        self.assertEqual(bills.status_code,200)
        self.assertTrue(all(x['operator_id']==1 for x in bills.get_json()))
        self.assertEqual(operator.get('/settlements/2').status_code,404)

    def test_login_failure_persists(self):
        from auth import password_hash
        from deploy import mysql_engine
        c = self.client()
        login = 'api-login-lock-' + uuid.uuid4().hex
        password = uuid.uuid4().hex
        engine = mysql_engine('CHARGE_DATABASE_URL')
        uid = None
        self.login_failure_checkpoints = []

        def state(stage):
            with engine.connect() as db:
                record = dict(db.exec_driver_sql(
                    'SELECT failed_logins,locked_until,COALESCE(locked_until>NOW(),false) locked,NOW() checked_at '
                    'FROM account WHERE id=%s', (uid,)).mappings().one())
            self.login_failure_checkpoints.append({
                'stage': stage, 'failed_logins': record['failed_logins'],
                'has_lock': record['locked_until'] is not None, 'locked': bool(record['locked'])})
            return record

        try:
            with engine.begin() as db:
                uid = db.exec_driver_sql(
                    "INSERT INTO account(login,password_hash,role) VALUES(%s,%s,'driver')",
                    (login, password_hash(password))).lastrowid
            for attempt in range(1, 5):
                self.assertEqual(c.post('/auth/login', json={'login': login, 'password': 'incorrect-password'}).status_code, 401)
                current = state(f'failure_{attempt}')
                self.assertEqual(current['failed_logins'], attempt)
                self.assertIsNone(current['locked_until'], f'failure {attempt} locked before threshold 5')

            with engine.connect() as db:
                before_fifth = db.exec_driver_sql('SELECT NOW()').scalar_one()
            self.assertEqual(c.post('/auth/login', json={'login': login, 'password': 'incorrect-password'}).status_code, 401)
            current = state('failure_5')
            self.assertEqual(current['failed_logins'], 5)
            self.assertTrue(current['locked'])
            self.assertGreaterEqual(current['locked_until'], before_fifth + timedelta(minutes=15))
            self.assertLessEqual(current['locked_until'], current['checked_at'] + timedelta(minutes=15))

            self.assertEqual(c.post('/auth/login', json={'login': login, 'password': password}).status_code, 401)
            current = state('correct_password_while_locked')
            self.assertEqual(current['failed_logins'], 5)
            self.assertTrue(current['locked'])

            with engine.begin() as db:
                db.exec_driver_sql('UPDATE account SET locked_until=NOW()-INTERVAL 1 SECOND WHERE id=%s', (uid,))
            self.assertEqual(c.post('/auth/login', json={'login': login, 'password': 'incorrect-password'}).status_code, 401)
            current = state('expired_lock_then_failure')
            self.assertEqual(current['failed_logins'], 1)
            self.assertIsNone(current['locked_until'])

            self.assertEqual(c.post('/auth/login', json={'login': login, 'password': password}).status_code, 200)
            current = state('successful_login')
            self.assertEqual(current['failed_logins'], 0)
            self.assertIsNone(current['locked_until'])
        finally:
            try:
                if uid is not None:
                    with engine.begin() as db:
                        db.exec_driver_sql('DELETE FROM account WHERE id=%s AND login=%s', (uid, login))
                    with engine.connect() as db:
                        remaining = db.exec_driver_sql('SELECT COUNT(*) FROM account WHERE id=%s', (uid,)).scalar_one()
                        self.login_fixture_cleanup_verified = remaining == 0
                        self.assertEqual(remaining, 0)
            finally:
                engine.dispose()

    def test_repository_and_pagination(self):
        c=self.client('admin')
        created=c.post('/admin/assets/operator',json={'name':'api-unreferenced-fixture'})
        self.assertEqual(created.status_code,201,created.get_json())
        key=created.get_json()['id']
        self.assertEqual(c.patch(f'/admin/assets/operator/{key}',json={'name':'api-renamed-fixture'}).status_code,204)
        self.assertEqual(c.get('/admin/assets/operator?offset=0').status_code,200)
        self.assertEqual(c.post('/admin/assets/operator',json={'name':'unsafe','password_hash':'x'}).status_code,400)
        self.assertEqual(c.delete(f'/admin/assets/operator/{key}').status_code,204)
        self.assertEqual(c.delete('/admin/assets/operator/1').status_code,409)

    def test_registration_and_pii_encryption(self):
        c=self.client(); login='api-privacy-'+uuid.uuid4().hex
        password=uuid.uuid4().hex
        result=c.post('/auth/register',json={'login':login,'password':password,'phone':'00000001234'})
        self.assertEqual(result.status_code,201,result.get_json())
        uid=result.get_json()['id']; vehicle_id=None
        from deploy import mysql_engine
        try:
            self.assertEqual(c.post('/auth/login',json={'login':login,'password':password}).status_code,200)
            response=c.post('/vehicles',json={'plate':'测试A00000','model':'synthetic API test','capacity_kwh':60,'max_kw':60,'supports_dc':True,'interface':'GB'})
            self.assertEqual(response.status_code,201,response.get_json())
            vehicle_id=response.get_json()['id']
            from cryptography.fernet import Fernet
            with mysql_engine().connect() as db:
                cipher,hashed=db.exec_driver_sql('SELECT phone_cipher,password_hash FROM account WHERE id=%s',(uid,)).one()
                self.assertNotIn(b'00000001234',cipher)
                self.assertEqual(Fernet(os.environ['CHARGE_PII_KEY'].encode()).decrypt(cipher).decode(),'00000001234')
                self.assertNotEqual(hashed,password)
            self.assertNotIn('phone_cipher',c.get('/me').get_json()['account'])
            self.assertEqual(c.delete(f'/vehicles/{vehicle_id}/binding').status_code,204)
        finally:
            with mysql_engine().begin() as db:
                db.exec_driver_sql('DELETE FROM vehicle_binding WHERE account_id=%s',(uid,))
                if vehicle_id: db.exec_driver_sql('DELETE FROM vehicle WHERE id=%s',(vehicle_id,))
                db.exec_driver_sql('DELETE FROM account WHERE id=%s',(uid,))

    def test_authorization_owner_other_driver_and_fleet_manager(self):
        # Reuse the isolated SQL fixture; login itself is covered by separate API tests.
        # Injecting its IDs into test-client sessions exercises real DB-backed role/owner checks.
        # local_runtime uses runpy, which does not add this script's directory.
        tests_directory = str(Path(__file__).resolve().parent)
        if tests_directory not in sys.path:
            sys.path.insert(0, tests_directory)
        import test_funding_concurrency as fixtures
        from deploy import mysql_engine
        from sqlalchemy import text
        fixture = fixtures.FundingConcurrencyTests('test_same_wallet_multiple_guns_reserve_once')
        fixture.engine = mysql_engine()
        extra = []

        def actor(account):
            client = app.test_client()
            with client.session_transaction() as stored:
                stored['user'] = account
            return client

        try:
            fixture.setUp()
            f = fixture.fx
            with fixture.engine.begin() as db:
                for suffix, role in (('-other-driver', 'driver'), ('-other-manager', 'fleet')):
                    extra.append(db.execute(text('INSERT INTO account(login,password_hash,role) '
                                                 'VALUES(:login,:disabled,:role)'),
                                             {'login': fixture.prefix+suffix, 'disabled': '!disabled-test-account', 'role': role}).lastrowid)
            owner, manager = actor(f['user']), actor(f['manager'])
            other, other_manager = actor(extra[0]), actor(extra[1])
            opened = owner.post('/orders', json={'vehicle': f['vehicles'][0], 'gun': f['guns'][0]})
            self.assertEqual(opened.status_code, 201, opened.get_json())
            order = opened.get_json()['id']
            permitted = owner.post(f'/orders/{order}/authorize', json={'total_budget': '21.00'})
            self.assertEqual(permitted.status_code, 200, permitted.get_json())
            self.assertEqual(str(permitted.get_json()['order']['authorized_amount']), '21.00')
            self.assertEqual(other.post(f'/orders/{order}/authorize', json={'total_budget': '22.00'}).status_code, 404)
            self.assertEqual(manager.post(f'/orders/{order}/authorize', json={'total_budget': '22.00'}).status_code, 404)
            self.assertEqual(owner.post(f'/orders/{order}/cancel', json={}).status_code, 204)
            opened = owner.post('/orders', json={'vehicle': f['vehicles'][0], 'gun': f['guns'][0], 'card': f['card']})
            self.assertEqual(opened.status_code, 201, opened.get_json())
            order = opened.get_json()['id']
            permitted = manager.post(f'/orders/{order}/authorize', json={'total_budget': '21.00'})
            self.assertEqual(permitted.status_code, 200, permitted.get_json())
            self.assertEqual(other_manager.post(f'/orders/{order}/authorize', json={'total_budget': '22.00'}).status_code, 404)
            self.assertEqual(other.post(f'/orders/{order}/authorize', json={'total_budget': '22.00'}).status_code, 404)
            permitted = owner.post(f'/orders/{order}/authorize', json={'total_budget': '22.00'})
            self.assertEqual(permitted.status_code, 200, permitted.get_json())
            # The manager cannot bypass the already-approved card limit of 25.
            self.assertEqual(manager.post(f'/orders/{order}/authorize', json={'total_budget': '26.00'}).status_code, 409)
            self.assertEqual(owner.post(f'/orders/{order}/cancel', json={}).status_code, 204)
            with fixture.engine.connect() as db:
                self.assertEqual(db.execute(text('SELECT reserved_balance FROM account WHERE id=:id'), {'id': f['user']}).scalar_one(), 0)
                self.assertEqual(db.execute(text('SELECT reserved_amount FROM fleet_card WHERE id=:id'), {'id': f['card']}).scalar_one(), 0)
        finally:
            try:
                with fixture.engine.begin() as db:
                    for account in extra:
                        db.execute(text('DELETE FROM account WHERE id=:id'), {'id': account})
                fixture.tearDown()
            finally:
                fixture.engine.dispose()


if __name__=='__main__':
    app.config['TESTING']=True
    unittest.main(verbosity=2)
