# 充电桩运营服务平台 MySQL 实现

采用 MySQL 8.4、InnoDB、Python、PyMySQL、SQLAlchemy 和 Flask。数据库与后端在本目录，前端展示暂缓。

| 目录 | 职责 |
|---|---|
| A/场站与充电设施 | 场站、桩枪、验收、状态历史和数据库角色 |
| A/充电估算与到站排队 | 排队、叫号、留枪、扫码开单 |
| B/充电订单与计费 | 费率、分段核价、估价函数、支付退款 |
| C/设备监控与故障工单 | 遥测分区、告警工单、调度与集成测试 |
| D/用户与会员运营 | 用户、车辆、车队、券、账户和消费发票 |
| E/结算与对账 | 月结、逐单差异、开票和恢复说明 |

## 本地部署

在 MySQL 8.4 创建专用空库，默认字符集用 utf8mb4。部署账号需有表、视图、触发器和例程的创建权限。服务器启用了 binlog 时，具有管理权限的人员需为测试实例配置存储函数创建所需权限，或在独立实验实例按需设置 log_bin_trust_function_creators。日期时间统一用 DATETIME(6) 存储北京时间，连接会话使用 +08:00。MySQL 5.1 无法运行本项目。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:CHARGE_ADMIN_DSN = 'mysql+pymysql://部署用户:密码@127.0.0.1:3306/charge?charset=utf8mb4'
$env:CHARGE_DEMO_PASSWORD = '自行设置至少10位的演示密码'
.\.venv\Scripts\python.exe deploy.py --demo
.\.venv\Scripts\python.exe dictionary.py
```

SQL 按 01 至 08 执行，最后导入 seed.sql。MySQL DDL 会隐式提交。首次部署若中途失败，修正报错后在新的专用空库重新部署。迁移脚本用于创建 MySQL 空库，已有外部数据需要另行导入。

在 MySQL 客户端选中项目数据库，由 DBA 执行 A/场站与充电设施/09_roles.sql，再将 charge_api 角色授予应用登录账号并设置默认角色。权限授予范围限定在专用项目库。密码特殊字符在 URL 内使用百分号编码。

```powershell
$env:CHARGE_DATABASE_URL = 'mysql+pymysql://应用用户:密码@127.0.0.1:3306/charge?charset=utf8mb4'
$env:CHARGE_SESSION_SECRET = '自行配置长随机值'
$env:CHARGE_PII_KEY = & .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.\.venv\Scripts\python.exe app.py
```

PII 密钥保存在受限配置中并跨重启复用。API 监听 127.0.0.1:5000。登录用 POST /auth/login，JSON 包含 login、password。演示用户有 driver1、driver2、admin、tech1、settlement、operator1。

## 验收

在 MySQL 客户端选中演示库并执行 `SOURCE C/设备监控与故障工单/smoke.sql`。用 PowerShell 运行：

```powershell
.\.venv\Scripts\python.exe 'C/设备监控与故障工单/concurrency.py'
.\.venv\Scripts\python.exe 'C/设备监控与故障工单/check_queries.py'
```

并发测试使用专用演示库，结束后会保留取消订单。查询脚本检查 15 对等价查询并打印 MySQL EXPLAIN ANALYZE 结果。初始化提供 20 组核心样例，审计、差异确认和其他少见状态的逐表记录数需要单独核对。

## 演示流程

1. admin 调用 POST /demo/chargers/1/state，提交 {"state":"idle"} 刷新心跳。POST /admin/tick 执行离线、超时告警及排队扫描，也可定时运行 C 的 scheduler.py。
2. driver1 访问 GET /stations、GET /stations/1/guns；POST /estimate 提供 vehicle、gun、at、current_soc、target_soc。POST /queue 提供 vehicle 和 station，GET /queue 查看叫号。
3. 被叫号车主 POST /orders 提供 vehicle、gun。管理员用 /demo/order/{id}/readings 和 /demo/order/{id}/finish 提交读数及结束时间。GET /orders/{id} 查看账单。
4. 演示订单 1 的原价 11.40 元、优惠 2.00 元、实收 9.40 元。用 /orders/1/pay 重放 seed-a-1，金额 4、渠道 mock，核对流水不重复。
5. GET /settlements/1 查看预置差异，分别由平台和 operator1 通过 /differences/{id}/confirm 提交 accept；确认结算后办理开票。CSV 列为 order_id,kwh,amount,paid，paid 使用 true 或 false。
6. admin 模拟断连后检查 GET /alarms，派单后 /work/{id}/step 按 accept、arrive、repair、close 推进。闭环须填写 result。

## MySQL 结构选择

同枪进行中订单、同车同站有效排队和单枪有效留枪采用生成列与唯一索引。遥测采用时间范围分区和桩编号哈希子分区；分区表的桩编号由触发器校验。备份使用 mysqldump，时间点恢复用 binlog 和 mysqlbinlog。
