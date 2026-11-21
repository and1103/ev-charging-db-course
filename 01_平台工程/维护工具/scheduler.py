"""Run one explicit maintenance sweep; importing this file never writes data."""
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
    with mysql_engine("CHARGE_DATABASE_URL").begin() as db:
        db.exec_driver_sql("CALL scan_offline()")
        db.exec_driver_sql("CALL escalate_alarms(SYSDATE(6))")
        ids = db.exec_driver_sql("SELECT id FROM station ORDER BY id").scalars().all()
        for station_id in ids:
            db.exec_driver_sql("CALL dispatch_station(%s)", (station_id,))
    print('已完成一次离线、告警时限和排队调度扫描。未安装周期任务。')


if __name__ == '__main__':
    main()
