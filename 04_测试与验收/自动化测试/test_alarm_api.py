"""Real API gun-scope, access-control and restored-alarm visibility checks."""

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

import os
from pathlib import Path
import sys
import unittest
import uuid

from app import app
from deploy import mysql_engine


class AlarmAPI(unittest.TestCase):
    def login(self, name):
        client = app.test_client()
        reply = client.post('/auth/login', json={'login': name, 'password': os.environ['CHARGE_DEMO_PASSWORD']})
        self.assertEqual(reply.status_code, 200)
        return client

    def test_gun_source_and_history(self):
        admin = self.login('admin')
        driver = self.login('driver1')
        code = 'API-SCOPE-' + uuid.uuid4().hex
        engine = mysql_engine()
        with engine.begin() as db:
            gun, charger = db.exec_driver_sql('SELECT id,charger_id FROM connector ORDER BY id LIMIT 1').one()
            other_charger = db.exec_driver_sql('SELECT id FROM charger WHERE id<>%s LIMIT 1', (charger,)).scalar_one()
            db.exec_driver_sql('INSERT INTO alarm_rule VALUES(%s,2,10)', (code,))
        try:
            path = f'/demo/chargers/{charger}/alarms'
            self.assertEqual(driver.post(path, json={'code': code, 'connector_id': gun}).status_code, 403)
            self.assertEqual(admin.post(path, json={'code': code, 'connector_id': True}).status_code, 400)
            reply = admin.post(path, json={'code': code, 'connector_id': gun})
            self.assertEqual(reply.status_code, 201, reply.get_json())
            key = reply.get_json()['id']
            self.assertEqual(admin.post(path, json={'code': code, 'connector_id': gun}).get_json()['id'], key)
            self.assertEqual(admin.get(f'/alarms/{key}').get_json()['connector_id'], gun)
            self.assertEqual(driver.get(f'/alarms/{key}').status_code, 403)
            self.assertEqual(admin.post(f'/demo/chargers/{other_charger}/alarms',
                                       json={'code': code, 'connector_id': gun}).status_code, 409)
            with engine.begin() as db:
                db.exec_driver_sql('UPDATE alarm SET restored_at=SYSDATE(6) WHERE id=%s', (key,))
            self.assertEqual(admin.get(f'/alarms/{key}').get_json()['state'], 'restored')
        finally:
            with engine.begin() as db:
                db.exec_driver_sql('DELETE n FROM alarm_notice n JOIN alarm a ON a.id=n.alarm_id WHERE a.code=%s', (code,))
                db.exec_driver_sql('DELETE FROM alarm WHERE code=%s', (code,))
                db.exec_driver_sql('DELETE FROM alarm_rule WHERE code=%s', (code,))


if __name__ == '__main__':
    unittest.main(verbosity=2)
