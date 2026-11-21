-- Workbench 新业务流程验证：全部私有UUID夹具，最后ROLLBACK，不修改原有样例。
-- 请使用单独SQL标签/会话，在没有待提交工作的情况下从头执行。
-- 可分段停在SELECT查看中间状态，但必须从准备段开始且保持同一会话。
-- 任一步报错：停止后执行 ROLLBACK;，不要COMMIT。脚本无DDL/无COMMIT。
-- 回滚会撤销夹具和业务写入；AUTO_INCREMENT编号已消耗仍可有空号，这是MySQL正常行为。
-- 时间与读数是明确的合成演示输入，设备/支付/发票均未调用外部平台。
USE charge_course_20261114;
SET time_zone='+08:00';
START TRANSACTION;
SET @wb_ref=CONCAT('wb-',REPLACE(UUID(),'-',''));

-- 01 准备私有场站、车主、车辆及角色，不使用任何已有用户身份或业务订单。
INSERT INTO operator(name) VALUES(@wb_ref);
SET @wb_operator=LAST_INSERT_ID();
INSERT INTO station(operator_id,name,address,spaces) VALUES(@wb_operator,@wb_ref,'合成Workbench验证场站',2);
SET @wb_station=LAST_INSERT_ID();
INSERT INTO charger(station_id,model,rated_kw,protocol,commissioned_on,heartbeat,state)
VALUES(@wb_station,'合成设备',120,'mock',CURRENT_DATE,SYSDATE(6),'idle');
SET @wb_charger=LAST_INSERT_ID();
INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(@wb_charger,1,'DC','GB',60,'idle');
SET @wb_gun=LAST_INSERT_ID();
INSERT INTO account(login,password_hash,role,verified) VALUES(CONCAT(@wb_ref,'-driver'),'!disabled-workbench-fixture','driver',true);
SET @wb_driver=LAST_INSERT_ID();
INSERT INTO account(login,password_hash,role) VALUES(CONCAT(@wb_ref,'-admin'),'!disabled-workbench-fixture','admin');
SET @wb_admin=LAST_INSERT_ID();
INSERT INTO account(login,password_hash,role,operator_id) VALUES(CONCAT(@wb_ref,'-operator'),'!disabled-workbench-fixture','operator',@wb_operator);
SET @wb_operator_user=LAST_INSERT_ID();
INSERT INTO account(login,password_hash,role,station_id) VALUES(CONCAT(@wb_ref,'-tech'),'!disabled-workbench-fixture','maintenance',@wb_station);
SET @wb_tech=LAST_INSERT_ID();
INSERT INTO vehicle(plate_mask,model,capacity_kwh,max_kw,supports_dc,interface) VALUES('测试***','合成车辆',60,60,true,'GB');
SET @wb_vehicle=LAST_INSERT_ID();
INSERT INTO vehicle_binding(vehicle_id,account_id) VALUES(@wb_vehicle,@wb_driver);
INSERT INTO tariff(station_id,starts,ends,service_mode,authorization_amount)
VALUES(@wb_station,CURRENT_DATE-INTERVAL 1 DAY,CURRENT_DATE+INTERVAL 2 DAY,'kwh',20);
SET @wb_tariff=LAST_INSERT_ID();
INSERT INTO tariff_band VALUES(@wb_tariff,0,1440,'flat',1,0.2);

-- 02 D钱包充值100元，同一请求重放只生成一笔流水；应为100余额、同一流水号。
SET @wb_topup=mock_wallet_topup(@wb_driver,CONCAT(@wb_ref,'-topup'),100);
SET @wb_topup_repeat=mock_wallet_topup(@wb_driver,CONCAT(@wb_ref,'-topup'),100);
SELECT '02 D 模拟充值与幂等' AS 阶段,@wb_topup AS 首次流水,@wb_topup_repeat AS 重放流水,
 a.balance AS 余额,a.reserved_balance AS 冻结,
 IF(@wb_topup=@wb_topup_repeat AND a.balance=100 AND a.reserved_balance=0,'PASS','FAIL') AS 判断
FROM account a WHERE a.id=@wb_driver;

-- 03 B估算：2kWh、60kW、平段1元/kWh+0.2服务费，应估价2.40。
SELECT '03 B 费用估算' AS 阶段,estimate_charge(@wb_tariff,SYSDATE(6),2,60) AS 估价,
 IF(estimate_charge(@wb_tariff,SYSDATE(6),2,60)=2.40,'PASS','FAIL') AS 判断;

-- 04 A取号→叫号→留枪。应出现called队列与held留枪。
SET @wb_queue=take_queue(@wb_driver,@wb_vehicle,@wb_station);
CALL dispatch_station(@wb_station);
SELECT '04 A 排队叫号留枪' AS 阶段,e.id AS 排队号,e.state AS 排队状态,q.id AS 叫号,
 h.connector_id AS 枪号,h.state AS 留枪状态,q.deadline AS 叫号期限,
 IF(e.state='called' AND h.state='held' AND h.connector_id=@wb_gun,'PASS','FAIL') AS 判断
