"""Compare the 15 SQL pairs and print representative MySQL execution plans."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from business_lines import BUSINESS_LINES
from deploy import mysql_engine, sql_statements

with mysql_engine().connect().execution_options(isolation_level="REPEATABLE READ") as db:
    db.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
    for member, line in BUSINESS_LINES.items():
        path = ROOT / member / line / "queries.sql"
        queries = list(sql_statements(path.read_text(encoding="utf-8")))
        assert len(queries) == 6
        for index in range(0, 6, 2):
            left, right = queries[index:index + 2]
            assert db.exec_driver_sql(left).all() == db.exec_driver_sql(right).all(), (member, index)
            if index == 0:
                for statement in (left, right):
                    for row in db.exec_driver_sql("EXPLAIN ANALYZE " + statement):
                        print(row[0])
        print(member, "3 query pairs matched")
