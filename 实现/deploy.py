import argparse
import os
from pathlib import Path
import re

from sqlalchemy import create_engine

from business_lines import BUSINESS_LINES

ROOT = Path(__file__).resolve().parent
MIGRATIONS = (
    "A/01_schema.sql", "D/02_schema.sql", "B/03_schema.sql",
    "A/04_queue.sql", "D/05_members.sql", "B/06_payment.sql",
    "C/07_monitor.sql", "E/08_settlement.sql",
)


def migration_path(name):
    member, filename = name.split("/", 1)
    line = "充电估算与到站排队" if filename == "04_queue.sql" else BUSINESS_LINES[member]
    return ROOT / member / line / filename


def sql_statements(source):
    delimiter = ";"
    lines = []
    for line in source.splitlines():
        line = line.rstrip()
        if line.upper().startswith("DELIMITER "):
            if lines:
                raise ValueError("unfinished SQL before DELIMITER")
            delimiter = line.split(maxsplit=1)[1]
            continue
        if not line or line.lstrip().startswith("--"):
            continue
        lines.append(line)
        if line.endswith(delimiter):
            yield "\n".join(lines)[:-len(delimiter)]
            lines.clear()
    if lines:
        raise ValueError("unfinished SQL at end of file")


def run_script(db, path):
    for sql in sql_statements(path.read_text(encoding="utf-8")):
        try:
            db.exec_driver_sql(sql)
        except Exception as error:
            raise RuntimeError(f"{path.name}: {sql.splitlines()[0]}") from error


def mysql_engine(name="CHARGE_ADMIN_DSN"):
    url = os.environ[name]
    if not url.startswith("mysql+pymysql://"):
        raise ValueError(f"{name} must use mysql+pymysql://")
    return create_engine(url, isolation_level="READ COMMITTED",
                         execution_options={"no_parameters": True},
                         connect_args={"init_command": "SET time_zone = '+08:00'"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.demo and len(os.environ.get("CHARGE_DEMO_PASSWORD", "")) < 10:
        parser.error("CHARGE_DEMO_PASSWORD must have at least 10 characters")
    with mysql_engine().connect() as db:
        version = db.exec_driver_sql("SELECT VERSION()").scalar_one()
        if not re.match(r"^8\.(?:[4-9]|[1-9][0-9])\.", version):
            raise RuntimeError(f"MySQL 8.4 or later 8.x required, got {version}")
        db.exec_driver_sql("CREATE TABLE IF NOT EXISTS charge_migration (name varchar(255) PRIMARY KEY)")
        for name in MIGRATIONS:
            if db.exec_driver_sql("SELECT 1 FROM charge_migration WHERE name=%s", (name,)).scalar():
                continue
            run_script(db, migration_path(name))
            db.exec_driver_sql("INSERT INTO charge_migration VALUES (%s)", (name,))
            print(name)
        if args.demo and not db.exec_driver_sql("SELECT 1 FROM charge_migration WHERE name='seed.sql'").scalar():
            from auth import password_hash
            seed = list(sql_statements((ROOT / "seed.sql").read_text(encoding="utf-8")))
            create, *inserts, cleanup = seed
            db.commit()
            db.exec_driver_sql("DROP PROCEDURE IF EXISTS seed_charge_demo")
            db.exec_driver_sql(create)
            db.commit()
            try:
                for statement in inserts:
                    db.exec_driver_sql(statement)
                db.exec_driver_sql("UPDATE account SET password_hash=%s WHERE password_hash='demo-pending'",
                                   (password_hash(os.environ["CHARGE_DEMO_PASSWORD"]),))
                db.exec_driver_sql("INSERT INTO charge_migration VALUES ('seed.sql')")
                db.commit()
            finally:
                if db.in_transaction():
                    db.rollback()
                db.exec_driver_sql(cleanup)
                db.commit()
        db.commit()


if __name__ == "__main__":
    main()
