"""Dedicated real-DB wallet/progress regressions; private UUID fixtures only.

No seed IDs, enabled logins or credentials are stored. Each committed fixture is
removed in tearDown. Requires the dedicated migrated course schema through the
same externally configured environment used by app.py.
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
from pathlib import Path
import sys
import threading
import unittest
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import app, engine


def execute(db, sql, **params):
    return db.execute(text(sql), params)


class WalletProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with engine.connect() as db:
            if db.exec_driver_sql("SELECT DATABASE()").scalar_one() != "charge_course_20261114":
                raise unittest.SkipTest("Only the dedicated synthetic course schema is permitted")
        app.config["TESTING"] = True

    def setUp(self):
        self.prefix = "wallet-progress-" + uuid4().hex
        self.fx = {}
        with engine.begin() as db:
            for label, role in (("user", "driver"), ("other", "driver"), ("admin", "admin")):
                self.fx[label] = execute(
                    db, "INSERT INTO account(login,password_hash,role,balance,verified) "
                    "VALUES(:name,'!disabled-synthetic-fixture',:role,0,true)",
                    name=self.prefix + "-" + label, role=role).lastrowid

    def client(self, label="user"):
        client = app.test_client()
        with client.session_transaction() as session:
            session["user"] = self.fx[label]
        return client

    def balance(self, label="user"):
        with engine.connect() as db:
            return execute(db, "SELECT balance FROM account WHERE id=:id", id=self.fx[label]).scalar_one()

    def reference(self):
        return "mock-" + uuid4().hex

    def tearDown(self):
        f = self.fx
        with engine.begin() as db:
            if "order" in f:
                execute(db, "UPDATE charge_order SET state='cancelled' WHERE id=:id AND account_id=:user",
                        id=f["order"], user=f["user"])
                execute(db, "DELETE FROM meter_sample WHERE order_id=:id", id=f["order"])
                execute(db, "DELETE FROM charge_order WHERE id=:id AND account_id=:user", id=f["order"], user=f["user"])
            for label in ("user", "other"):
                execute(db, "DELETE FROM wallet_entry WHERE account_id=:id", id=f[label])
            if "vehicle" in f:
                execute(db, "DELETE FROM vehicle_binding WHERE vehicle_id=:id AND account_id=:user",
                        id=f["vehicle"], user=f["user"])
                execute(db, "DELETE FROM vehicle WHERE id=:id", id=f["vehicle"])
            if "tariff" in f:
                execute(db, "DELETE FROM tariff_band WHERE tariff_id=:id", id=f["tariff"])
                execute(db, "DELETE FROM tariff WHERE id=:id", id=f["tariff"])
            if "charger" in f:
                execute(db, "DELETE FROM asset_history WHERE charger_id=:charger OR connector_id=:gun",
                        charger=f["charger"], gun=f["gun"])
                execute(db, "DELETE FROM connector WHERE id=:id", id=f["gun"])
                execute(db, "DELETE FROM charger WHERE id=:id", id=f["charger"])
                execute(db, "DELETE FROM station WHERE id=:id", id=f["station"])
                execute(db, "DELETE FROM operator WHERE id=:id", id=f["operator"])
            for label in ("user", "other", "admin"):
                execute(db, "DELETE FROM account WHERE id=:id", id=f[label])

    def test_zero_balance_funding_and_exact_replay(self):
        client = self.client()
        reference = self.reference()
        self.assertEqual(self.balance(), 0)
        first = client.post("/wallet/mock-topups", json={"request_id": reference, "amount": "20.00"})
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertTrue(first.get_json()["simulation"])
        self.assertFalse(first.get_json()["real_payment"])
        self.assertEqual(self.balance(), Decimal("20.00"))
        replay = client.post("/wallet/mock-topups", json={"request_id": reference, "amount": 20})
        self.assertEqual(replay.status_code, 200, replay.get_json())
        self.assertEqual(first.get_json()["wallet_entry_id"], replay.get_json()["wallet_entry_id"])
        self.assertEqual(self.balance(), Decimal("20.00"))
        self.assertEqual(client.post("/wallet/mock-topups", json={"request_id": reference, "amount": 21}).status_code, 409)
        self.assertEqual(self.client("other").post("/wallet/mock-topups", json={"request_id": reference, "amount": 20}).status_code, 409)
        self.assertEqual(self.balance("other"), 0)

    def test_invalid_amounts_references_and_auth(self):
        self.assertEqual(app.test_client().post("/wallet/mock-topups", json={"request_id": self.reference(), "amount": 1}).status_code, 401)
        self.assertEqual(self.client("admin").post("/wallet/mock-topups", json={"request_id": self.reference(), "amount": 1}).status_code, 403)
        client = self.client()
        for amount in (0, -1, True, "0.001", "NaN", "Infinity", "10000.01"):
            with self.subTest(amount=amount):
                self.assertEqual(client.post("/wallet/mock-topups", json={"request_id": self.reference(), "amount": amount}).status_code, 400)
        for reference in ("", "white space", "a" * 65, None, 123):
            self.assertEqual(client.post("/wallet/mock-topups", json={"request_id": reference, "amount": 1}).status_code, 400)
        self.assertEqual(self.balance(), 0)

    def test_reference_case_is_preserved(self):
        client = self.client()
        reference = self.reference()
        first = client.post("/wallet/mock-topups", json={"request_id": reference, "amount": 1})
        second = client.post("/wallet/mock-topups", json={"request_id": reference.upper(), "amount": 1})
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertNotEqual(first.get_json()["wallet_entry_id"], second.get_json()["wallet_entry_id"])
        self.assertEqual(self.balance(), 2)

    def test_caller_failure_rolls_back_journal_and_credit(self):
        reference = self.reference()
        with self.assertRaises(DBAPIError):
            with engine.begin() as db:
                execute(db, "SELECT mock_wallet_topup(:user,:ref,25)", user=self.fx["user"], ref=reference).scalar_one()
                execute(db, "INSERT INTO wallet_entry(account_id,`change`) VALUES(:user,0)", user=self.fx["user"])
        self.assertEqual(self.balance(), 0)
        with engine.connect() as db:
            self.assertEqual(execute(db, "SELECT COUNT(*) FROM wallet_entry WHERE topup_ref=:ref", ref=reference).scalar_one(), 0)

    def concurrent_posts(self, labels, references, amount):
        barrier = threading.Barrier(len(labels))

        def worker(label, reference):
            client = self.client(label)
            barrier.wait(timeout=10)
            result = client.post("/wallet/mock-topups", json={"request_id": reference, "amount": amount})
            return result.status_code, result.get_json()
        with ThreadPoolExecutor(max_workers=len(labels)) as workers:
            return list(workers.map(lambda args: worker(*args), zip(labels, references)))

    def test_concurrent_duplicate_and_distinct_requests(self):
        reference = self.reference()
        results = self.concurrent_posts(["user"] * 4, [reference] * 4, "25.00")
        self.assertTrue(all(status == 200 for status, _ in results), results)
        self.assertEqual(len({body["wallet_entry_id"] for _, body in results}), 1)
        self.assertEqual(self.balance(), 25)
        results = self.concurrent_posts(["user"] * 4, [self.reference() for _ in range(4)], "10.00")
        self.assertTrue(all(status == 200 for status, _ in results), results)
        self.assertEqual(self.balance(), 65)

    def test_cross_account_collision_never_double_credits(self):
        reference = self.reference()
        results = self.concurrent_posts(["user", "other"], [reference, reference], "10.00")
        self.assertEqual(sorted(status for status, _ in results), [200, 409], results)
        self.assertEqual(self.balance() + self.balance("other"), 10)
        with engine.connect() as db:
            self.assertEqual(execute(db, "SELECT COUNT(*) FROM wallet_entry WHERE topup_ref=:ref", ref=reference).scalar_one(), 1)

    def progress_fixture(self):
        result = self.client().post("/wallet/mock-topups", json={"request_id": self.reference(), "amount": "50.00"})
        self.assertEqual(result.status_code, 200, result.get_json())
        f = self.fx
        with engine.begin() as db:
            f["operator"] = execute(db, "INSERT INTO operator(name) VALUES(:name)", name=self.prefix).lastrowid
            f["station"] = execute(db, "INSERT INTO station(operator_id,name,address,spaces) VALUES(:op,:name,'synthetic',1)",
                                   op=f["operator"], name=self.prefix).lastrowid
            f["charger"] = execute(db, "INSERT INTO charger(station_id,model,rated_kw,protocol,commissioned_on,heartbeat,state) "
                                  "VALUES(:station,'synthetic',120,'mock',CURRENT_DATE,SYSDATE(6),'idle')", station=f["station"]).lastrowid
            f["gun"] = execute(db, "INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) "
                              "VALUES(:charger,1,'DC','GB',60,'idle')", charger=f["charger"]).lastrowid
            f["vehicle"] = execute(db, "INSERT INTO vehicle(plate_mask,model,capacity_kwh,max_kw,supports_dc,interface) "
                                  "VALUES('synthetic','synthetic',60,60,true,'GB')").lastrowid
            execute(db, "INSERT INTO vehicle_binding(vehicle_id,account_id) VALUES(:vehicle,:user)", vehicle=f["vehicle"], user=f["user"])
            f["tariff"] = execute(db, "INSERT INTO tariff(station_id,starts,ends,service_mode,authorization_amount) "
                                 "VALUES(:station,'2025-01-01','2035-01-01','kwh',20)", station=f["station"]).lastrowid
            execute(db, "INSERT INTO tariff_band VALUES(:tariff,0,1440,'flat',1,0)", tariff=f["tariff"])
            f["order"] = execute(db, "INSERT INTO charge_order(account_id,vehicle_id,connector_id,tariff_id,started_at,state,authorized_amount) "
                                "VALUES(:user,:vehicle,:gun,:tariff,SYSDATE(6)-INTERVAL 2 MINUTE,'charging',20)",
                                user=f["user"], vehicle=f["vehicle"], gun=f["gun"], tariff=f["tariff"]).lastrowid
            f["started"] = execute(db, "SELECT started_at FROM charge_order WHERE id=:id", id=f["order"]).scalar_one()
            execute(db, "UPDATE connector SET state='occupied' WHERE id=:gun", gun=f["gun"])
            execute(db, "INSERT INTO meter_sample VALUES(:id,:a,100),(:id,:b,101),(:id,:future,500)",
                    id=f["order"], a=f["started"], b=f["started"] + timedelta(minutes=1), future=f["started"] + timedelta(hours=1))

    def test_progress_uses_past_meter_and_enforces_ownership(self):
        self.progress_fixture()
        result = self.client().get(f"/orders/{self.fx['order']}")
        self.assertEqual(result.status_code, 200, result.get_json())
        value = result.get_json()
        self.assertEqual(Decimal(value["latest_meter"]["reading_kwh"]), 101)
        self.assertEqual(Decimal(value["progress"]["metered_kwh"]), 1)
        self.assertEqual(Decimal(value["progress"]["estimated_gross"]), 1)
        self.assertEqual(value["progress"]["cost_basis"], "measured_average_power_estimate")
        self.assertNotIn("soc", value["progress"])
        self.assertEqual(self.client("other").get(f"/orders/{self.fx['order']}").status_code, 404)
        self.assertEqual(self.client("admin").get(f"/orders/{self.fx['order']}").status_code, 200)

    def test_missing_or_decreasing_meter_is_not_fabricated(self):
        self.progress_fixture()
        f = self.fx
        with engine.begin() as db:
            execute(db, "DELETE FROM meter_sample WHERE order_id=:id AND sampled_at=:at", id=f["order"], at=f["started"])
        value = self.client().get(f"/orders/{f['order']}").get_json()
        self.assertEqual(value["progress"]["data_quality"], "missing_start_reading")
        self.assertIsNone(value["progress"]["metered_kwh"])
        self.assertIsNone(value["progress"]["estimated_gross"])
        with engine.begin() as db:
            execute(db, "INSERT INTO meter_sample VALUES(:id,:a,100),(:id,:b,102)",
                    id=f["order"], a=f["started"], b=f["started"] + timedelta(seconds=30))
        value = self.client().get(f"/orders/{f['order']}").get_json()
        self.assertEqual(value["progress"]["data_quality"], "non_monotonic")
        self.assertIsNone(value["progress"]["metered_kwh"])
        with engine.begin() as db:
            execute(db, "DELETE FROM meter_sample WHERE order_id=:id", id=f["order"])
        value = self.client().get(f"/orders/{f['order']}").get_json()
        self.assertEqual(value["progress"]["data_quality"], "awaiting_meter")
        self.assertIsNone(value["latest_meter"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
