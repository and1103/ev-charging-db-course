"""Credit-billed fleet examples; no pretend cash payment is recorded."""
from pathlib import Path
import sys

for _project_root in Path(__file__).resolve().parents:
    _app_root = _project_root / '01_平台工程'
    if (_app_root / 'project_paths.py').is_file():
        sys.path.insert(0, str(_app_root))
        break
else:
    raise RuntimeError('请从完整的数据库设计第二版工程运行此脚本。')

from deploy import mysql_engine


def main():
    from local_runtime import load_runtime
    load_runtime()
    with mysql_engine().begin() as db:
        if db.exec_driver_sql("SELECT 1 FROM charge_migration WHERE name='seed_fleet.py'").scalar():
            return
        for n in range(1,21):
            if not db.exec_driver_sql('SELECT id FROM wallet_entry WHERE account_id=%s AND payment_id IS NULL AND refund_id IS NULL AND `change`=100',(n,)).scalar():
                db.exec_driver_sql("INSERT INTO wallet_entry(account_id,`change`,happened_at) VALUES(%s,100,'2026-10-31 00:00')",(n,))
            db.exec_driver_sql("INSERT INTO charge_order(account_id,connector_id,vehicle_id,tariff_id,fleet_card_id,started_at,state) VALUES(%s,%s,%s,%s,%s,'2026-11-05 12:00','charging')",(n,n,n,n,n))
            order=db.exec_driver_sql('SELECT LAST_INSERT_ID()').scalar_one()
            db.exec_driver_sql("INSERT INTO meter_sample VALUES(%s,'2026-11-05 12:00',100),(%s,'2026-11-05 12:10',102)",(order,order))
            db.exec_driver_sql("CALL finish_charge(%s,'2026-11-05 12:10',false)",(order,))
        db.exec_driver_sql("INSERT INTO charge_migration VALUES('seed_fleet.py')")
    print('20 fleet credit bills and opening wallet balances are available.')


if __name__=='__main__':
    main()