FROM queue_entry e JOIN queue_call q ON q.entry_id=e.id JOIN gun_hold h ON h.call_id=q.id WHERE e.id=@wb_queue;

-- 05 A/B扫码开单，默认冻结20元；钱包余额仍100，可用80，排队converted/留枪used。
SET @wb_order=open_charge(@wb_driver,@wb_vehicle,@wb_gun,NULL);
SELECT started_at INTO @wb_start FROM charge_order WHERE id=@wb_order;
SELECT '05 AB 开单预授权' AS 阶段,o.id AS 订单号,o.state AS 状态,o.authorized_amount AS 授权,
 a.balance AS 余额,a.reserved_balance AS 冻结,a.balance-a.reserved_balance AS 可用,
 e.state AS 排队状态,h.state AS 留枪状态,
 IF(o.state='charging' AND o.wallet_hold=20 AND a.balance=100 AND a.reserved_balance=20
 AND e.state='converted' AND h.state='used','PASS','FAIL') AS 判断
FROM charge_order o JOIN account a ON a.id=o.account_id JOIN queue_entry e ON e.id=@wb_queue
JOIN gun_hold h ON h.order_id=o.id WHERE o.id=@wb_order;

-- 06 B模拟读数100→102，使用同日单平段避免额外跨午夜插值复核；最大模拟10分钟。
SET @wb_end=LEAST(@wb_start+INTERVAL 10 MINUTE,TIMESTAMP(DATE(@wb_start)+INTERVAL 1 DAY)-INTERVAL 1 MICROSECOND);
INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(@wb_order,@wb_start,100),(@wb_order,@wb_end,102);
CALL finish_charge(@wb_order,@wb_end,false);
SELECT '06 B 结束核价' AS 阶段,o.id AS 订单,o.state AS 状态,o.kwh AS 电量,o.gross AS 原价,
 o.wallet_hold AS 剩余冻结,f.energy AS 电费,f.service AS 服务费,
 IF(o.state='billed' AND o.kwh=2 AND o.gross=2.40 AND f.energy=2 AND f.service=0.40,'PASS','FAIL') AS 判断
FROM charge_order o JOIN fee_detail f ON f.order_id=o.id WHERE o.id=@wb_order;

-- 07 D发0.40优惠券，B账单应付由2.40变2.00，资金冻结同步调整。
INSERT INTO campaign(name,station_id,face,minimum,starts,expires,stock)
VALUES(@wb_ref,@wb_station,0.40,1,CURRENT_DATE-INTERVAL 1 DAY,CURRENT_DATE+INTERVAL 2 DAY,1);
SET @wb_campaign=LAST_INSERT_ID();
SET @wb_coupon=issue_coupon(@wb_campaign,@wb_driver);
CALL redeem_coupon(@wb_order,@wb_coupon,@wb_driver);
SELECT '07 D 优惠核销' AS 阶段,id AS 订单,discount AS 优惠,net_due AS 应付,wallet_hold AS 冻结,
 IF(discount=0.40 AND net_due=2 AND wallet_hold=2,'PASS','FAIL') AS 判断 FROM v_order_balance WHERE id=@wb_order;

-- 08 B付款1+1元，重放第一笔不重复扣款；应paid、已收2、待付0、余额98、冻结0、仅两笔付款。
SET @wb_payment1=post_payment(@wb_driver,@wb_order,'wallet',CONCAT(@wb_ref,'-pay1'),1,true);
SET @wb_repeat1=post_payment(@wb_driver,@wb_order,'wallet',CONCAT(@wb_ref,'-pay1'),1,true);
SET @wb_payment2=post_payment(@wb_driver,@wb_order,'wallet',CONCAT(@wb_ref,'-pay2'),1,true);
SELECT '08 BD 分次付款与幂等' AS 阶段,o.id AS 订单,o.state AS 状态,o.received AS 已收,o.outstanding AS 待付,
 a.balance AS 钱包余额,a.reserved_balance AS 冻结,
 (SELECT COUNT(*) FROM payment WHERE order_id=@wb_order) AS 付款笔数,
 IF(@wb_payment1=@wb_repeat1 AND o.state='paid' AND o.received=2 AND o.outstanding=0
 AND a.balance=98 AND a.reserved_balance=0 AND (SELECT COUNT(*) FROM payment WHERE order_id=@wb_order)=2,'PASS','FAIL') AS 判断
FROM v_order_balance o JOIN account a ON a.id=o.account_id WHERE o.id=@wb_order;

