# 测试与验收：从哪里运行、验证什么

主入口只有项目根目录的 **运行验证.cmd**，实际实现为本目录 `run_checks.py`。它按位置参数选择组；不传参数等于quick。`运行验证.py`及旧API验证入口只转发到同一实现。

## 常用操作

在第二版根目录打开终端：

```powershell
.\运行验证.cmd
.\运行验证.cmd api
.\运行验证.cmd workbench
.\运行验证.cmd all --start-http
```

第一条执行quick，默认不启动网页。all中的HTTP检查如需临时启动，请加`--start-http`，测试后在finally关闭临时服务；原先已运行且身份匹配的第二版服务不被自动关闭。旧版占用5000端口时拒绝复用，须先关旧版。

## 各组范围

| 参数 | 实际验证 | 是否连接/修改数据库 |
|---|---|---|
| quick | unit＋schema＋queries＋client-contract | 含只读结构和查询，不启动服务 |
| unit | 13项启动停止＋5项运行路径/配置保护＋4项管理员任务派发，共22项 | 不连数据库；浏览器、进程和管理员数据库动作mock |
| schema | 断言44业务基表、320基表字段、19视图、25过程＋15函数、每表至少20行；导出字段/约束/索引CSV | 应用账号只读；触发器完整性默认标记not_verified |
| queries | A—E每线3题、每题两种实现，共15对SQL在一致性只读快照中比较 | 只读；记录非空/空对数 |
| client-contract | 16项CSV解析、行数/数值/布尔值和北京时间检查 | 纯Node，无数据库 |
| api | 34项真实Flask＋MySQL集成测试：权限、CRUD、分页、资金并发、幂等、回滚、网页衔接 | 会写入合成夹具，见下文 |
| workbench | 两份Workbench脚本自动执行；固定金额与一笔新A—E闭环 | 只读展示＋UUID事务，最终回滚 |
| http | 18项真实HTTP：Cookie登录、CSRF、令牌轮换、本人订单、越权、注销 | 需要第二版服务，登录计数可能清零 |
| dom | 采集6角色GET响应，再用jsdom验证66个本地DOM场景 | GET只读；不是浏览器验收 |
| all | quick＋api＋workbench＋http＋dom | 不含管理员SQL回归、建库或恢复 |
| sql-regression | 6份临时存储过程中的资金/核价边界/工单/结算回归 | 需显式管理员；有CREATE/DROP ROUTINE，业务数据事务回滚 |
| legacy-gun | 旧版同枪竞争脚本，保留以便追溯和单独复现 | 会刷新种子枪心跳、保留取消单，不默认运行 |

脚本不会将历史PASS当作本轮结果。输出全部在 `过程文件/本次整合/验证结果/时间戳/`，最近一次指针为该目录的`最近一次.json`。分组日志只保存测试名、结果、数量和异常类型，不保存原始SQL参数、连接串、口令或完整堆栈。

## 前置条件与副作用

- DB组使用本机127.0.0.1:3307、charge_course_20261114及当前Windows用户的加密运行配置；测试前MySQL需可连接。
- schema的320字段只统计44张业务基表，排除视图字段及charge_migration。默认schema通过表示这些明确的核心检查通过，**不表示触发器已经完整核对**：应用账号可能看不到TRIGGER元数据，输出`triggers:null`、`trigger_metadata.status=not_verified`和`complete_metadata_verified=false`，不能把不可见的空列表解释为实库没有触发器。DDL声明的54个触发器单列为`declared_triggers`，与实库观察分开。
- API测试多数私有UUID夹具会在finally清理。基础用例会刷新种子桩1状态和心跳，并保留取消的合成订单；自增ID空号正常。不能将它称为全库零写入。
- Workbench脚本不含DDL/COMMIT，正常结尾回滚。手动执行途中报错时，在同一连接执行ROLLBACK后重跑。单标签顺序操作不证明并发。
- `queries`通过只证明两种写法在当前数据下结果一致。空集不证明正向场景充分；仍须补非空/边界样例及独立手算预期。
- 执行计划是查询诊断，不等于已证明优化收益。需在独立性能库相同条件下做优化前后对照。
- DOM测试仅代码渲染，7个合成状态分支明确标注；实际浏览器排版、鼠标/键盘及端到端写事务另行验收。

## 开发工具依赖

平台运行不依赖Node；`client-contract`与`dom`开发检查需要Node.js。DOM依赖只在本目录：

```powershell
npm ci --prefix "04_测试与验收/DOM模块测试" --no-audit --no-fund
.\运行验证.cmd dom
```

## 管理员回归与维护

`维护工具/inspect_schema.py --admin`必须由运行者显式提供`CHARGE_ADMIN_DSN`，用有足够元数据权限的管理员只读核验。它仍执行全部核心断言，并要求实库可见触发器集合与正式DDL中的54个名称完全相同；缺失或额外对象都会失败。仅当这些检查均通过时，才输出`complete_metadata_verified=true`。应用账号默认导出的未知范围不能回填成管理员已核验结果。

`sql-regression`要求运行者在进程环境显式提供`CHARGE_ADMIN_DSN`。脚本限制为本地3307课设库；不会从DPAPI猜出root密码，也不把口令写到文档。应用账号默认没有建/删例程权限。

`查询与并发/check_queries.py --explain`可额外记录每线首题两种写法的EXPLAIN ANALYZE，需能查看相应视图定义的账号。默认queries不要求SHOW VIEW。

`维护工具/run_sql.py`是明确执行并 **COMMIT** 选定项目SQL的工具，不是预览器。范围限制为02数据库和04测试目录，调用前阅读SQL，DDL会隐式提交；不要将任意业务更新SQL当只读验收运行。

`历史维护工具`中的旧升级/旧验收聚合器用于追溯，不是第二版默认入口，具体用途见该目录说明。新库重建入口在02，备份恢复入口在05，均要求明确新库名，始终拒绝覆盖已存在数据库。
