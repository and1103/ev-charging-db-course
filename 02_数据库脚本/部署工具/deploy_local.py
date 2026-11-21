"""Deploy to the dedicated local course schema with a temporary routine-creation setting."""
import sys
from pathlib import Path

for _project_root in Path(__file__).resolve().parents:
    _app_root = _project_root / '01_平台工程'
    if (_app_root / 'project_paths.py').is_file():
        sys.path.insert(0, str(_app_root))
        break
else:
    raise RuntimeError('请从完整的数据库设计第二版工程运行此脚本。')

from deploy import main, mysql_engine


if __name__ == '__main__':
    from local_runtime import load_runtime
    load_runtime()
    engine = mysql_engine()
    with engine.connect() as server:
        previous = server.exec_driver_sql('SELECT @@GLOBAL.log_bin_trust_function_creators').scalar_one()
        try:
            if not previous:
                server.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=1')
            main()
        finally:
            if not previous:
                server.exec_driver_sql('SET GLOBAL log_bin_trust_function_creators=0')
    print('Temporary routine-creation setting restored.')
