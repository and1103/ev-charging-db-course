"""Canonical paths for the integrated second edition; no duplicate SQL sources."""
from pathlib import Path
import hashlib

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
SQL_ROOT = PROJECT_ROOT / '02_数据库脚本'
DESIGN_ROOT = PROJECT_ROOT / '03_需求与设计'
TEST_ROOT = PROJECT_ROOT / '04_测试与验收'
BACKUP_ROOT = PROJECT_ROOT / '05_备份与恢复'
TASK_ROOT = PROJECT_ROOT / '06_任务资料与小组分工'
PROCESS_ROOT = PROJECT_ROOT / '过程文件'
CURRENT_RECORDS = PROCESS_ROOT / '本次整合'
EDITION = 'database_design_v2'
INSTANCE_ID = hashlib.sha256(str(APP_ROOT.resolve()).casefold().encode('utf-8')).hexdigest()[:16]
BUSINESS_SQL_DIRS = {
    'A': SQL_ROOT / 'A_场站设施与排队',
    'B': SQL_ROOT / 'B_充电订单与计费',
    'C': SQL_ROOT / 'C_设备监控与故障工单',
    'D': SQL_ROOT / 'D_用户与会员运营',
    'E': SQL_ROOT / 'E_结算与对账',
}


def business_sql_path(member, filename):
    return BUSINESS_SQL_DIRS[member] / filename
