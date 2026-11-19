"""Run against a disposable MySQL demo database."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
import sys

from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deploy import mysql_engine


def main():
    engine = mysql_engine()
    sql = "SELECT open_charge(%s,%s,1,NULL)"
    ready = Event()
    with engine.begin() as db:
        db.exec_driver_sql("UPDATE charger SET heartbeat=SYSDATE(6) WHERE id=1")

    def second():
        with engine.connect() as db:
            db.exec_driver_sql("SET innodb_lock_wait_timeout=5")
            ready.set()
            try:
                db.exec_driver_sql(sql, (2, 2))
            except DBAPIError as error:
                if error.orig.args[0] in {1062, 1644}:
                    return
                raise
            raise AssertionError("second order was accepted")

    order_id = None
    try:
        with engine.connect() as first, ThreadPoolExecutor(max_workers=1) as pool:
            order_id = first.exec_driver_sql(sql, (1, 1)).scalar_one()
            result = pool.submit(second)
            assert ready.wait(5)
            first.commit()
            result.result(timeout=8)
    finally:
        if order_id is not None:
            with engine.begin() as db:
                db.exec_driver_sql("UPDATE charge_order SET state='cancelled' WHERE id=%s AND state='charging'", (order_id,))
                db.exec_driver_sql("UPDATE connector SET state='idle' WHERE id=1 AND state='occupied'")
    print("concurrent charging passed")


if __name__ == "__main__":
    main()
