"""Export an exact field and constraint inventory from the deployed MySQL schema."""
import csv
from pathlib import Path

from deploy import mysql_engine

from business_lines import BUSINESS_LINES

ROOT = Path(__file__).resolve().parent
TABLES = {
    "A": "operator station charger connector asset_history asset_request ",
    "B": "tariff tariff_band charge_order meter_sample fee_detail order_review payment refund",
    "C": "telemetry alarm_rule alarm work_order work_part alarm_notice",
    "D": "account vehicle vehicle_binding fleet fleet_card campaign coupon wallet_entry redemption consumer_invoice_request driver_feedback",
    "E": "settlement settlement_item external_bill recon_diff diff_confirmation settlement_adjustment settlement_invoice",
}
FIELDS = """
SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,EXTRA,COLUMN_DEFAULT,COLUMN_COMMENT
FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN %s
ORDER BY TABLE_NAME,ORDINAL_POSITION
"""
CONSTRAINTS = """
SELECT t.TABLE_NAME,t.CONSTRAINT_NAME,t.CONSTRAINT_TYPE,k.COLUMN_NAME,
       k.REFERENCED_TABLE_NAME,k.REFERENCED_COLUMN_NAME,c.CHECK_CLAUSE
FROM information_schema.TABLE_CONSTRAINTS t
LEFT JOIN information_schema.KEY_COLUMN_USAGE k USING(CONSTRAINT_SCHEMA,TABLE_NAME,CONSTRAINT_NAME)
LEFT JOIN information_schema.CHECK_CONSTRAINTS c USING(CONSTRAINT_SCHEMA,CONSTRAINT_NAME)
WHERE t.TABLE_SCHEMA=DATABASE() AND t.TABLE_NAME IN %s ORDER BY 1,2,k.ORDINAL_POSITION
"""
INDEXES = """
SELECT TABLE_NAME,INDEX_NAME,COLUMN_NAME,NON_UNIQUE,SEQ_IN_INDEX FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN %s ORDER BY 1,2,5
"""

DESTINATIONS = {
    (member, BUSINESS_LINES[member]): tables for member, tables in TABLES.items()
}
DESTINATIONS[("A", "充电估算与到站排队")] = "queue_entry queue_call gun_hold"

with mysql_engine().connect() as db:
    for (member, line), tables in DESTINATIONS.items():
        for filename, headers, sql in [
            ("字段.csv", ["表", "字段", "类型", "允许空值", "额外属性", "默认值", "说明"], FIELDS),
            ("约束.csv", ["表", "约束名", "约束类型", "字段", "引用表", "引用字段", "检查表达式"], CONSTRAINTS),
            ("索引.csv", ["表", "索引名", "字段", "非唯一", "列顺序"], INDEXES),
        ]:
            with (ROOT / member / line / filename).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(headers)
                writer.writerows(db.exec_driver_sql(sql, (tuple(tables.split()),)))

