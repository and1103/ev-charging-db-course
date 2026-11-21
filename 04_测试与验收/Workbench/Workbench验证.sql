-- Workbench 后端验证：只读总览。
-- 每个 SELECT 产生一个结果网格。可选中一段执行，也可执行全文件。
-- “PASS/FAIL”来自实际查询条件；空结果不自动等于通过。
-- 不执行建表、写入或付款。可重复执行。
USE charge_course_20261114;

-- 01 环境与结构：当前专用课设库、3307端口、44业务表、19视图。
SELECT '01 环境和结构' AS 阶段,VERSION() AS MySQL版本,DATABASE() AS 当前库,@@port AS 端口,
 (SELECT COUNT(*) FROM information_schema.TABLES
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' AND TABLE_NAME<>'charge_migration') AS 业务表,
 (SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA=DATABASE()) AS 视图,
 CASE WHEN DATABASE()='charge_course_20261114' AND @@port=3307
  AND (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()
   AND TABLE_TYPE='BASE TABLE' AND TABLE_NAME<>'charge_migration')=44
  AND (SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA=DATABASE())=19
 THEN 'PASS' ELSE 'FAIL：核对连接或结构版本' END AS 判断;

-- 02 A线：场站—桩—枪的真实链路。状态是当前数据，不保证所有枪此刻可用。
SELECT '02 A 资产链' AS 阶段,s.id AS 场站号,s.name AS 场站,c.id AS 桩号,g.id AS 枪号,
 g.kind AS 枪型,c.rated_kw AS 桩功率,g.max_kw AS 枪功率,g.state AS 当前枪状态,
 IF(g.max_kw<=c.rated_kw,'PASS','FAIL') AS 功率约束
FROM station s JOIN charger c ON c.station_id=s.id JOIN connector g ON g.charger_id=c.id
ORDER BY s.id,g.id LIMIT 10;

-- 03 B线：固定订单1。应为 paid / 11.40 / 2.00 / 9.40 / 0.00 / 0.00。
SELECT '03 B 固定账单' AS 阶段,o.id AS 订单号,o.state AS 状态,o.gross AS 原价,o.discount AS 优惠,
 o.received AS 已收,o.refunded AS 已退,o.net_due AS 实际应付,o.outstanding AS 待付,
 CASE WHEN o.state='paid' AND o.gross=11.40 AND o.discount=2.00 AND o.received=9.40
 AND o.refunded=0 AND o.net_due=9.40 AND o.outstanding=0 THEN 'PASS' ELSE 'FAIL：固定样例已变化' END AS 判断
FROM v_order_balance o WHERE o.id=1;

-- 04 原始计量与分段账单一起看：原价来自哪些电量和时段。
SELECT '04 B 计量原始证据' AS 阶段,order_id AS 订单号,sampled_at AS 采样时刻,reading AS 累计电表读数
FROM meter_sample WHERE order_id=1 ORDER BY sampled_at;
SELECT '04 B 费用分段' AS 阶段,order_id AS 订单号,begins AS 开始时刻,ends AS 结束时刻,
 label AS 时段,kwh AS 电量,energy_rate AS 电价,service_rate AS 服务费率,
 energy AS 电费,service AS 服务费,estimated AS 边界是否插值
FROM fee_detail WHERE order_id=1 ORDER BY begins;

-- 05 支付拆分及幂等事实：应为2笔成功付款、4.00+5.40=9.40，无重复引用。
SELECT '05 B 付款明细' AS 阶段,id AS 付款号,channel AS 渠道,reference AS 幂等引用,amount AS 金额,succeeded AS 成功
FROM payment WHERE order_id=1 ORDER BY id;
SELECT '05 B 付款核对' AS 阶段,COUNT(*) AS 成功笔数,SUM(amount) AS 成功合计,
 IF(COUNT(*)=2 AND SUM(amount)=9.40 AND COUNT(DISTINCT channel,reference)=2,'PASS','FAIL') AS 判断
FROM payment WHERE order_id=1 AND succeeded;

-- 06 D线：钱包余额必须能回到资金流水，不展示密码、密文或完整身份信息。
SELECT '06 D 钱包与流水' AS 阶段,a.id AS 用户号,a.phone_mask AS 脱敏手机号,
 a.balance AS 余额,a.reserved_balance AS 冻结,a.balance-a.reserved_balance AS 可用,
 COALESCE(w.ledger_total,0) AS 流水净额,
 IF(a.balance=COALESCE(w.ledger_total,0) AND a.reserved_balance BETWEEN 0 AND a.balance,'PASS','FAIL') AS 判断
FROM account a LEFT JOIN (SELECT account_id,SUM(`change`) ledger_total FROM wallet_entry GROUP BY account_id) w ON w.account_id=a.id
WHERE a.id BETWEEN 1 AND 5 ORDER BY a.id;

-- 07 D线：优惠核销已真正落在订单，车队应付与实付分开显示。
SELECT '07 D 订单1优惠' AS 阶段,r.order_id AS 订单号,r.coupon_id AS 优惠券,r.discount AS 核销额,o.discount AS 订单优惠,
 IF(r.discount=o.discount,'PASS','FAIL') AS 判断
FROM redemption r JOIN charge_order o ON o.id=r.order_id WHERE r.order_id=1;
SELECT '07 D 车队月账单' AS 阶段,fleet_id AS 车队,period AS 月份,orders AS 订单数,
 amount AS 应付,paid AS 实付,outstanding AS 待付
FROM v_fleet_month ORDER BY fleet_id,period LIMIT 5;

-- 08 C线：恢复历史与工单时间链。查看非空的接单/到场/修复/关闭，不用“收到心跳”替代工单闭环。
SELECT '08 C 告警与工单' AS 阶段,a.id AS 告警号,a.charger_id AS 桩号,a.connector_id AS 来源枪,
 a.code AS 告警码,IF(a.restored_at IS NULL,'活动','已恢复') AS 告警状态,
 w.id AS 工单号,w.assigned_at AS 派单,w.accepted_at AS 接单,w.arrived_at AS 到场,
 w.repaired_at AS 修复,w.closed_at AS 关闭,a.restored_at AS 恢复
FROM alarm a LEFT JOIN work_order w ON w.alarm_id=a.id
ORDER BY (a.restored_at IS NULL),a.id,w.id LIMIT 10;

-- 09 E线：完整批次、单方/双方签字状态、未决差异，不直接修改已确认账单。
SELECT '09 E 对账及签字' AS 阶段,s.id AS 结算号,s.period AS 月份,s.state AS 状态,
 b.state AS 批次状态,b.expected_rows AS 声明行数,
 (SELECT COUNT(*) FROM external_bill x WHERE x.settlement_id=s.id) AS 实际行数,
 (SELECT COUNT(*) FROM settlement_confirmation x WHERE x.settlement_id=s.id) AS 签字方数,
 (SELECT COUNT(*) FROM v_pending_diff x WHERE x.settlement_id=s.id) AS 未决差异,
 CASE WHEN s.state IN ('confirmed','paid') THEN
  IF(b.state='complete' AND b.expected_rows=(SELECT COUNT(*) FROM external_bill x WHERE x.settlement_id=s.id)
   AND (SELECT COUNT(*) FROM settlement_confirmation x WHERE x.settlement_id=s.id)=2
   AND NOT EXISTS(SELECT 1 FROM v_pending_diff x WHERE x.settlement_id=s.id),'PASS','FAIL')
 ELSE '草稿：不作已确认判定' END AS 判断
FROM settlement s LEFT JOIN settlement_import b ON b.settlement_id=s.id ORDER BY s.id LIMIT 5;
SELECT '09 E 双方分别签字' AS 阶段,c.settlement_id AS 结算号,c.side AS 一方,c.actor AS 确认账号,a.role AS 角色,c.confirmed_at AS 签字时间
FROM settlement_confirmation c JOIN account a ON a.id=c.actor ORDER BY c.settlement_id,c.side LIMIT 10;

-- 10 E线：两类票据分别看，红冲保留原票；净额不能超过额度。
SELECT '10 E 结算票额度' AS 阶段,id AS 结算号,due AS 应结,invoiced AS 净开票,remaining AS 剩余额度,
 IF(invoiced BETWEEN 0 AND GREATEST(due,0),'PASS','FAIL') AS 判断
FROM v_invoice_balance ORDER BY id LIMIT 5;
SELECT '10 E 消费票蓝红记录' AS 阶段,id AS 票号,order_id AS 订单,amount AS 票额,
 original_id AS 红冲关联原票,IF(original_id IS NULL,'蓝票','红票') AS 方向
FROM consumer_invoice ORDER BY id LIMIT 10;

-- 11 数据质量：必须是每张业务表的实际COUNT，不用information_schema.TABLE_ROWS估计值。
WITH row_counts AS (
 SELECT 'account' table_name,COUNT(*) row_count FROM account
 UNION ALL SELECT 'alarm',COUNT(*) FROM alarm
 UNION ALL SELECT 'alarm_notice',COUNT(*) FROM alarm_notice
 UNION ALL SELECT 'alarm_rule',COUNT(*) FROM alarm_rule
 UNION ALL SELECT 'asset_history',COUNT(*) FROM asset_history
 UNION ALL SELECT 'asset_request',COUNT(*) FROM asset_request
 UNION ALL SELECT 'campaign',COUNT(*) FROM campaign
 UNION ALL SELECT 'charge_order',COUNT(*) FROM charge_order
 UNION ALL SELECT 'charger',COUNT(*) FROM charger
 UNION ALL SELECT 'connector',COUNT(*) FROM connector
 UNION ALL SELECT 'consumer_invoice',COUNT(*) FROM consumer_invoice
 UNION ALL SELECT 'consumer_invoice_request',COUNT(*) FROM consumer_invoice_request
 UNION ALL SELECT 'coupon',COUNT(*) FROM coupon
 UNION ALL SELECT 'diff_confirmation',COUNT(*) FROM diff_confirmation
 UNION ALL SELECT 'driver_feedback',COUNT(*) FROM driver_feedback
 UNION ALL SELECT 'external_bill',COUNT(*) FROM external_bill
 UNION ALL SELECT 'fee_detail',COUNT(*) FROM fee_detail
 UNION ALL SELECT 'fleet',COUNT(*) FROM fleet
 UNION ALL SELECT 'fleet_card',COUNT(*) FROM fleet_card
 UNION ALL SELECT 'gun_hold',COUNT(*) FROM gun_hold
 UNION ALL SELECT 'meter_sample',COUNT(*) FROM meter_sample
 UNION ALL SELECT 'operator',COUNT(*) FROM operator
 UNION ALL SELECT 'order_review',COUNT(*) FROM order_review
 UNION ALL SELECT 'payment',COUNT(*) FROM payment
 UNION ALL SELECT 'queue_call',COUNT(*) FROM queue_call
 UNION ALL SELECT 'queue_entry',COUNT(*) FROM queue_entry
 UNION ALL SELECT 'recon_diff',COUNT(*) FROM recon_diff
 UNION ALL SELECT 'redemption',COUNT(*) FROM redemption
 UNION ALL SELECT 'refund',COUNT(*) FROM refund
 UNION ALL SELECT 'settlement',COUNT(*) FROM settlement
 UNION ALL SELECT 'settlement_adjustment',COUNT(*) FROM settlement_adjustment
 UNION ALL SELECT 'settlement_confirmation',COUNT(*) FROM settlement_confirmation
 UNION ALL SELECT 'settlement_import',COUNT(*) FROM settlement_import
 UNION ALL SELECT 'settlement_invoice',COUNT(*) FROM settlement_invoice
 UNION ALL SELECT 'settlement_item',COUNT(*) FROM settlement_item
 UNION ALL SELECT 'station',COUNT(*) FROM station
 UNION ALL SELECT 'tariff',COUNT(*) FROM tariff
 UNION ALL SELECT 'tariff_band',COUNT(*) FROM tariff_band
 UNION ALL SELECT 'telemetry',COUNT(*) FROM telemetry
 UNION ALL SELECT 'vehicle',COUNT(*) FROM vehicle
 UNION ALL SELECT 'vehicle_binding',COUNT(*) FROM vehicle_binding
 UNION ALL SELECT 'wallet_entry',COUNT(*) FROM wallet_entry
 UNION ALL SELECT 'work_order',COUNT(*) FROM work_order
 UNION ALL SELECT 'work_part',COUNT(*) FROM work_part
)
SELECT '11 实际逐表数据量' AS 阶段,table_name AS 业务表,row_count AS 实际行数,
 IF(row_count>=20,'PASS','FAIL：少于20条') AS 判断 FROM row_counts ORDER BY table_name;

-- 12 查询正确性与执行路径：费用明细不应因一对多付款连接被重复累计。
SELECT '12 账单组成核对' AS 阶段,o.id AS 订单号,o.gross AS 原价,
 COALESCE(f.detail_total,0) AS 分段费用合计,r.adjustment AS 人工调整,
 t.minimum AS 最低收费,
 IF(o.gross=GREATEST(COALESCE(f.detail_total,0),t.minimum)+COALESCE(r.adjustment,0),'PASS','核对人工调整/样例状态') AS 判断
FROM charge_order o JOIN tariff t ON t.id=o.tariff_id
LEFT JOIN (SELECT order_id,SUM(energy+service) detail_total FROM fee_detail GROUP BY order_id) f ON f.order_id=o.id
LEFT JOIN order_review r ON r.order_id=o.id
WHERE o.id BETWEEN 1 AND 5 ORDER BY o.id;
EXPLAIN FORMAT=TREE SELECT id,started_at,state FROM charge_order WHERE account_id=1 ORDER BY started_at DESC,id DESC LIMIT 10;
