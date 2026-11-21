-- Execute on the seeded demo database with the mysql client.
SET time_zone='+08:00';
DROP PROCEDURE IF EXISTS charge_smoke;
DELIMITER $$
CREATE PROCEDURE charge_smoke()
BEGIN
 DECLARE s bigint; DECLARE d bigint; DECLARE p bigint; DECLARE x bigint;
 DECLARE q bigint; DECLARE o bigint; DECLARE t datetime(6); DECLARE refused boolean DEFAULT false;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 IF (SELECT gross FROM charge_order WHERE id=1)<>11.40 OR (SELECT received FROM v_order_balance WHERE id=1)<>9.40
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='billing totals wrong'; END IF;
 SET p=post_payment(1,1,'mock','seed-a-1',4,true);
 IF (SELECT COUNT(*) FROM payment WHERE order_id=1)<>2 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='replay duplicated payment'; END IF;
 UPDATE charger SET heartbeat=SYSDATE(6) WHERE id=1;
 SET q=take_queue(1,1,1);
 CALL dispatch_station(1);
 IF (SELECT state FROM queue_entry WHERE id=q)<>'called' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='queue did not call'; END IF;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET refused=true;
  SET o=open_charge(2,2,1,NULL);
 END;
 IF NOT refused THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='reserved gun was available'; END IF;
 SET o=open_charge(1,1,1,NULL);
 SELECT started_at INTO t FROM charge_order WHERE id=o;
 INSERT INTO meter_sample VALUES(o,t,200),(o,t+INTERVAL 1 MINUTE,201);
 CALL process_charger(1,'offline');
 IF (SELECT state FROM charge_order WHERE id=o)<>'review' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='disconnect did not require review'; END IF;
 SELECT id INTO s FROM settlement WHERE station_id=1 AND period='2026-11-01';
 SELECT id INTO d FROM recon_diff WHERE settlement_id=s AND kind='price';
 IF (SELECT COUNT(*) FROM settlement_confirmation WHERE settlement_id=s)<>2
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='bilateral settlement signatures missing'; END IF;
 IF NOT EXISTS(SELECT 1 FROM settlement_adjustment WHERE diff_id=d)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='confirmed difference adjustment missing'; END IF;
 SET refused=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET refused=true;
  INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount) VALUES(s,'示例','test',9999);
 END;
 IF NOT refused THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invoice exceeded ceiling'; END IF;
 INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount) VALUES(s,'示例','test',1);
 SET x=LAST_INSERT_ID();
 INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount,original_id) VALUES(s,'示例','test',1,x);
 IF (SELECT invoiced FROM v_invoice_balance WHERE id=s)<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='red invoice did not cancel'; END IF;
 ROLLBACK;
 SELECT 'smoke passed' AS result;
END$$
DELIMITER ;
CALL charge_smoke();
DROP PROCEDURE charge_smoke;
