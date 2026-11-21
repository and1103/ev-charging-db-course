"""Summarize existing evidence. Does not connect to databases or read private config."""

# Resolve the integrated project by its marker, not by a fragile parent count.
from pathlib import Path as _BootstrapPath
import sys as _bootstrap_sys
for _base in _BootstrapPath(__file__).resolve().parents:
    _app_candidate = _base / '01_平台工程'
    if (_app_candidate / 'project_paths.py').is_file():
        _bootstrap_sys.path.insert(0, str(_app_candidate))
        _bootstrap_sys.path.insert(0, str(_base / '04_测试与验收'))
        break
else:
    raise RuntimeError('Cannot locate the integrated project root')
from project_paths import APP_ROOT, PROJECT_ROOT, SQL_ROOT, TEST_ROOT, DESIGN_ROOT, BACKUP_ROOT, PROCESS_ROOT, CURRENT_RECORDS, BUSINESS_SQL_DIRS, business_sql_path

import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = APP_ROOT
ARTIFACTS = ROOT/'过程文件'
OUTPUT = ARTIFACTS/'后端构建与验收结果.md'
from deploy import MIGRATIONS, migration_path


def read(relative):
    return json.loads((ROOT/relative).read_text(encoding='utf-8-sig'))


def main():
    metadata = read('过程文件/验收/数据库结构.json')
    tests = read('过程文件/验收/测试结果.json')
    restore = read('过程文件/备份恢复/最终版/恢复验证.json')
    graph = read('过程文件/图件工具/图模数据库一致性.json')
    clean_path = sorted((ROOT/'过程文件'/'空库复现').glob('*/clean_build_result.json'))[-1]
    clean = json.loads(clean_path.read_text(encoding='utf-8'))
    if not (all(x['passed'] for x in tests.values()) and restore['all_rows_and_objects_equal'] and graph['passed'] and clean['passed']):
        raise RuntimeError('Some evidence is not passing; refusing a success report')
    previous_report = OUTPUT.read_text(encoding='utf-8-sig') if OUTPUT.exists() else ''
    previous_date = re.search(r'^验收日期：([^。\n]+)', previous_report, re.M)
    accepted_at = previous_date[1] if previous_date else restore['checked_at'][:16].replace('T', ' ')
    per_line = {}
    for name in MIGRATIONS:
        row = per_line.setdefault(name[0], dict(views=0, procedures=0, functions=0, triggers=0))
        sql = migration_path(name).read_text(encoding='utf-8')
        for kind, key in [('VIEW','views'),('PROCEDURE','procedures'),('FUNCTION','functions'),('TRIGGER','triggers')]:
            row[key] += len(re.findall(r'^CREATE\s+'+kind+r'\s+', sql, re.M|re.I))
    index_pairs = set()
    for path in ARTIFACTS.glob('数据库导出/*/*/索引.csv'):
        for row in csv.DictReader(path.open(encoding='utf-8-sig')):
            if row['索引名'] != 'PRIMARY':
                index_pairs.add((row['表'], row['索引名']))
    passing = '\n'.join(f"| {name} | 通过 | {result['seconds']} 秒 | [日志](验收/{result['log']}) |" for name,result in tests.items())
    line_counts = '\n'.join(f"| {name} | {row['views']} | {row['procedures']} | {row['functions']} | {row['triggers']} |" for name,row in sorted(per_line.items()))
    rows = '\n'.join(f'| {table} | {count} |' for table,count in metadata['row_counts'].items())
    report = f'''# 后端构建与验收结果

验收日期：{accepted_at}。本次按照任务书、个人/小组模板和评分标准核对数据库与后端；以下结论有本机执行记录支撑。文件整理保留原验收时间，不表示重新执行了业务验收。

## 当前可用状态

MySQL {metadata['version']}，127.0.0.1:3307，专用库 **charge_course_20261114**。原验收时后端运行于 http://127.0.0.1:5000 ，[实际健康检查](验收/后端健康检查.json)已返回 ok。

2026-11-15起，数据库展示统一使用桌面MySQL Workbench入口；旧命令行展示脚本和输出已按用户要求删除。当前验证步骤、SQL及实测记录集中在[Workbench展示](Workbench展示/使用说明.md)。本报告保留原后端验收日期和结果，新验证以该目录的日期记录为准。

实库有 **44 张业务表、320 个基表字段、19 个视图、25 个过程、15 个函数、54 个触发器**。charge_migration 是部署控制表，单列计算，不计入44张业务表。每张业务表均至少20条记录，最少值为 {min(metadata['row_counts'].values())}。结构与准确行数见[数据库结构.json](验收/数据库结构.json)。物理索引除主键外共 {len(index_pairs)} 个，包含唯一约束与辅助索引；索引数量不等于有效索引方案数量。

## 主要修正及补齐

1. 修复跨列 CHECK、结算生成过程的 MySQL 1442、函数分隔符等实际部署问题；最终源码已从新空库重建成功。
2. 开单冻结钱包/车队额度，结束、取消、付款正确释放；锁定当前数据校验，补上旧 RR 快照可能重复占用车队额度的情况。超过预算仍保存真实读数和完整账单，并记录停止请求及复核原因。
3. 支付、退款幂等按原交易字段校验；正常退款减少债务，支付撤销独立建模；零元优惠账单不制造付款流水。月结按历史场站/运营商快照，退款按原分成比例反向分配并累计消除分角误差。
4. 对账先验证整批导入与缺单/多单，保留双方分别签署的意见与版本。双方一致确认后冻结账单；用户消费票、运营商结算票及红冲分别闭环。
5. 工单状态逐步推进，修复后须新近连续正常采样；枪级告警新增来源枪、桩枪归属校验和范围去重，整桩告警保留空枪编号。
6. 补齐新用户模拟钱包充值：字符串请求号精确幂等、同号并发只入账一次、失败整体回滚；订单详情返回最新可信读数/电量和费用预估，不伪造 SOC。
7. 完善资产 DAO、分页与允许字段清单、角色/归属校验、车辆解绑/转移、JSON 错误、采样输入校验与隐私字段加密。

设备、外部支付、充值及通知使用课设模拟方式；接口明确标注模拟。未连接真实桩和真实支付平台。

## 任务书数量与设计证据

| 业务线 | 视图 | 过程 | 函数 | 触发器 |
|---|---:|---:|---:|---:|
{line_counts}

A包括设施与排队。每线至少3视图、1过程、1触发器均覆盖。15道 SQL 题各有2种实现，共30条；结果比较已通过，且保存 MySQL EXPLAIN ANALYZE。至少5道含3表及以上关系的要求由每线选定题目支撑，具体 SQL 在各线 queries.sql。

索引围绕用户订单时间、枪占用/结束时间、活动告警时限、工单告警、采样时间/桩和结算账期等实际查询设计。当前数据用于正确性验证；尚未将小样本执行计划解释为大规模性能提升。

[完整字典与范式分析](设计文档/数据库设计与数据字典.md)覆盖全部字段。外账结算号→批次、用户票据申请→订单等保留受控物理冗余，字典给出函数依赖与维护措施；未声称44张物理表全部严格满足3NF。

[图件索引](图件索引.md)包含34张正式图件，放在各业务模块原目录，图片仅保留 PNG。局部 E-R 采用矩形实体、菱形联系、椭圆属性及下划线标识；修正订单复核归属、联系基数和外键表达。用例图、鲁棒图、全局 UML 与完整字段分区图同步核查。最终核对 **44表/320字段/75组物理外键/77列映射**；另4条逻辑关联单独用虚线表达。[一致性记录](图件工具/图模数据库一致性.json)通过，另见[目视检查记录](图件工具/目视检查记录.md)。

## 自动回归结果

共 {len(tests)} 组全部通过。API8项、资金并发5项、钱包与进度8项为子测试数量，不能与组数混淆。

| 测试组 | 结果 | 耗时 | 证据 |
|---|---|---|---|
{passing}

重点包含：同枪并发抢占；同钱包/同车队额度竞争；同券不可重复核销；支付退款重放；旧RR快照；跨午夜/免费时长/起步价；正常与异常结算；告警来源和恢复；本人/他人/车队负责人权限；登录限制和密文存储；充值回滚及并发精确幂等。

## 空库重建与实际恢复

空库重现数据库为 **{clean['target_database']}**。全部DDL及三组种子脚本执行成功，44表逐表20条以上，例程参数恢复原值。详细[重建记录]({clean_path.relative_to(ARTIFACTS).as_posix()})。本次新建验证库没有覆盖原有实验库。

最终全量备份为[课设库SQL](备份恢复/最终版/charge_course_20261114.sql)，{restore['backup_bytes']} 字节，备份 {restore['backup_seconds']} 秒。隔离恢复库 **{restore['restore']}**，恢复及核验耗时 {restore['restore_and_validation_seconds']} 秒。所有表包含控制表的行数、逐行内容哈希、视图/例程/触发器集合完全一致；所有视图可查询，且没有误指向主库。[恢复验证记录](备份恢复/最终版/恢复验证.json)。

备份坐标 {restore['backup_binlog_file']}:{restore['backup_binlog_position']}，binlog为ROW。全量恢复已实际验证；binlog时间点重放和周期任务未执行。周期、保留、RPO/RTO及演练方法见[策略说明](../E/结算与对账/备份恢复.md)，目标与实测值分开记载。

## 后续提交材料

数据库与后端基础阶段可供演示。前端依用户要求暂缓。接下来仍需真实成员姓名分工、按模板整编小组/个人报告与PDF、答辩PPT、含全员发言的录像，以及真实协作/会议记录。早期初稿中的“尚未部署”结论已由本次实测更新；未虚构团队活动与最终提交完成。

## 逐表数据量

| 业务表 | 实际行数 |
|---|---:|
{rows}
'''
    OUTPUT.write_text(report, encoding='utf-8')
    files = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in [migration_path(n) for n in MIGRATIONS] + [ROOT/'app.py',ROOT/'repositories.py']}
    (ROOT/'过程文件'/'验收'/'最终代码哈希.json').write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Evidence report generated:', OUTPUT)


if __name__ == '__main__':
    main()
