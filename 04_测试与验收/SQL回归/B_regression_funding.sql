-- Independent regression. Run after 01..08 in a dedicated test schema.
-- All business fixtures are rolled back, including on failure. No credentials are used.
SET time_zone='+08:00';
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
DROP PROCEDURE IF EXISTS regression_funding;
DELIMITER $$
CREATE PROCEDURE regression_funding()
BEGIN
 DECLARE v_operator bigint; DECLARE v_station bigint; DECLARE v_charger bigint;
 DECLARE v_gun1 bigint; DECLARE v_gun2 bigint; DECLARE v_user bigint; DECLARE v_admin bigint;
 DECLARE v_vehicle bigint; DECLARE v_tariff bigint; DECLARE v_order bigint; DECLARE v_second bigint;
 DECLARE v_payment bigint; DECLARE v_refund bigint; DECLARE v_campaign bigint; DECLARE v_coupon bigint;
 DECLARE v_fleet bigint; DECLARE v_card bigint; DECLARE v_t datetime(6);
 DECLARE v_rejected boolean DEFAULT false; DECLARE v_prefix varchar(64);
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 SET v_prefix=CONCAT('reg-',UUID());
 INSERT INTO operator(name) VALUES(v_prefix); SET v_operator=LAST_INSERT_ID();
 INSERT INTO station(operator_id,name,address,spaces) VALUES(v_operator,v_prefix,'synthetic regression site',2); SET v_station=LAST_INSERT_ID();
 INSERT INTO charger(station_id,model,rated_kw,protocol,commissioned_on,heartbeat,state)
 VALUES(v_station,'regression',120,'mock',CURRENT_DATE,SYSDATE(6),'idle'); SET v_charger=LAST_INSERT_ID();
 INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(v_charger,1,'DC','GB',60,'idle'); SET v_gun1=LAST_INSERT_ID();
 INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(v_charger,2,'DC','GB',60,'idle'); SET v_gun2=LAST_INSERT_ID();
 INSERT INTO account(login,password_hash,role,balance,verified) VALUES(v_prefix,'disabled-test-account','driver',30,true); SET v_user=LAST_INSERT_ID();
 INSERT INTO account(login,password_hash,role) VALUES(CONCAT(v_prefix,'-admin'),'disabled-test-account','admin'); SET v_admin=LAST_INSERT_ID();
 INSERT INTO vehicle(plate_mask,model,capacity_kwh,max_kw,supports_dc,interface) VALUES('synthetic','regression',60,60,true,'GB'); SET v_vehicle=LAST_INSERT_ID();
 INSERT INTO vehicle_binding(vehicle_id,account_id) VALUES(v_vehicle,v_user);
 INSERT INTO tariff(station_id,starts,ends,service_mode,authorization_amount) VALUES(v_station,'2025-01-01','2035-01-01','kwh',20); SET v_tariff=LAST_INSERT_ID();
 INSERT INTO tariff_band VALUES(v_tariff,0,1440,'flat',1,0);
 SET v_order=open_charge(v_user,v_vehicle,v_gun1,NULL);
 IF (SELECT reserved_balance FROM account WHERE id=v_user)<>20 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='wallet authorization not reserved'; END IF;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET v_rejected=true;
  SET v_second=open_charge(v_user,v_vehicle,v_gun2,NULL);
 END;
 IF NOT v_rejected OR (SELECT reserved_balance FROM account WHERE id=v_user)<>20 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='simultaneous wallet budgets exceeded available funds'; END IF;
 UPDATE charge_order SET state='cancelled' WHERE id=v_order;
 UPDATE connector SET state='idle' WHERE id=v_gun1;
 IF (SELECT reserved_balance FROM account WHERE id=v_user)<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='cancellation did not release wallet hold'; END IF;
 SET v_order=open_charge(v_user,v_vehicle,v_gun1,NULL);
 SELECT started_at INTO v_t FROM charge_order WHERE id=v_order;
 INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(v_order,v_t,0),(v_order,v_t+INTERVAL 1 MINUTE,25);
 CALL inspect_charge_budget(v_order);
 IF NOT (SELECT budget_exceeded AND stop_requested_at IS NOT NULL FROM charge_order WHERE id=v_order)
  OR (SELECT COUNT(*) FROM meter_sample WHERE order_id=v_order)<>2 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='budget incident lost raw samples or failed to request stop'; END IF;
 CALL finish_charge(v_order,v_t+INTERVAL 1 MINUTE,false);
 IF (SELECT state FROM charge_order WHERE id=v_order)<>'review' OR (SELECT gross FROM charge_order WHERE id=v_order)<>25
  OR (SELECT reserved_balance FROM account WHERE id=v_user)<>20 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='over-budget billing must preserve actual fee and authorization'; END IF;
 SET v_rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET v_rejected=true;
  CALL approve_review(v_order,v_admin,0,'must authorize first');
 END;
 IF NOT v_rejected THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='unfunded budget review was approved'; END IF;
 CALL authorize_more(v_order,25);
 CALL approve_review(v_order,v_admin,0,'additional authorization checked');
 SET v_payment=post_payment(v_user,v_order,'wallet',CONCAT(v_prefix,'-pay'),25,true);
 IF (SELECT balance FROM account WHERE id=v_user)<>5 OR (SELECT reserved_balance FROM account WHERE id=v_user)<>0 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='wallet payment did not debit and release exactly once'; END IF;
 SET v_refund=post_refund(v_payment,CONCAT(v_prefix,'-refund'),5);
 IF (SELECT outstanding FROM v_order_balance WHERE id=v_order)<>0 OR (SELECT net_due FROM v_order_balance WHERE id=v_order)<>20
  OR (SELECT state FROM charge_order WHERE id=v_order)<>'paid' OR (SELECT balance FROM account WHERE id=v_user)<>10 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='normal refund recreated customer debt'; END IF;
 SET v_refund=post_refund(v_payment,CONCAT(v_prefix,'-refund'),5);
 IF (SELECT balance FROM account WHERE id=v_user)<>10 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='refund replay duplicated wallet credit'; END IF;
 SET v_refund=post_refund_kind(v_payment,CONCAT(v_prefix,'-reversal'),5,'payment_reversal');
 IF (SELECT outstanding FROM v_order_balance WHERE id=v_order)<>5 OR (SELECT net_due FROM v_order_balance WHERE id=v_order)<>20
  OR (SELECT reserved_balance FROM account WHERE id=v_user)<>5 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='payment reversal failed to preserve obligation'; END IF;
 SET v_payment=post_payment(v_user,v_order,'wallet',CONCAT(v_prefix,'-repay'),5,true);
 IF (SELECT outstanding FROM v_order_balance WHERE id=v_order)<>0 OR (SELECT balance FROM account WHERE id=v_user)<>10 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='reversal repayment failed'; END IF;
 UPDATE account SET balance=30 WHERE id=v_user;
 SET v_order=open_charge(v_user,v_vehicle,v_gun1,NULL);
 SELECT started_at INTO v_t FROM charge_order WHERE id=v_order;
 INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(v_order,v_t,0),(v_order,v_t+INTERVAL 1 MINUTE,5);
 CALL finish_charge(v_order,v_t+INTERVAL 1 MINUTE,false);
 INSERT INTO campaign(name,station_id,face,minimum,starts,expires,stock)
 VALUES(v_prefix,v_station,100,0,NOW()-INTERVAL 1 DAY,NOW()+INTERVAL 1 DAY,1); SET v_campaign=LAST_INSERT_ID();
 SET v_coupon=issue_coupon(v_campaign,v_user);
 CALL redeem_coupon(v_order,v_coupon,v_user);
 IF (SELECT state FROM charge_order WHERE id=v_order)<>'paid' OR (SELECT outstanding FROM v_order_balance WHERE id=v_order)<>0
  OR (SELECT COUNT(*) FROM payment WHERE order_id=v_order)<>0 OR (SELECT reserved_balance FROM account WHERE id=v_user)<>0 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fully discounted order failed zero-payment settlement'; END IF;
 INSERT INTO fleet(manager_id,name) VALUES(v_admin,v_prefix); SET v_fleet=LAST_INSERT_ID();
 INSERT INTO fleet_card(fleet_id,vehicle_id,driver_id,credit_limit) VALUES(v_fleet,v_vehicle,v_user,25); SET v_card=LAST_INSERT_ID();
 SET v_order=open_charge(v_user,v_vehicle,v_gun1,v_card);
 SELECT started_at INTO v_t FROM charge_order WHERE id=v_order;
 IF (SELECT reserved_amount FROM fleet_card WHERE id=v_card)<>20 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet authorization not reserved'; END IF;
 INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(v_order,v_t,0),(v_order,v_t+INTERVAL 1 MINUTE,30);
 CALL inspect_charge_budget(v_order);
 CALL finish_charge(v_order,v_t+INTERVAL 1 MINUTE,false);
 SET v_rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET v_rejected=true;
  CALL authorize_more(v_order,30);
 END;
 IF NOT v_rejected OR (SELECT reserved_amount FROM fleet_card WHERE id=v_card)<>20 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet credit allowed unfunded additional authorization'; END IF;
 UPDATE fleet_card SET credit_limit=40 WHERE id=v_card;
 CALL authorize_more(v_order,30);
 CALL approve_review(v_order,v_admin,0,'fleet limit increased explicitly');
 IF (SELECT reserved_amount FROM fleet_card WHERE id=v_card)<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='completed fleet order retained active hold'; END IF;
 SET v_rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET v_rejected=true;
  SET v_second=open_charge(v_user,v_vehicle,v_gun2,v_card);
 END;
 IF NOT v_rejected THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet monthly billed usage was omitted from credit check'; END IF;
 IF NOT (SELECT station_id=v_station AND operator_id=v_operator FROM charge_order WHERE id=v_order) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='order historical ownership snapshot missing'; END IF;
 ROLLBACK;
 SELECT 'funding/refund/zero-price regression passed' AS result;
END$$
DELIMITER ;
CALL regression_funding();
DROP PROCEDURE regression_funding;
