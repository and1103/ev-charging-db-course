"""Run periodically with CHARGE_DATABASE_URL set."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deploy import mysql_engine

with mysql_engine("CHARGE_DATABASE_URL").begin() as db:
    db.exec_driver_sql("CALL scan_offline()")
    db.exec_driver_sql("CALL escalate_alarms(SYSDATE(6))")
    ids = db.exec_driver_sql("SELECT id FROM station ORDER BY id").scalars().all()
    for station_id in ids:
        db.exec_driver_sql("CALL dispatch_station(%s)", (station_id,))
