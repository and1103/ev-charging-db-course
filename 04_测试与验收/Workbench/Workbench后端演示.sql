-- 充电桩运营平台：真实课设数据库（只读展示）
USE charge_course_20261114;

-- 1. 数据库规模：44张业务表，19个视图
SELECT VERSION() AS MySQL版本, DATABASE() AS 当前课设库, @@port AS 端口,
 (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' AND TABLE_NAME<>'charge_migration') AS 业务表数量,
 (SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA=DATABASE()) AS 视图数量;

-- 2. 场站、桩、枪资产主链
SELECT s.id AS 场站号,s.name AS 场站,c.id AS 桩编号,g.id AS 枪编号,g.kind AS 枪型,g.state AS 枪状态
FROM station s JOIN charger c ON c.station_id=s.id JOIN connector g ON g.charger_id=c.id ORDER BY s.id,g.id LIMIT 10;

-- 3. 原价11.40，优惠2.00，实收9.40，待付0
SELECT id AS 订单号,state AS 状态,gross AS 原价,discount AS 优惠,received AS 累计收款,refunded AS 已退款,net_due AS 实际应付,outstanding AS 待付
FROM v_order_balance WHERE id BETWEEN 1 AND 5 ORDER BY id;

-- 4. 订单1的分时电量、电费、服务费
SELECT order_id AS 订单号,begins AS 分段开始,ends AS 分段结束,label AS 时段,kwh AS 电量,energy AS 电费,service AS 服务费
FROM fee_detail WHERE order_id=1 ORDER BY begins;

-- 5. 分次付款流水
SELECT order_id AS 订单号,channel AS 渠道,reference AS 流水号,amount AS 金额,succeeded AS 成功
FROM payment WHERE order_id=1 ORDER BY id;

-- 6. 钱包余额与冻结，只显示脱敏信息
SELECT id AS 用户编号,phone_mask AS 脱敏手机号,balance AS 余额,reserved_balance AS 冻结,balance-reserved_balance AS 可用余额
FROM account WHERE id BETWEEN 1 AND 5 ORDER BY id;

-- 7. 桩枪告警与恢复历史
SELECT id AS 告警号,charger_id AS 桩编号,connector_id AS 来源枪编号,code AS 告警码,severity AS 等级,
 CASE WHEN restored_at IS NULL THEN '活动' ELSE '已恢复' END AS 告警状态,opened_at AS 发生时间,restored_at AS 恢复时间
FROM alarm ORDER BY id LIMIT 10;

-- 8. 企业车队月账单
SELECT * FROM v_fleet_month ORDER BY fleet_id,period LIMIT 5;

-- 9. 运营商结算与开票余额
SELECT id AS 结算号,station_id AS 场站,operator_id AS 运营商,period AS 账期,state AS 状态,due AS 应结,invoiced AS 净开票,remaining AS 剩余额度
FROM v_invoice_balance ORDER BY id LIMIT 5;

-- 10. 结算双方签字（平台与运营商）
SELECT settlement_id AS 结算号,side AS 确认方,actor AS 确认人 FROM settlement_confirmation ORDER BY settlement_id,side LIMIT 10;
