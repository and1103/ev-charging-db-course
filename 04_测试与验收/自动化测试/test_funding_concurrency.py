"""Run against the dedicated migrated MySQL schema; never uses seed IDs.

Set CHARGE_DATABASE_URL (or CHARGE_ADMIN_DSN) externally, then run this file.
Each test commits UUID-prefixed synthetic fixtures for independent connections,
and removes only its own rows in tearDown. No application login is enabled.
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

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

ROOT = APP_ROOT
from deploy import mysql_engine


def execute(db, sql, **params):
    return db.execute(text(sql), params)


class FundingConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = 'CHARGE_DATABASE_URL' if os.environ.get('CHARGE_DATABASE_URL') else 'CHARGE_ADMIN_DSN'
        if not os.environ.get(name):
            raise unittest.SkipTest('A dedicated MySQL DSN must be supplied through the environment')
        cls.engine = mysql_engine(name)
        with cls.engine.connect() as db:
            version = db.exec_driver_sql('SELECT VERSION()').scalar_one()
            if not version.startswith('8.4.'):
                raise unittest.SkipTest('This regression targets MySQL 8.4')

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'engine'):
            cls.engine.dispose()

    def setUp(self):
        self.fx = {}
        self.prefix = 'funding-test-' + uuid4().hex
        with self.engine.begin() as db:
            f = self.fx
            f['operator'] = execute(db, 'INSERT INTO operator(name) VALUES(:name)', name=self.prefix).lastrowid
            f['station'] = execute(db, 'INSERT INTO station(operator_id,name,address,spaces) VALUES(:op,:name,:name,2)',
                                   op=f['operator'], name=self.prefix).lastrowid
            f['charger'] = execute(db, "INSERT INTO charger(station_id,model,rated_kw,protocol,commissioned_on,heartbeat,state) "
                                   "VALUES(:station,'synthetic',120,'mock',CURRENT_DATE,SYSDATE(6),'idle')", station=f['station']).lastrowid
            f['guns'] = [execute(db, "INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) "
                                    "VALUES(:charger,:position,'DC','GB',60,'idle')", charger=f['charger'], position=i).lastrowid
                         for i in (1, 2)]
            f['user'] = execute(db, "INSERT INTO account(login,password_hash,role,balance,verified) "
                               "VALUES(:name,'!disabled-test-account','driver',30,true)", name=self.prefix).lastrowid
            f['admin'] = execute(db, "INSERT INTO account(login,password_hash,role) VALUES(:name,'!disabled-test-account','admin')",
                                name=self.prefix + '-admin').lastrowid
            f['manager'] = execute(db, "INSERT INTO account(login,password_hash,role) VALUES(:name,'!disabled-test-account','fleet')",
                                  name=self.prefix + '-manager').lastrowid
            f['vehicles'] = []
            for _ in range(2):
                vehicle = execute(db, "INSERT INTO vehicle(plate_mask,model,capacity_kwh,max_kw,supports_dc,interface) "
                                  "VALUES('synthetic','test',60,60,true,'GB')").lastrowid
                f['vehicles'].append(vehicle)
                execute(db, 'INSERT INTO vehicle_binding(vehicle_id,account_id) VALUES(:vehicle,:user)', vehicle=vehicle, user=f['user'])
            f['tariff'] = execute(db, "INSERT INTO tariff(station_id,starts,ends,service_mode,authorization_amount) "
                                 "VALUES(:station,'2025-01-01','2035-01-01','kwh',20)", station=f['station']).lastrowid
            execute(db, "INSERT INTO tariff_band VALUES(:tariff,0,1440,'flat',1,0)", tariff=f['tariff'])
            f['campaign'] = execute(db, 'INSERT INTO campaign(name,station_id,face,minimum,starts,expires,stock) '
                                   'VALUES(:name,:station,2,0,NOW()-INTERVAL 1 DAY,NOW()+INTERVAL 1 DAY,1)',
                                   name=self.prefix, station=f['station']).lastrowid
            f['coupon'] = execute(db, 'SELECT issue_coupon(:campaign,:user)', campaign=f['campaign'], user=f['user']).scalar_one()
            f['fleet'] = execute(db, 'INSERT INTO fleet(manager_id,name) VALUES(:manager,:name)', manager=f['manager'], name=self.prefix).lastrowid
            f['card'] = execute(db, 'INSERT INTO fleet_card(fleet_id,vehicle_id,driver_id,credit_limit) VALUES(:fleet,:vehicle,:user,25)',
                               fleet=f['fleet'], vehicle=f['vehicles'][0], user=f['user']).lastrowid
        self.committed_fixture = True

    def tearDown(self):
        if not getattr(self, 'committed_fixture', False):
            return
        f = self.fx
        # Scope every statement to the UUID fixture's private account/station IDs.
        with self.engine.begin() as db:
            execute(db, "UPDATE charge_order SET state='cancelled' WHERE account_id=:user AND station_id=:station",
                    user=f['user'], station=f['station'])
            execute(db, 'DELETE FROM wallet_entry WHERE account_id=:user', user=f['user'])
            execute(db, 'DELETE r FROM refund r JOIN payment p ON p.id=r.payment_id JOIN charge_order o ON o.id=p.order_id '
                        'WHERE o.account_id=:user', user=f['user'])
            execute(db, 'DELETE r FROM redemption r JOIN charge_order o ON o.id=r.order_id WHERE o.account_id=:user', user=f['user'])
            for table in ('order_review', 'fee_detail', 'meter_sample', 'payment'):
                execute(db, f'DELETE t FROM {table} t JOIN charge_order o ON o.id=t.order_id WHERE o.account_id=:user', user=f['user'])
            execute(db, 'DELETE FROM charge_order WHERE account_id=:user AND station_id=:station', user=f['user'], station=f['station'])
            execute(db, 'DELETE FROM coupon WHERE campaign_id=:campaign', campaign=f['campaign'])
            execute(db, 'DELETE FROM campaign WHERE id=:campaign', campaign=f['campaign'])
            execute(db, 'DELETE FROM fleet_card WHERE fleet_id=:fleet', fleet=f['fleet'])
            execute(db, 'DELETE FROM fleet WHERE id=:fleet', fleet=f['fleet'])
            execute(db, 'DELETE FROM vehicle_binding WHERE account_id=:user', user=f['user'])
            for vehicle in f['vehicles']:
                execute(db, 'DELETE FROM vehicle WHERE id=:vehicle', vehicle=vehicle)
            for account in (f['user'], f['admin'], f['manager']):
                execute(db, 'DELETE FROM account WHERE id=:account', account=account)
            execute(db, 'DELETE FROM tariff_band WHERE tariff_id=:tariff', tariff=f['tariff'])
            execute(db, 'DELETE FROM tariff WHERE id=:tariff', tariff=f['tariff'])
            execute(db, 'DELETE FROM asset_history WHERE charger_id=:charger OR connector_id IN '
                        '(SELECT id FROM connector WHERE charger_id=:charger)', charger=f['charger'])
            execute(db, 'DELETE FROM connector WHERE charger_id=:charger', charger=f['charger'])
            execute(db, 'DELETE FROM charger WHERE id=:charger', charger=f['charger'])
            execute(db, 'DELETE FROM station WHERE id=:station', station=f['station'])
            execute(db, 'DELETE FROM operator WHERE id=:operator', operator=f['operator'])

    def race(self, *actions):
        barrier = threading.Barrier(len(actions))

        def worker(action):
            for attempt in range(5):
                try:
                    with self.engine.begin() as db:
                        if attempt == 0:
                            barrier.wait(timeout=15)
                        result = action(db)
                    return ('ok', result)
                except DBAPIError as error:
                    code = error.orig.args[0]
                    if code in (1205, 1213) and attempt < 4:
                        time.sleep(0.02 * (attempt + 1))
                        continue
                    # Do not print SQL parameters or connection configuration.
                    return ('error', code)

        with ThreadPoolExecutor(max_workers=len(actions)) as executor:
            return list(executor.map(worker, actions))

    def assert_one_success(self, results):
        self.assertEqual(sum(state == 'ok' for state, _ in results), 1, results)
        for state, code in results:
            if state == 'error':
                self.assertIn(code, (1062, 1644), results)
        return next(value for state, value in results if state == 'ok')

    def billed_order(self, db, gun):
        f = self.fx
        key = execute(db, "INSERT INTO charge_order(account_id,vehicle_id,connector_id,tariff_id,started_at,ended_at,state,kwh,gross) "
                      "VALUES(:user,:vehicle,:gun,:tariff,SYSDATE(6)-INTERVAL 1 HOUR,SYSDATE(6),'billed',5,5)",
                      user=f['user'], vehicle=f['vehicles'][0], gun=gun, tariff=f['tariff']).lastrowid
        execute(db, "INSERT INTO fee_detail SELECT id,started_at,ended_at,'flat',5,1,0,5,0,false FROM charge_order WHERE id=:id", id=key)
        return key

    def test_same_coupon_two_orders(self):
        f = self.fx
        with self.engine.begin() as db:
            orders = [self.billed_order(db, gun) for gun in f['guns']]
        results = self.race(*(lambda db, key=key: execute(db, 'CALL redeem_coupon(:order,:coupon,:user)',
                             order=key, coupon=f['coupon'], user=f['user']).rowcount for key in orders))
        self.assert_one_success(results)
        with self.engine.connect() as db:
            self.assertEqual(execute(db, 'SELECT COUNT(*) FROM redemption WHERE coupon_id=:coupon', coupon=f['coupon']).scalar_one(), 1)
            self.assertEqual(execute(db, 'SELECT SUM(discount) FROM charge_order WHERE account_id=:user', user=f['user']).scalar_one(), Decimal('2'))

    def test_same_wallet_multiple_guns_reserve_once(self):
        f = self.fx
        results = self.race(*(lambda db, i=i: execute(db, 'SELECT open_charge(:user,:vehicle,:gun,NULL)',
                             user=f['user'], vehicle=f['vehicles'][i], gun=f['guns'][i]).scalar_one() for i in range(2)))
        self.assert_one_success(results)
        with self.engine.connect() as db:
            self.assertEqual(execute(db, 'SELECT reserved_balance FROM account WHERE id=:user', user=f['user']).scalar_one(), Decimal('20'))
            self.assertEqual(execute(db, 'SELECT COUNT(*) FROM charge_order WHERE account_id=:user AND active_gun IS NOT NULL', user=f['user']).scalar_one(), 1)

    def test_same_card_and_monthly_credit(self):
        f = self.fx
        results = self.race(*(lambda db, i=i: execute(db, 'SELECT open_charge(:user,:vehicle,:gun,:card)',
                             user=f['user'], vehicle=f['vehicles'][0], gun=f['guns'][i], card=f['card']).scalar_one() for i in range(2)))
        order = self.assert_one_success(results)
        with self.engine.begin() as db:
            self.assertEqual(execute(db, 'SELECT reserved_amount FROM fleet_card WHERE id=:card', card=f['card']).scalar_one(), Decimal('20'))
            started = execute(db, 'SELECT started_at FROM charge_order WHERE id=:order', order=order).scalar_one()
            for at, reading in ((started, 0), (started + timedelta(minutes=1), 10)):
                execute(db, 'INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(:order,:at,:reading)', order=order, at=at, reading=reading)
            execute(db, 'CALL finish_charge(:order,:at,false)', order=order, at=started + timedelta(minutes=1))
            if execute(db, 'SELECT state FROM charge_order WHERE id=:order', order=order).scalar_one() == 'review':
                execute(db, 'CALL approve_review(:order,:admin,0,:note)', order=order, admin=f['admin'], note='synthetic boundary interpolation reviewed')
            self.assertEqual(execute(db, 'SELECT reserved_amount FROM fleet_card WHERE id=:card', card=f['card']).scalar_one(), Decimal('0'))
        # 10 already used, 15 remains: another 20 authorization must be rejected.
        results = self.race(lambda db: execute(db, 'SELECT open_charge(:user,:vehicle,:gun,:card)',
                             user=f['user'], vehicle=f['vehicles'][0], gun=f['guns'][0], card=f['card']).scalar_one())
        self.assertEqual(results, [('error', 1644)])

    def test_payment_and_refund_replays_are_idempotent(self):
        f = self.fx
        with self.engine.begin() as db:
            order = self.billed_order(db, f['guns'][0])
        reference = self.prefix + '-payment'
        pay = lambda db: execute(db, "SELECT post_payment(:user,:order,'wallet',:ref,5,true)",
                                user=f['user'], order=order, ref=reference).scalar_one()
        results = self.race(pay, pay)
        self.assertTrue(all(state == 'ok' for state, _ in results), results)
        self.assertEqual(results[0][1], results[1][1])
        payment = results[0][1]
        refund = lambda db: execute(db, 'SELECT post_refund(:payment,:ref,2)', payment=payment, ref=self.prefix + '-refund').scalar_one()
        results = self.race(refund, refund)
        self.assertTrue(all(state == 'ok' for state, _ in results), results)
        self.assertEqual(results[0][1], results[1][1])
        with self.engine.connect() as db:
            self.assertEqual(execute(db, 'SELECT balance FROM account WHERE id=:user', user=f['user']).scalar_one(), Decimal('27'))
            self.assertEqual(execute(db, 'SELECT COUNT(*) FROM payment WHERE order_id=:order', order=order).scalar_one(), 1)
            self.assertEqual(execute(db, 'SELECT COUNT(*) FROM refund WHERE payment_id=:payment', payment=payment).scalar_one(), 1)
            self.assertEqual(execute(db, 'SELECT COUNT(*) FROM wallet_entry WHERE account_id=:user', user=f['user']).scalar_one(), 2)
            self.assertEqual(execute(db, 'SELECT outstanding FROM v_order_balance WHERE id=:order', order=order).scalar_one(), Decimal('0'))

    def test_card_credit_uses_current_rows_despite_old_rr_snapshot(self):
        f = self.fx
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as stale:
            transaction = stale.begin()
            try:
                # Pin an old snapshot before another connection turns a hold into usage.
                self.assertEqual(execute(stale, 'SELECT COUNT(*) FROM charge_order WHERE fleet_card_id=:card', card=f['card']).scalar_one(), 0)
                with self.engine.begin() as writer:
                    order = execute(writer, 'SELECT open_charge(:user,:vehicle,:gun,:card)', user=f['user'],
                                    vehicle=f['vehicles'][0], gun=f['guns'][0], card=f['card']).scalar_one()
                    started = execute(writer, 'SELECT started_at FROM charge_order WHERE id=:id', id=order).scalar_one()
                    for at, reading in ((started, 0), (started + timedelta(minutes=1), 10)):
                        execute(writer, 'INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(:order,:at,:reading)',
                                order=order, at=at, reading=reading)
                    execute(writer, 'CALL finish_charge(:order,:at,false)', order=order, at=started + timedelta(minutes=1))
                    if execute(writer, 'SELECT state FROM charge_order WHERE id=:id', id=order).scalar_one() == 'review':
                        execute(writer, 'CALL approve_review(:order,:admin,0,:note)', order=order, admin=f['admin'],
                                note='synthetic time boundary reviewed')
                # The stale snapshot still sees zero usage, but the current limit is 25-10=15.
                self.assertEqual(execute(stale, 'SELECT COUNT(*) FROM charge_order WHERE fleet_card_id=:card', card=f['card']).scalar_one(), 0)
                # Use the actual card vehicle: ownership errors must not count as a quota test.
                with self.assertRaises(DBAPIError) as rejected:
                    execute(stale, 'SELECT open_charge(:user,:vehicle,:gun,:card)', user=f['user'],
                            vehicle=f['vehicles'][0], gun=f['guns'][1], card=f['card']).scalar_one()
                self.assertEqual(rejected.exception.orig.args[0], 1644)
                self.assertIn('credit', rejected.exception.orig.args[1].lower())
            finally:
                transaction.rollback()


if __name__ == '__main__':
    unittest.main(verbosity=2)
