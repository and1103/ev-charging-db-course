-- Dedicated deployment regression. No fixture data survives success or failure.
DROP PROCEDURE IF EXISTS regression_settlement;
SET time_zone='+08:00';
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
DELIMITER $$
CREATE PROCEDURE regression_settlement()
BEGIN
 DECLARE op bigint; DECLARE site bigint; DECLARE device bigint; DECLARE gun bigint;
 DECLARE driver bigint; DECLARE admin_user bigint; DECLARE operator_user bigint; DECLARE car bigint; DECLARE tariff_key bigint;
 DECLARE first_order bigint; DECLARE late_order bigint; DECLARE first_payment bigint; DECLARE second_payment bigint; DECLARE refund_key bigint;
 DECLARE bill bigint; DECLARE future_bill bigint; DECLARE missing_key bigint; DECLARE extra_key bigint; DECLARE request_key bigint; DECLARE blue_key bigint;
 DECLARE started datetime(6); DECLARE period_key date; DECLARE prefix_key varchar(64); DECLARE rejected boolean DEFAULT false;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 IF DATABASE()<>'charge_course_v3' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='run settlement regression only in the dedicated course test schema'; END IF;
 SET prefix_key=CONCAT('settlement-reg-',UUID());
 INSERT INTO operator(name) VALUES(prefix_key); SET op=LAST_INSERT_ID();
 INSERT INTO station(operator_id,name,address,spaces) VALUES(op,prefix_key,'synthetic settlement fixture',2); SET site=LAST_INSERT_ID();
 INSERT INTO charger(station_id,model,rated_kw,protocol,commissioned_on,heartbeat,state)
 VALUES(site,'regression',120,'mock',CURRENT_DATE,SYSDATE(6),'idle'); SET device=LAST_INSERT_ID();
 INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(device,1,'DC','GB',60,'idle'); SET gun=LAST_INSERT_ID();
 INSERT INTO account(login,password_hash,role,balance,verified) VALUES(prefix_key,'disabled-fixture','driver',500,true); SET driver=LAST_INSERT_ID();
 INSERT INTO account(login,password_hash,role) VALUES(CONCAT(prefix_key,'-admin'),'disabled-fixture','admin'); SET admin_user=LAST_INSERT_ID();
 INSERT INTO account(login,password_hash,role,operator_id) VALUES(CONCAT(prefix_key,'-operator'),'disabled-fixture','operator',op); SET operator_user=LAST_INSERT_ID();
 INSERT INTO vehicle(plate_mask,model,capacity_kwh,max_kw,supports_dc,interface) VALUES('fixture','regression',200,60,true,'GB'); SET car=LAST_INSERT_ID();
 INSERT INTO vehicle_binding(vehicle_id,account_id) VALUES(car,driver);
 INSERT INTO tariff(station_id,starts,ends,service_mode,authorization_amount) VALUES(site,'2025-01-01','2035-01-01','kwh',200); SET tariff_key=LAST_INSERT_ID();
 INSERT INTO tariff_band VALUES(tariff_key,0,1440,'flat',1,0);
 SET first_order=open_charge(driver,car,gun,NULL);
 SELECT started_at INTO started FROM charge_order WHERE id=first_order;
 INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(first_order,started,0),(first_order,started+INTERVAL 2 HOUR,100);
 CALL finish_charge(first_order,started+INTERVAL 2 HOUR,false);
 SET first_payment=post_payment(driver,first_order,'wallet',CONCAT(prefix_key,'-pay'),100,true);
 SET period_key=CAST(DATE_FORMAT(started+INTERVAL 2 HOUR,'%Y-%m-01') AS DATE);
 CALL build_settlement(site,period_key);
 SELECT id INTO bill FROM settlement WHERE station_id=site AND operator_id=op AND period=period_key;
 IF (SELECT due FROM v_settlement WHERE id=bill)<>88 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='100 original energy must settle 90 minus 2 = 88'; END IF;

 CALL begin_bill_import(bill,'incomplete',2);
 INSERT INTO external_bill VALUES(bill,first_order,100,100,true);
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  CALL compare_settlement(bill);
 END;
 IF NOT rejected OR (SELECT state FROM settlement_import WHERE settlement_id=bill)<>'open'
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='incomplete batch was accepted'; END IF;
 CALL reset_bill_import(bill);
 CALL begin_bill_import(bill,'missing-and-extra',1);
 INSERT INTO external_bill VALUES(bill,9000000000000000000,1,1,true);
 CALL compare_settlement(bill);
 SELECT id INTO missing_key FROM recon_diff WHERE settlement_id=bill AND kind='missing' AND order_id=first_order;
 SELECT id INTO extra_key FROM recon_diff WHERE settlement_id=bill AND kind='extra' AND order_id=9000000000000000000;
 IF missing_key IS NULL OR extra_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='missing/unknown extra order was lost'; END IF;
 CALL confirm_difference(missing_key,admin_user,'accept');
 CALL confirm_difference(missing_key,operator_user,'reject');
 IF (SELECT COUNT(*) FROM diff_confirmation WHERE diff_id=missing_key)<>2
 OR NOT EXISTS(SELECT 1 FROM v_pending_diff WHERE id=missing_key)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='opposing opinions were rejected or prematurely resolved'; END IF;
 CALL confirm_difference(missing_key,admin_user,'reject');
 CALL confirm_difference(extra_key,admin_user,'reject');
 CALL confirm_difference(extra_key,operator_user,'reject');
 CALL confirm_settlement(bill,admin_user);
 IF (SELECT state FROM settlement WHERE id=bill)<>'draft' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='single party finalized settlement'; END IF;
 CALL confirm_settlement(bill,operator_user);
 IF (SELECT state FROM settlement WHERE id=bill)<>'confirmed' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='bilateral signatures did not finalize'; END IF;
 SET rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  UPDATE settlement_item SET kwh=kwh+1 WHERE settlement_id=bill;
 END;
 IF NOT rejected THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='confirmed item was mutable'; END IF;
 SET rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  DELETE FROM external_bill WHERE settlement_id=bill;
 END;
 IF NOT rejected THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='confirmed external batch was mutable'; END IF;

 INSERT INTO consumer_invoice_request(order_id,title) VALUES(first_order,'synthetic invoice'); SET request_key=LAST_INSERT_ID();
 CALL issue_consumer_invoice(request_key,admin_user,'synthetic-tax',100);
 SELECT id INTO blue_key FROM consumer_invoice WHERE request_id=request_key AND original_id IS NULL;
 IF blue_key IS NULL OR (SELECT remaining FROM v_consumer_invoice_balance WHERE order_id=first_order)<>0
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='consumer invoice amount/limit missing'; END IF;
 SET rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  SET refund_key=post_refund(first_payment,CONCAT(prefix_key,'-blocked'),1);
 END;
 IF NOT rejected THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='refund bypassed active invoice limit'; END IF;
 CALL reverse_consumer_invoice(blue_key,admin_user);
 IF (SELECT COUNT(*) FROM consumer_invoice WHERE request_id=request_key)<>2
 OR (SELECT invoiced FROM v_consumer_invoice_balance WHERE order_id=first_order)<>0
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='red invoice destroyed original or failed to restore limit'; END IF;
 SET refund_key=post_refund(first_payment,CONCAT(prefix_key,'-refund-1'),33.33);
 CALL build_settlement(site,period_key+INTERVAL 1 MONTH);
 SELECT id INTO future_bill FROM settlement WHERE station_id=site AND operator_id=op AND period=period_key+INTERVAL 1 MONTH;
 IF (SELECT due FROM v_settlement WHERE id=bill)<>88
 OR (SELECT due FROM v_settlement WHERE id=future_bill)<>-29.33
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='refund changed frozen ledger or incorrect partial reversal'; END IF;
 SET refund_key=post_refund(first_payment,CONCAT(prefix_key,'-refund-2'),33.33);
 SET refund_key=post_refund(first_payment,CONCAT(prefix_key,'-refund-3'),33.34);
 CALL build_settlement(site,period_key+INTERVAL 1 MONTH);
 CALL build_settlement(site,period_key+INTERVAL 1 MONTH);
 IF (SELECT SUM(amount) FROM settlement_adjustment WHERE settlement_id=future_bill AND refund_id IS NOT NULL)<>-88
 OR (SELECT COUNT(*) FROM settlement_adjustment WHERE settlement_id=future_bill AND refund_id IS NOT NULL)<>3
 OR (SELECT SUM(energy_reversal) FROM settlement_adjustment WHERE settlement_id=future_bill)<>90
 OR (SELECT SUM(fee_reversal) FROM settlement_adjustment WHERE settlement_id=future_bill)<>2
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='full refund failed exact 88 reversal or duplicated partial refunds'; END IF;

 -- A second order is paid only after the first monthly ledger was frozen.
 SET late_order=open_charge(driver,car,gun,NULL);
 SELECT started_at INTO started FROM charge_order WHERE id=late_order;
 INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(late_order,started,0),(late_order,started+INTERVAL 2 HOUR,100);
 CALL finish_charge(late_order,started+INTERVAL 2 HOUR,false);
 SET second_payment=post_payment(driver,late_order,'wallet',CONCAT(prefix_key,'-late-pay'),100,true);
 CALL build_settlement(site,period_key);
 IF EXISTS(SELECT 1 FROM settlement_item WHERE order_id=late_order)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='late payment rewrote confirmed source period'; END IF;
 CALL build_settlement(site,period_key+INTERVAL 1 MONTH);
 IF NOT EXISTS(SELECT 1 FROM settlement_item WHERE order_id=late_order AND settlement_id=future_bill AND source_period=period_key)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='late first settlement was lost'; END IF;
 IF (SELECT due FROM v_settlement WHERE id=future_bill)<>0
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='late order and exact refund allocation did not balance'; END IF;
 ROLLBACK;
 SELECT 'settlement batch/bilateral/freeze/100-to-88/late-first/invoice regression passed' result;
END$$
DELIMITER ;
CALL regression_settlement();
DROP PROCEDURE regression_settlement;