-- 09 C独立模拟告警历史：指定来源枪，同源同码不生成重复告警。
SET @wb_rule=CONCAT(@wb_ref,'-FAULT');
INSERT INTO alarm_rule(code,severity,response_minutes) VALUES(@wb_rule,3,5);
SET @wb_alarm=raise_alarm_scope(@wb_charger,@wb_gun,@wb_rule);
SET @wb_alarm_repeat=raise_alarm_scope(@wb_charger,@wb_gun,@wb_rule);
SET @wb_t=SYSDATE(6);
UPDATE alarm SET opened_at=@wb_t-INTERVAL 8 MINUTE,deadline=@wb_t-INTERVAL 7 MINUTE WHERE id=@wb_alarm;
INSERT INTO work_order(alarm_id,technician_id,assigned_at) VALUES(@wb_alarm,@wb_tech,@wb_t-INTERVAL 6 MINUTE);
SET @wb_work=LAST_INSERT_ID();
UPDATE work_order SET accepted_at=@wb_t-INTERVAL 5 MINUTE WHERE id=@wb_work;
UPDATE work_order SET arrived_at=@wb_t-INTERVAL 4 MINUTE WHERE id=@wb_work;
UPDATE work_order SET repaired_at=@wb_t-INTERVAL 3 MINUTE,result='合成修复，供SQL流程验证' WHERE id=@wb_work;
UPDATE work_order SET closed_at=@wb_t-INTERVAL 2 MINUTE WHERE id=@wb_work;
INSERT INTO telemetry(charger_id,sampled_at,offline_seconds)
VALUES(@wb_charger,@wb_t-INTERVAL 150 SECOND,0),(@wb_charger,@wb_t-INTERVAL 90 SECOND,0),(@wb_charger,@wb_t-INTERVAL 30 SECOND,0);
UPDATE charger SET heartbeat=@wb_t,state='idle' WHERE id=@wb_charger;
CALL recover_alarm(@wb_alarm);
SELECT '09 C 工单闭环和正常观察' AS 阶段,a.id AS 告警,a.connector_id AS 来源枪,w.accepted_at AS 接单,
 w.arrived_at AS 到场,w.repaired_at AS 修复,w.closed_at AS 关闭,a.restored_at AS 恢复,
 IF(@wb_alarm=@wb_alarm_repeat AND a.connector_id=@wb_gun AND a.restored_at IS NOT NULL
 AND w.closed_at IS NOT NULL,'PASS','FAIL') AS 判断 FROM alarm a JOIN work_order w ON w.alarm_id=a.id WHERE a.id=@wb_alarm;

-- 10 E生成私有结算单并导入一行完整外账；不是操作任何已有确认账单。
SET @wb_period=CAST(DATE_FORMAT(@wb_end,'%Y-%m-01') AS DATE);
CALL build_settlement(@wb_station,@wb_period);
SELECT id INTO @wb_bill FROM settlement WHERE station_id=@wb_station AND operator_id=@wb_operator AND period=@wb_period;
CALL begin_bill_import(@wb_bill,@wb_ref,1);
INSERT INTO external_bill(settlement_id,order_id,batch,kwh,amount,paid)
VALUES(@wb_bill,@wb_order,@wb_ref,2,2,true);
CALL compare_settlement(@wb_bill);
SELECT '10 E 完整批次对账' AS 阶段,s.id AS 结算,s.state AS 状态,b.state AS 批次,
 b.expected_rows AS 声明行数,(SELECT COUNT(*) FROM recon_diff WHERE settlement_id=@wb_bill) AS 差异数,
 IF(s.state='draft' AND b.state='complete' AND b.expected_rows=1
 AND NOT EXISTS(SELECT 1 FROM recon_diff WHERE settlement_id=@wb_bill),'PASS','FAIL') AS 判断
FROM settlement s JOIN settlement_import b ON b.settlement_id=s.id WHERE s.id=@wb_bill;

-- 11 E平台签一次仍是draft；运营商签第二次才confirmed。
CALL confirm_settlement(@wb_bill,@wb_admin);
SELECT '11 E 仅平台确认' AS 阶段,id AS 结算,state AS 状态,
 IF(state='draft' AND (SELECT COUNT(*) FROM settlement_confirmation WHERE settlement_id=@wb_bill)=1,'PASS','FAIL') AS 判断
FROM settlement WHERE id=@wb_bill;
CALL confirm_settlement(@wb_bill,@wb_operator_user);
SELECT '11 E 双方确认' AS 阶段,s.id AS 结算,s.state AS 状态,v.due AS 应结,
 (SELECT COUNT(*) FROM settlement_confirmation WHERE settlement_id=@wb_bill) AS 确认方数,
 IF(s.state='confirmed' AND v.due=1.73
 AND (SELECT COUNT(*) FROM settlement_confirmation WHERE settlement_id=@wb_bill)=2,'PASS','FAIL') AS 判断
