CREATE VIEW v_order_balance AS SELECT o.*,COALESCE(p.total,0) received,COALESCE(r.total,0) refunded,
 COALESCE(r.reduction,0) refund_adjustment,
 o.gross-o.discount-COALESCE(r.reduction,0) net_due,
 o.gross-o.discount-COALESCE(r.reduction,0)-COALESCE(p.total,0)+COALESCE(r.total,0) outstanding
 FROM charge_order o
 LEFT JOIN (SELECT order_id,SUM(amount) total FROM payment WHERE succeeded GROUP BY order_id) p ON p.order_id=o.id
 LEFT JOIN (SELECT p.order_id,SUM(r.amount) total,SUM(r.debt_reduction) reduction FROM refund r JOIN payment p ON p.id=r.payment_id GROUP BY p.order_id) r ON r.order_id=o.id;
CREATE VIEW v_unpaid_order AS SELECT * FROM v_order_balance WHERE state='billed' AND outstanding>0;
CREATE VIEW v_band_income AS SELECT o.station_id,DATE(f.begins) service_day,f.label,SUM(f.kwh) kwh,SUM(f.energy) energy,SUM(f.service) service
 FROM fee_detail f JOIN charge_order o ON o.id=f.order_id
 WHERE o.state IN ('billed','paid') GROUP BY o.station_id,DATE(f.begins),f.label;
DELIMITER $$
CREATE FUNCTION post_payment(p_user bigint,p_order bigint,p_channel varchar(20),p_ref varchar(255),p_amount decimal(14,4),p_success boolean)
RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE order_key bigint; DECLARE prior bigint; DECLARE due decimal(12,2); DECLARE result bigint; DECLARE o_state varchar(20);
 DECLARE prior_order bigint; DECLARE prior_amount decimal(12,2); DECLARE prior_success boolean;
 DECLARE obligation decimal(12,2); DECLARE paid_total decimal(18,2); DECLARE refunded_total decimal(18,2); DECLARE reduced_total decimal(18,2);
 SELECT id,state,gross-discount INTO order_key,o_state,obligation FROM charge_order WHERE id=p_order AND account_id=p_user FOR UPDATE;
 IF order_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='order not found'; END IF;
 SELECT id,order_id,amount,succeeded INTO prior,prior_order,prior_amount,prior_success
  FROM payment WHERE channel=p_channel AND reference=p_ref FOR UPDATE;
 IF prior IS NOT NULL THEN
  IF prior_order<>p_order OR NOT(prior_amount<=>p_amount) OR NOT(prior_success<=>p_success)
  THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='payment replay mismatch'; END IF;
  RETURN prior;
 END IF;
 -- Current reads are required even when the caller already has a read snapshot.
 SELECT COALESCE(SUM(amount),0) INTO paid_total FROM payment WHERE order_id=order_key AND succeeded FOR UPDATE;
 SELECT COALESCE(SUM(r.amount),0),COALESCE(SUM(r.debt_reduction),0) INTO refunded_total,reduced_total
  FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=order_key FOR UPDATE;
 SET due=obligation-reduced_total-paid_total+refunded_total;
 IF o_state<>'billed' OR p_amount IS NULL OR p_amount<=0 OR p_amount<>ROUND(p_amount,2) OR p_amount>due
  OR p_channel NOT IN ('mock','wallet') OR p_success IS NULL OR p_ref IS NULL OR CHAR_LENGTH(TRIM(p_ref))=0
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid payment'; END IF;
 IF p_success THEN
  UPDATE charge_order SET wallet_hold=GREATEST(0,wallet_hold-p_amount) WHERE id=p_order;
 END IF;
 IF p_channel='wallet' AND p_success THEN
  UPDATE account SET balance=balance-p_amount WHERE id=p_user AND balance-reserved_balance>=p_amount;
  IF ROW_COUNT()=0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='insufficient unreserved wallet balance'; END IF;
 END IF;
 INSERT INTO payment(order_id,channel,reference,amount,succeeded) VALUES(p_order,p_channel,p_ref,p_amount,p_success);
 SET result=LAST_INSERT_ID();
 IF p_channel='wallet' AND p_success THEN INSERT INTO wallet_entry(account_id,payment_id,`change`) VALUES(p_user,result,-p_amount); END IF;
 IF p_success AND p_amount=due THEN UPDATE charge_order SET state='paid' WHERE id=p_order; END IF;
 RETURN result;
