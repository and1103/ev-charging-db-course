"""Add coherent refund, review, bilateral-confirmation and invoice teaching cases."""
from datetime import datetime
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
        if db.exec_driver_sql("SELECT 1 FROM charge_migration WHERE name='seed_extended.py'").scalar():
            print('Extended scenarios already loaded.')
            return
        for n in range(1,21):
            db.exec_driver_sql("INSERT INTO charge_order(account_id,connector_id,vehicle_id,tariff_id,started_at,state) VALUES(%s,%s,%s,%s,'2026-11-02 17:55','charging')",(n,n,n,n))
            order=db.exec_driver_sql('SELECT LAST_INSERT_ID()').scalar_one()
            db.exec_driver_sql('INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(%s,%s,100),(%s,%s,104),(%s,%s,110)',
                               (order,datetime(2026,11,2,17,55),order,datetime(2026,11,2,18),order,datetime(2026,11,2,18,6)))
            db.exec_driver_sql("CALL finish_charge(%s,'2026-11-02 18:06',false)",(order,))
            pay=db.exec_driver_sql("SELECT post_payment(%s,%s,'mock',%s,11.40,true)",(n,order,f'extended-payment-{n}')).scalar_one()
            db.exec_driver_sql('SELECT post_refund(%s,%s,0.40)',(pay,f'extended-refund-{n}'))
            db.exec_driver_sql("INSERT INTO charge_order(account_id,connector_id,vehicle_id,tariff_id,started_at,state) VALUES(%s,%s,%s,%s,'2026-11-03 12:00','charging')",(n,n,n,n))
            review=db.exec_driver_sql('SELECT LAST_INSERT_ID()').scalar_one()
            db.exec_driver_sql("INSERT INTO meter_sample VALUES(%s,'2026-11-03 12:00',200),(%s,'2026-11-03 12:02',201)",(review,review))
            db.exec_driver_sql("CALL finish_charge(%s,'2026-11-03 12:02',true)",(review,))
            settlement=db.exec_driver_sql("SELECT id FROM settlement WHERE station_id=%s AND period='2026-11-01'",(n,)).scalar_one()
            db.exec_driver_sql('CALL reset_bill_import(%s)',(settlement,))
            db.exec_driver_sql("CALL build_settlement(%s,'2026-11-01')",(n,))
            expected=db.exec_driver_sql('SELECT order_id,kwh,amount,true paid FROM v_recon_expected WHERE settlement_id=%s ORDER BY order_id',(settlement,)).all()
            db.exec_driver_sql('CALL begin_bill_import(%s,%s,%s)',(settlement,'extended',len(expected)))
            for index,row in enumerate(expected):
                oid,kwh,amount,paid=row
                db.exec_driver_sql('INSERT INTO external_bill VALUES(%s,%s,%s,%s,%s,%s)',
                                   (settlement,oid,'extended',kwh,amount+(1 if index==0 else 0),paid))
            db.exec_driver_sql('CALL compare_settlement(%s)',(settlement,))
            differences=db.exec_driver_sql('SELECT id FROM recon_diff WHERE settlement_id=%s',(settlement,)).scalars().all()
            for diff in differences:
                db.exec_driver_sql("CALL confirm_difference(%s,501,'accept')",(diff,))
                db.exec_driver_sql("CALL confirm_difference(%s,%s,'accept')",(diff,n+100))
            db.exec_driver_sql('CALL confirm_settlement(%s,501)',(settlement,))
            db.exec_driver_sql('CALL confirm_settlement(%s,%s)',(settlement,n+100))
            db.exec_driver_sql("INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount) VALUES(%s,'教学运营商发票','DEMO-TAX',1)",(settlement,))
            invoice=db.exec_driver_sql('SELECT LAST_INSERT_ID()').scalar_one()
            db.exec_driver_sql("INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount,original_id) VALUES(%s,'教学红冲','DEMO-TAX',1,%s)",(settlement,invoice))
            request=db.exec_driver_sql('SELECT id FROM consumer_invoice_request WHERE order_id=%s',(n,)).scalar_one()
            db.exec_driver_sql("CALL issue_consumer_invoice(%s,501,'DEMO-DRIVER',1)",(request,))
            invoice=db.exec_driver_sql('SELECT id FROM consumer_invoice WHERE request_id=%s AND original_id IS NULL',(request,)).scalar_one()
            db.exec_driver_sql('CALL reverse_consumer_invoice(%s,501)',(invoice,))
        db.exec_driver_sql("INSERT INTO charge_migration VALUES('seed_extended.py')")
    print('20 coherent extended scenario sets loaded.')


if __name__=='__main__':
    main()
