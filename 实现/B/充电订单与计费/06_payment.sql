

CREATE VIEW v_order_balance AS SELECT o.*,COALESCE(p.total,0) received,COALESCE(r.total,0) refunded,
 o.gross-o.discount-COALESCE(p.total,0)+COALESCE(r.total,0) outstanding FROM charge_order o
 LEFT JOIN (SELECT order_id,SUM(amount) total FROM payment WHERE succeeded GROUP BY order_id) p ON p.order_id=o.id
 LEFT JOIN (SELECT p.order_id,SUM(r.amount) total FROM refund r JOIN payment p ON p.id=r.payment_id GROUP BY p.order_id) r ON r.order_id=o.id;
CREATE VIEW v_unpaid_order AS SELECT * FROM v_order_balance WHERE state='billed' AND outstanding>0;
CREATE VIEW v_band_income AS SELECT g.station_id,DATE(f.begins) service_day,f.label,SUM(f.kwh) kwh,SUM(f.energy) energy,SUM(f.service) service
 FROM fee_detail f JOIN charge_order o ON o.id=f.order_id JOIN v_gun_state g ON g.id=o.connector_id
 WHERE o.state IN ('billed','paid') GROUP BY 1,2,3;
DELIMITER $$
CREATE FUNCTION post_payment(p_user bigint,p_order bigint,p_channel varchar(20),p_ref varchar(255),p_amount decimal(14,4),p_success boolean)
RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE order_key bigint; DECLARE prior bigint; DECLARE due decimal(12,2); DECLARE result bigint; DECLARE o_state varchar(20);
 SELECT id,state INTO order_key,o_state FROM charge_order WHERE id=p_order AND account_id=p_user FOR UPDATE;
 IF order_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='order not found'; END IF;
 SELECT id INTO prior FROM payment WHERE channel=p_channel AND reference=p_ref;
 IF prior IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM payment WHERE id=prior AND order_id=p_order AND amount=p_amount AND succeeded=p_success)
  THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='payment replay mismatch'; END IF;
  RETURN prior;
 END IF;
 SELECT outstanding INTO due FROM v_order_balance WHERE id=order_key;
 IF o_state<>'billed' OR p_amount<=0 OR p_amount<>ROUND(p_amount,2) OR p_amount>due
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid payment'; END IF;
 IF p_channel='wallet' AND p_success THEN
  UPDATE account SET balance=balance-p_amount WHERE id=p_user AND balance>=p_amount;
  IF ROW_COUNT()=0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='insufficient balance'; END IF;
 END IF;
 INSERT INTO payment(order_id,channel,reference,amount,succeeded) VALUES(p_order,p_channel,p_ref,p_amount,p_success);
 SET result=LAST_INSERT_ID();
 IF p_channel='wallet' AND p_success THEN INSERT INTO wallet_entry(account_id,payment_id,`change`) VALUES(p_user,result,-p_amount); END IF;
 IF p_success AND p_amount=due THEN UPDATE charge_order SET state='paid' WHERE id=p_order; END IF;
 RETURN result;
END$$
CREATE FUNCTION post_refund(p_payment bigint,p_ref varchar(255),p_amount decimal(14,4)) RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE order_key bigint; DECLARE owner_key bigint; DECLARE channel_name varchar(20); DECLARE paid decimal(12,2);
 DECLARE prior bigint; DECLARE result bigint;
 SELECT order_id,channel,amount INTO order_key,channel_name,paid FROM payment WHERE id=p_payment AND succeeded;
 SELECT account_id INTO owner_key FROM charge_order WHERE id=order_key FOR UPDATE;
 SELECT id INTO prior FROM refund WHERE reference=p_ref;
 IF prior IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM refund WHERE id=prior AND payment_id=p_payment AND amount=p_amount)
  THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='refund replay mismatch'; END IF;
  RETURN prior;
 END IF;
 IF order_key IS NULL OR p_amount<=0 OR p_amount<>ROUND(p_amount,2) OR p_amount>paid-COALESCE((SELECT SUM(amount) FROM refund WHERE payment_id=p_payment),0)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='refund exceeds payment'; END IF;
 INSERT INTO refund(payment_id,reference,amount) VALUES(p_payment,p_ref,p_amount);
 SET result=LAST_INSERT_ID();
 IF channel_name='wallet' THEN
 UPDATE account SET balance=balance+p_amount WHERE id=owner_key;
 INSERT INTO wallet_entry(account_id,refund_id,`change`) VALUES(owner_key,result,p_amount);
 END IF;
 UPDATE charge_order SET state='billed' WHERE id=order_key AND state='paid';
 RETURN result;
END$$
CREATE PROCEDURE approve_review(IN p_order bigint,IN p_reviewer bigint,IN p_adjustment decimal(12,2),IN p_conclusion varchar(255))
BEGIN
 UPDATE charge_order SET gross=gross+p_adjustment,state='billed' WHERE id=p_order AND state='review';
 IF ROW_COUNT()=0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='order not under review'; END IF;
 UPDATE order_review SET adjustment=p_adjustment,reviewed_by=p_reviewer,reviewed_at=NOW(6),conclusion=p_conclusion WHERE order_id=p_order;
END$$
DELIMITER ;