FROM settlement s JOIN v_settlement v ON v.id=s.id WHERE s.id=@wb_bill;

-- 12 E两类票据各自开蓝票、红冲保留原票。消费票依据订单2元，结算票依据应结1.73元。
INSERT INTO consumer_invoice_request(order_id,title) VALUES(@wb_order,'合成消费票抬头');
SET @wb_request=LAST_INSERT_ID();
CALL issue_consumer_invoice(@wb_request,@wb_admin,'WB-SYNTHETIC-TAX',2);
SELECT id INTO @wb_blue FROM consumer_invoice WHERE request_id=@wb_request AND original_id IS NULL;
CALL reverse_consumer_invoice(@wb_blue,@wb_admin);
INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount) VALUES(@wb_bill,'合成结算票','WB-SYNTHETIC-TAX',1.73);
SET @wb_settlement_blue=LAST_INSERT_ID();
INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount,original_id)
VALUES(@wb_bill,'合成结算票','WB-SYNTHETIC-TAX',1.73,@wb_settlement_blue);
SELECT '12 E 消费票蓝红记录' AS 阶段,id AS 票号,amount AS 金额,original_id AS 红冲引用
FROM consumer_invoice WHERE request_id=@wb_request ORDER BY id;
SELECT '12 E 结算票蓝红记录' AS 阶段,id AS 票号,amount AS 金额,original_id AS 红冲引用
FROM settlement_invoice WHERE settlement_id=@wb_bill ORDER BY id;
SELECT '12 E 红冲后额度' AS 阶段,c.invoiced AS 消费净开票,c.remaining AS 消费剩余,
 s.invoiced AS 结算净开票,s.remaining AS 结算剩余,
 IF(c.invoiced=0 AND c.remaining=2 AND s.invoiced=0 AND s.remaining=1.73,'PASS','FAIL') AS 判断
FROM v_consumer_invoice_balance c CROSS JOIN v_invoice_balance s WHERE c.order_id=@wb_order AND s.id=@wb_bill;

-- 13 B/E正常退款0.25：减少客户债务，不重新形成欠费；旧结算不变，次月按原比例逆冲。
SET @wb_refund=post_refund(@wb_payment2,CONCAT(@wb_ref,'-refund'),0.25);
SET @wb_refund_repeat=post_refund(@wb_payment2,CONCAT(@wb_ref,'-refund'),0.25);
CALL build_settlement(@wb_station,@wb_period+INTERVAL 1 MONTH);
SELECT id INTO @wb_next_bill FROM settlement WHERE station_id=@wb_station AND operator_id=@wb_operator AND period=@wb_period+INTERVAL 1 MONTH;
SELECT '13 BE 退款与跨期逆冲' AS 阶段,o.net_due AS 客户实际应付,o.refunded AS 已退,o.outstanding AS 待付,
 a.balance AS 钱包余额,old_bill.due AS 旧结算应结,next_bill.due AS 次月调整,
 IF(@wb_refund=@wb_refund_repeat AND o.net_due=1.75 AND o.refunded=0.25 AND o.outstanding=0
 AND a.balance=98.25 AND old_bill.due=1.73 AND next_bill.due=-0.21,'PASS','FAIL') AS 判断
FROM v_order_balance o JOIN account a ON a.id=o.account_id
CROSS JOIN v_settlement old_bill CROSS JOIN v_settlement next_bill
WHERE o.id=@wb_order AND old_bill.id=@wb_bill AND next_bill.id=@wb_next_bill;

-- 14 回滚；此前所有SELECT网格仍可查看，私有业务和夹具行全部撤销。
ROLLBACK;
SELECT '14 回滚后检查' AS 阶段,
 (SELECT COUNT(*) FROM operator WHERE id=@wb_operator) AS 场站经营者剩余,
 (SELECT COUNT(*) FROM account WHERE id=@wb_driver) AS 用户剩余,
 (SELECT COUNT(*) FROM charge_order WHERE id=@wb_order) AS 订单剩余,
 (SELECT COUNT(*) FROM settlement WHERE id IN (@wb_bill,@wb_next_bill)) AS 结算剩余,
 (SELECT COUNT(*) FROM alarm WHERE id=@wb_alarm) AS 告警剩余,
 IF(NOT EXISTS(SELECT 1 FROM operator WHERE id=@wb_operator)
 AND NOT EXISTS(SELECT 1 FROM account WHERE id=@wb_driver)
 AND NOT EXISTS(SELECT 1 FROM charge_order WHERE id=@wb_order)
 AND NOT EXISTS(SELECT 1 FROM settlement WHERE id IN (@wb_bill,@wb_next_bill))
 AND NOT EXISTS(SELECT 1 FROM alarm WHERE id=@wb_alarm),'PASS','FAIL：请核对事务状态') AS 判断;