END$$
CREATE FUNCTION post_refund_kind(p_payment bigint,p_ref varchar(255),p_amount decimal(14,4),p_kind varchar(32))
RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE order_key bigint; DECLARE owner_key bigint; DECLARE channel_name varchar(20); DECLARE paid decimal(12,2);
 DECLARE prior bigint; DECLARE result bigint; DECLARE due decimal(12,2); DECLARE obligation decimal(12,2);
 DECLARE available_hold decimal(12,2); DECLARE card bigint;
 DECLARE prior_payment bigint; DECLARE prior_amount decimal(12,2); DECLARE prior_kind varchar(32);
 DECLARE paid_total decimal(18,2); DECLARE refunded_total decimal(18,2); DECLARE reduced_total decimal(18,2);
 DECLARE payment_refunded decimal(18,2);
 -- Lock the order before payment/refund rows; OF prevents a payment -> order inversion.
 SELECT o.id,o.account_id,o.fleet_card_id,o.gross-o.discount,p.channel,p.amount
  INTO order_key,owner_key,card,obligation,channel_name,paid
  FROM charge_order o JOIN payment p ON p.order_id=o.id WHERE p.id=p_payment AND p.succeeded FOR UPDATE OF o;
 SELECT id,payment_id,amount,kind INTO prior,prior_payment,prior_amount,prior_kind FROM refund WHERE reference=p_ref FOR UPDATE;
 IF prior IS NOT NULL THEN
  IF prior_payment<>p_payment OR NOT(prior_amount<=>p_amount) OR NOT(prior_kind<=>p_kind)
  THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='refund replay mismatch'; END IF;
  RETURN prior;
 END IF;
 SELECT COALESCE(SUM(amount),0) INTO paid_total FROM payment WHERE order_id=order_key AND succeeded FOR UPDATE;
 SELECT COALESCE(SUM(r.amount),0),COALESCE(SUM(r.debt_reduction),0),COALESCE(SUM(IF(r.payment_id=p_payment,r.amount,0)),0)
  INTO refunded_total,reduced_total,payment_refunded FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=order_key FOR UPDATE;
 IF order_key IS NULL OR p_amount IS NULL OR p_amount<=0 OR p_amount<>ROUND(p_amount,2)
  OR p_kind IS NULL OR p_kind NOT IN ('price_adjustment','payment_reversal') OR p_ref IS NULL OR CHAR_LENGTH(TRIM(p_ref))=0
  OR p_amount>paid-payment_refunded
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid refund or amount exceeds payment'; END IF;
 IF p_kind='price_adjustment' AND p_amount>obligation-reduced_total THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='price adjustment exceeds remaining obligation'; END IF;
 INSERT INTO refund(payment_id,reference,amount,kind,debt_reduction)
 VALUES(p_payment,p_ref,p_amount,p_kind,IF(p_kind='price_adjustment',p_amount,0));
 SET result=LAST_INSERT_ID();
 IF channel_name='wallet' THEN
  UPDATE account SET balance=balance+p_amount WHERE id=owner_key;
  INSERT INTO wallet_entry(account_id,refund_id,`change`) VALUES(owner_key,result,p_amount);
 END IF;
 SET due=obligation-reduced_total-IF(p_kind='price_adjustment',p_amount,0)-paid_total+refunded_total+p_amount;
 SELECT a.balance-a.reserved_balance+o.wallet_hold INTO available_hold FROM account a JOIN charge_order o ON o.account_id=a.id
  WHERE o.id=order_key FOR UPDATE;
 UPDATE charge_order SET state=IF(due=0,'paid','billed'),
  wallet_hold=IF(card IS NULL AND authorized_amount>0,LEAST(authorized_amount,GREATEST(0,due),available_hold),0) WHERE id=order_key;
 RETURN result;
END$$
-- Backwards-compatible default: a normal refund reduces the customer's obligation.
CREATE FUNCTION post_refund(p_payment bigint,p_ref varchar(255),p_amount decimal(14,4)) RETURNS bigint MODIFIES SQL DATA
BEGIN RETURN post_refund_kind(p_payment,p_ref,p_amount,'price_adjustment'); END$$
CREATE PROCEDURE approve_review(IN p_order bigint,IN p_reviewer bigint,IN p_adjustment decimal(12,2),IN p_conclusion varchar(255))
BEGIN
 DECLARE actual decimal(12,2); DECLARE budget decimal(12,2); DECLARE reduction decimal(12,2); DECLARE card bigint;
 DECLARE old_hold decimal(12,2); DECLARE period_key date;
 SELECT gross,authorized_amount,discount,fleet_card_id,fleet_hold,budget_period INTO actual,budget,reduction,card,old_hold,period_key FROM charge_order
  WHERE id=p_order AND state='review' FOR UPDATE;
 IF actual IS NULL OR p_adjustment IS NULL OR actual+p_adjustment<reduction
  OR p_conclusion IS NULL OR CHAR_LENGTH(TRIM(p_conclusion))=0
  OR NOT EXISTS(SELECT 1 FROM account WHERE id=p_reviewer AND role IN ('admin','settlement'))
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='valid reviewed order, reviewer and conclusion required'; END IF;
 SET actual=actual+p_adjustment;
 IF budget>0 AND actual-reduction>budget THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='additional authorization required before approving review'; END IF;
 IF card IS NOT NULL THEN CALL check_fleet_credit_current(card,p_order,period_key,old_hold,0,actual-reduction); END IF;
 UPDATE charge_order SET gross=actual,state=IF(actual=reduction,'paid','billed'),fleet_hold=0,
  wallet_hold=IF(card IS NULL AND budget>0,actual-reduction,0) WHERE id=p_order;
 UPDATE order_review SET adjustment=p_adjustment,reviewed_by=p_reviewer,reviewed_at=NOW(6),conclusion=p_conclusion WHERE order_id=p_order;
END$$
DELIMITER ;
