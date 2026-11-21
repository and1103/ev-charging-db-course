-- MySQL 8.4; every procedure uses the caller's transaction.
CREATE TABLE settlement (
 id bigint AUTO_INCREMENT PRIMARY KEY, station_id bigint NOT NULL, FOREIGN KEY(station_id) REFERENCES station(id),
 operator_id bigint NOT NULL, FOREIGN KEY(operator_id) REFERENCES operator(id),
 period date NOT NULL CHECK(DAY(period)=1), state varchar(20) NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','confirmed','paid')),
 created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), confirmed_at datetime(6), UNIQUE(operator_id,station_id,period)
) ENGINE=InnoDB;
CREATE TABLE settlement_item (
 settlement_id bigint NOT NULL, FOREIGN KEY(settlement_id) REFERENCES settlement(id),
 order_id bigint NOT NULL UNIQUE, FOREIGN KEY(order_id) REFERENCES charge_order(id), source_period date NOT NULL,
 kwh decimal(18,4) NOT NULL CHECK(kwh>=0), energy_share decimal(18,4) NOT NULL CHECK(energy_share>=0),
 service_share decimal(18,4) NOT NULL CHECK(service_share>=0), platform_fee decimal(18,4) NOT NULL CHECK(platform_fee>=0),
 net_received decimal(18,4) NOT NULL CHECK(net_received>=0), PRIMARY KEY(settlement_id,order_id)
) ENGINE=InnoDB;
CREATE TABLE settlement_import (
 settlement_id bigint PRIMARY KEY, FOREIGN KEY(settlement_id) REFERENCES settlement(id), batch varchar(255) NOT NULL,
 expected_rows integer NOT NULL CHECK(expected_rows BETWEEN 0 AND 10000),
 state varchar(20) NOT NULL DEFAULT 'open' CHECK(state IN ('open','complete')),
 opened_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), completed_at datetime(6)
) ENGINE=InnoDB;
CREATE TABLE external_bill (
 settlement_id bigint NOT NULL, FOREIGN KEY(settlement_id) REFERENCES settlement_import(settlement_id),
 -- Unknown external order references are retained as extra rows, without an order FK.
 order_id bigint NOT NULL CHECK(order_id>0),
 kwh decimal(18,4) NOT NULL CHECK(kwh>=0), amount decimal(18,4) NOT NULL, paid boolean NOT NULL,
 PRIMARY KEY(settlement_id,order_id)
) ENGINE=InnoDB;
CREATE TABLE recon_diff (
 id bigint AUTO_INCREMENT PRIMARY KEY, settlement_id bigint NOT NULL, FOREIGN KEY(settlement_id) REFERENCES settlement(id),
 order_id bigint NOT NULL, kind varchar(20) NOT NULL CHECK(kind IN ('energy','price','payment','missing','extra')),
 delta decimal(18,4) NOT NULL, expected_kwh decimal(18,4), actual_kwh decimal(18,4),
 expected_amount decimal(18,4), actual_amount decimal(18,4), proposed_adjustment decimal(18,4) NOT NULL DEFAULT 0,
 automatic_allowed boolean NOT NULL DEFAULT true, conclusion varchar(20) CHECK(conclusion IN ('accept','reject')),
 UNIQUE(settlement_id,order_id,kind)
) ENGINE=InnoDB;
CREATE TABLE diff_confirmation (
 diff_id bigint NOT NULL, FOREIGN KEY(diff_id) REFERENCES recon_diff(id),
 side varchar(20) NOT NULL CHECK(side IN ('platform','operator')), actor bigint NOT NULL, FOREIGN KEY(actor) REFERENCES account(id),
 conclusion varchar(20) NOT NULL CHECK(conclusion IN ('accept','reject')),
 confirmed_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(diff_id,side)
) ENGINE=InnoDB;
CREATE TABLE settlement_confirmation (
 settlement_id bigint NOT NULL, FOREIGN KEY(settlement_id) REFERENCES settlement(id),
 side varchar(20) NOT NULL CHECK(side IN ('platform','operator')), actor bigint NOT NULL, FOREIGN KEY(actor) REFERENCES account(id),
 confirmed_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(settlement_id,side)
) ENGINE=InnoDB;
CREATE TABLE settlement_adjustment (
 id bigint AUTO_INCREMENT PRIMARY KEY, settlement_id bigint NOT NULL, FOREIGN KEY(settlement_id) REFERENCES settlement(id),
 order_id bigint NOT NULL, diff_id bigint UNIQUE, FOREIGN KEY(diff_id) REFERENCES recon_diff(id),
 refund_id bigint UNIQUE, FOREIGN KEY(refund_id) REFERENCES refund(id), amount decimal(18,4) NOT NULL, reason varchar(255) NOT NULL,
 customer_reduction decimal(18,4) NOT NULL DEFAULT 0 CHECK(customer_reduction>=0),
 energy_reversal decimal(18,4) NOT NULL DEFAULT 0 CHECK(energy_reversal>=0),
 service_reversal decimal(18,4) NOT NULL DEFAULT 0 CHECK(service_reversal>=0),
 fee_reversal decimal(18,4) NOT NULL DEFAULT 0 CHECK(fee_reversal>=0),
 CHECK(((diff_id IS NOT NULL)+(refund_id IS NOT NULL))=1)
) ENGINE=InnoDB;
CREATE TABLE settlement_invoice (
 id bigint AUTO_INCREMENT PRIMARY KEY, settlement_id bigint NOT NULL, FOREIGN KEY(settlement_id) REFERENCES settlement(id),
 title varchar(255) NOT NULL, tax_id varchar(255) NOT NULL, amount numeric(12,2) NOT NULL CHECK(amount>0),
 original_id bigint UNIQUE, FOREIGN KEY(original_id) REFERENCES settlement_invoice(id), issued_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

CREATE VIEW v_settlement AS SELECT s.*,COALESCE(i.kwh,0) kwh,COALESCE(i.energy,0) energy_share,
 COALESCE(i.service,0) service_share,COALESCE(i.fee,0) platform_fee,
 COALESCE(i.energy+i.service-i.fee,0)+COALESCE(a.amount,0) due,COALESCE(i.orders,0) orders
 FROM settlement s LEFT JOIN (SELECT settlement_id,SUM(kwh) kwh,SUM(energy_share) energy,SUM(service_share) service,
 SUM(platform_fee) fee,COUNT(*) orders FROM settlement_item GROUP BY settlement_id) i ON i.settlement_id=s.id
 LEFT JOIN (SELECT settlement_id,SUM(amount) amount FROM settlement_adjustment GROUP BY settlement_id) a ON a.settlement_id=s.id;
CREATE VIEW v_pending_diff AS SELECT d.* FROM recon_diff d WHERE
 (SELECT COUNT(*) FROM diff_confirmation c WHERE c.diff_id=d.id)<>2 OR
 (SELECT COUNT(DISTINCT conclusion) FROM diff_confirmation c WHERE c.diff_id=d.id)<>1 OR
 (NOT d.automatic_allowed AND EXISTS(SELECT 1 FROM diff_confirmation c WHERE c.diff_id=d.id AND c.conclusion='accept'));
CREATE VIEW v_invoice_balance AS SELECT s.*,COALESCE(i.net,0) invoiced,s.due-COALESCE(i.net,0) remaining
 FROM v_settlement s LEFT JOIN (SELECT settlement_id,SUM(IF(original_id IS NULL,amount,-amount)) net
 FROM settlement_invoice GROUP BY settlement_id) i ON i.settlement_id=s.id;
-- Customer cash is reconciled separately from merchant allocation. A refund-only
-- month has negative cash and zero new kWh for the original order.
CREATE VIEW v_recon_expected AS SELECT settlement_id,order_id,SUM(kwh) kwh,SUM(amount) amount,SUM(merchant_due) merchant_due
 FROM (SELECT settlement_id,order_id,kwh,net_received amount,energy_share+service_share-platform_fee merchant_due FROM settlement_item
 UNION ALL SELECT settlement_id,order_id,0,-customer_reduction,amount FROM settlement_adjustment WHERE refund_id IS NOT NULL) expected_lines
 GROUP BY settlement_id,order_id;

DELIMITER $$
CREATE PROCEDURE assert_draft_settlement(IN p_key bigint)
BEGIN
 DECLARE k bigint;
 SELECT id INTO k FROM settlement WHERE id=p_key AND state='draft' FOR UPDATE;
 IF k IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='draft settlement required'; END IF;
END$$
CREATE PROCEDURE build_settlement(IN p_station bigint,IN p_period date)
main: BEGIN
 DECLARE finished boolean DEFAULT false; DECLARE k bigint; DECLARE owner_key bigint; DECLARE station_key bigint;
 DECLARE bills CURSOR FOR SELECT id,operator_id FROM settlement WHERE station_id=p_station AND period=p_period AND state='draft' ORDER BY operator_id;
 DECLARE CONTINUE HANDLER FOR NOT FOUND SET finished=true;
 IF p_period IS NULL OR DAY(p_period)<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='period must be first day of month'; END IF;
 SELECT id INTO station_key FROM station WHERE id=p_station FOR UPDATE;
 IF station_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='station not found'; END IF;
 INSERT INTO settlement(station_id,operator_id,period)
 SELECT p_station,owners.operator_id,p_period FROM (
  SELECT operator_id FROM station WHERE id=p_station
  UNION SELECT operator_id FROM charge_order WHERE station_id=p_station AND ended_at<p_period+INTERVAL 1 MONTH
  UNION SELECT s.operator_id FROM settlement s JOIN settlement_item i ON i.settlement_id=s.id
  JOIN payment p ON p.order_id=i.order_id JOIN refund r ON r.payment_id=p.id
  WHERE s.station_id=p_station AND r.debt_reduction>0 AND r.happened_at<p_period+INTERVAL 1 MONTH
 ) owners ON DUPLICATE KEY UPDATE id=settlement.id;
 SET finished=false;
 OPEN bills;
 bill_loop: LOOP
  FETCH bills INTO k,owner_key;
  IF finished THEN LEAVE bill_loop; END IF;
  CALL assert_draft_settlement(k);
  IF NOT EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=k)
   AND NOT EXISTS(SELECT 1 FROM settlement_confirmation WHERE settlement_id=k) THEN
   INSERT INTO settlement_item(settlement_id,order_id,source_period,kwh,energy_share,service_share,platform_fee,net_received)
   SELECT k,o.id,CAST(DATE_FORMAT(o.ended_at,'%Y-%m-01') AS DATE),o.kwh,
    -- Positive minimum/review adjustments are service revenue. Negative review
    -- adjustments reduce both original components proportionally; coupons then
    -- reduce the resulting bases proportionally. Zero-meter minimums stay valid.
    ROUND((o.gross-o.discount)*.90*IF(GREATEST(o.gross,f.energy+f.service)=0,0,f.energy/GREATEST(o.gross,f.energy+f.service)),2),
    ROUND((o.gross-o.discount)*.80*(1-IF(GREATEST(o.gross,f.energy+f.service)=0,0,f.energy/GREATEST(o.gross,f.energy+f.service))),2),
    ROUND((o.gross-o.discount)*.02,2),o.gross-o.discount
   FROM v_order_balance o JOIN (SELECT order_id,SUM(energy) energy,SUM(service) service FROM fee_detail GROUP BY order_id) f ON f.order_id=o.id
   WHERE o.station_id=p_station AND o.operator_id=owner_key AND o.state='paid' AND o.outstanding=0
    AND o.ended_at<p_period+INTERVAL 1 MONTH
    AND NOT EXISTS(SELECT 1 FROM settlement_item prior_item WHERE prior_item.order_id=o.id);
   -- Read parent snapshots before the child INSERT. Reading settlement in that
   -- INSERT's SELECT would conflict with its trigger locking settlement (1442).
   BEGIN
    DECLARE refund_done boolean DEFAULT false;
    DECLARE prior_order bigint; DECLARE prior_cash decimal(18,4);
    DECLARE prior_energy decimal(18,4); DECLARE prior_service decimal(18,4); DECLARE prior_fee decimal(18,4);
    DECLARE refundable_orders CURSOR FOR
     SELECT i.order_id,i.net_received,i.energy_share,i.service_share,i.platform_fee
     FROM settlement_item i JOIN settlement source_bill ON source_bill.id=i.settlement_id
     WHERE source_bill.station_id=p_station AND source_bill.operator_id=owner_key AND source_bill.period<=p_period
      AND (source_bill.id=k OR source_bill.state IN ('confirmed','paid')) AND i.net_received>0;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET refund_done=true;
    OPEN refundable_orders;
    refund_loop: LOOP
     FETCH refundable_orders INTO prior_order,prior_cash,prior_energy,prior_service,prior_fee;
     IF refund_done THEN LEAVE refund_loop; END IF;
     INSERT INTO settlement_adjustment(settlement_id,order_id,refund_id,amount,reason,
      customer_reduction,energy_reversal,service_reversal,fee_reversal)
     SELECT k,prior_order,x.refund_id,-x.er-x.sr+x.fr,'refund reverses original allocation',x.debt_reduction,x.er,x.sr,x.fr
     FROM (SELECT r.id refund_id,r.debt_reduction,r.happened_at,
      ROUND(prior_energy*LEAST(1,r.cumulative/prior_cash),2)-ROUND(prior_energy*LEAST(1,(r.cumulative-r.debt_reduction)/prior_cash),2) er,
      ROUND(prior_service*LEAST(1,r.cumulative/prior_cash),2)-ROUND(prior_service*LEAST(1,(r.cumulative-r.debt_reduction)/prior_cash),2) sr,
      ROUND(prior_fee*LEAST(1,r.cumulative/prior_cash),2)-ROUND(prior_fee*LEAST(1,(r.cumulative-r.debt_reduction)/prior_cash),2) fr
      FROM (SELECT r.id,r.happened_at,r.debt_reduction,
       SUM(r.debt_reduction) OVER(ORDER BY r.id ROWS UNBOUNDED PRECEDING) cumulative
       FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=prior_order) r
      WHERE r.debt_reduction>0
     ) x WHERE x.happened_at<p_period+INTERVAL 1 MONTH
      AND NOT EXISTS(SELECT 1 FROM settlement_adjustment posted WHERE posted.refund_id=x.refund_id);
    END LOOP;
    CLOSE refundable_orders;
   END;
  END IF;
 END LOOP;
 CLOSE bills;
END$$
CREATE PROCEDURE begin_bill_import(IN p_key bigint,IN p_batch varchar(255),IN p_expected_rows integer)
BEGIN
 CALL assert_draft_settlement(p_key);
 IF p_batch IS NULL OR CHAR_LENGTH(TRIM(p_batch))=0 OR p_expected_rows IS NULL OR p_expected_rows<0 OR p_expected_rows>10000
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid batch reference or declared row count'; END IF;
 IF EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=p_key)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='batch exists; reset draft import before replacing it'; END IF;
 INSERT INTO settlement_import(settlement_id,batch,expected_rows) VALUES(p_key,p_batch,p_expected_rows);
END$$
CREATE PROCEDURE compare_settlement(IN p_key bigint)
main: BEGIN
 DECLARE declared_rows integer; DECLARE batch_state varchar(20);
 CALL assert_draft_settlement(p_key);
 SELECT expected_rows,state INTO declared_rows,batch_state FROM settlement_import WHERE settlement_id=p_key FOR UPDATE;
 IF declared_rows IS NULL OR declared_rows<>(SELECT COUNT(*) FROM external_bill WHERE settlement_id=p_key)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='missing or incomplete external bill batch'; END IF;
 IF batch_state='complete' THEN LEAVE main; END IF;
 UPDATE settlement_import SET state='complete',completed_at=SYSDATE(6) WHERE settlement_id=p_key;
 INSERT INTO recon_diff(settlement_id,order_id,kind,delta,expected_kwh,actual_kwh,expected_amount,actual_amount,proposed_adjustment,automatic_allowed)
 SELECT p_key,e.order_id,'missing',-e.amount,e.kwh,NULL,e.amount,NULL,-e.merchant_due,true
 FROM v_recon_expected e LEFT JOIN external_bill b USING(settlement_id,order_id) WHERE e.settlement_id=p_key AND b.order_id IS NULL;
 INSERT INTO recon_diff(settlement_id,order_id,kind,delta,expected_kwh,actual_kwh,expected_amount,actual_amount,automatic_allowed)
 SELECT p_key,b.order_id,'extra',b.amount,NULL,b.kwh,NULL,b.amount,false
 FROM external_bill b LEFT JOIN v_recon_expected e USING(settlement_id,order_id) WHERE b.settlement_id=p_key AND e.order_id IS NULL;
 INSERT INTO recon_diff(settlement_id,order_id,kind,delta,expected_kwh,actual_kwh,expected_amount,actual_amount,proposed_adjustment,automatic_allowed)
 SELECT p_key,e.order_id,x.kind,
  CASE x.kind WHEN 'energy' THEN b.kwh-e.kwh WHEN 'price' THEN b.amount-e.amount ELSE -e.amount END,
  e.kwh,b.kwh,e.amount,b.amount,
  CASE WHEN x.kind='payment' THEN -e.merchant_due
   WHEN x.kind='price' AND b.paid AND e.amount<>0 THEN ROUND((b.amount-e.amount)*e.merchant_due/e.amount,2) ELSE 0 END,
  NOT(x.kind='price' AND b.paid AND e.amount=0 AND b.amount<>0)
 FROM v_recon_expected e JOIN external_bill b USING(settlement_id,order_id)
 CROSS JOIN (SELECT 'energy' kind UNION ALL SELECT 'price' UNION ALL SELECT 'payment') x
 WHERE e.settlement_id=p_key AND ((x.kind='energy' AND b.kwh<>e.kwh) OR (x.kind='price' AND b.amount<>e.amount) OR (x.kind='payment' AND NOT b.paid));
END$$
CREATE PROCEDURE reset_bill_import(IN p_key bigint)
BEGIN
 CALL assert_draft_settlement(p_key);
 DELETE FROM settlement_confirmation WHERE settlement_id=p_key;
 DELETE c FROM diff_confirmation c JOIN recon_diff d ON d.id=c.diff_id WHERE d.settlement_id=p_key;
 DELETE FROM settlement_adjustment WHERE settlement_id=p_key AND diff_id IS NOT NULL;
 DELETE FROM recon_diff WHERE settlement_id=p_key;
 DELETE FROM external_bill WHERE settlement_id=p_key;
 DELETE FROM settlement_import WHERE settlement_id=p_key;
END$$
CREATE PROCEDURE confirm_difference(IN p_diff bigint,IN p_actor bigint,IN p_conclusion varchar(20))
BEGIN
 DECLARE k bigint; DECLARE owner_key bigint; DECLARE actor_operator bigint; DECLARE actor_role varchar(20); DECLARE party varchar(20);
 DECLARE agreed varchar(20); DECLARE order_key bigint; DECLARE delta_fee decimal(18,4); DECLARE can_apply boolean;
 SET k=(SELECT settlement_id FROM recon_diff WHERE id=p_diff);
 CALL assert_draft_settlement(k);
 SELECT operator_id INTO owner_key FROM settlement WHERE id=k;
 SELECT order_id,proposed_adjustment,automatic_allowed INTO order_key,delta_fee,can_apply FROM recon_diff WHERE id=p_diff FOR UPDATE;
 SELECT role,operator_id INTO actor_role,actor_operator FROM account WHERE id=p_actor;
 SET party=CASE WHEN actor_role='operator' AND actor_operator=owner_key THEN 'operator' WHEN actor_role IN ('admin','settlement') THEN 'platform' END;
 IF party IS NULL OR p_conclusion IS NULL OR p_conclusion NOT IN ('accept','reject')
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid difference confirmation actor or conclusion'; END IF;
 DELETE FROM settlement_confirmation WHERE settlement_id=k;
 INSERT INTO diff_confirmation(diff_id,side,actor,conclusion) VALUES(p_diff,party,p_actor,p_conclusion)
 ON DUPLICATE KEY UPDATE actor=p_actor,conclusion=p_conclusion,confirmed_at=SYSDATE(6);
 SET agreed=(SELECT CASE WHEN COUNT(*)=2 AND COUNT(DISTINCT conclusion)=1 THEN MIN(conclusion) END FROM diff_confirmation WHERE diff_id=p_diff);
 UPDATE recon_diff SET conclusion=agreed WHERE id=p_diff;
 DELETE FROM settlement_adjustment WHERE diff_id=p_diff;
 IF agreed IS NOT NULL AND (agreed='reject' OR can_apply) THEN
  INSERT INTO settlement_adjustment(settlement_id,order_id,diff_id,amount,reason)
  VALUES(k,order_key,p_diff,IF(agreed='accept',delta_fee,0),CONCAT('both parties ',agreed));
 END IF;
END$$
CREATE PROCEDURE confirm_settlement(IN p_key bigint,IN p_actor bigint)
BEGIN
 DECLARE owner_key bigint; DECLARE actor_operator bigint; DECLARE actor_role varchar(20); DECLARE party varchar(20);
 CALL assert_draft_settlement(p_key);
 SELECT operator_id INTO owner_key FROM settlement WHERE id=p_key;
 SELECT role,operator_id INTO actor_role,actor_operator FROM account WHERE id=p_actor;
 SET party=CASE WHEN actor_role='operator' AND actor_operator=owner_key THEN 'operator' WHEN actor_role IN ('admin','settlement') THEN 'platform' END;
 IF party IS NULL OR NOT EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=p_key AND state='complete')
 OR EXISTS(SELECT 1 FROM v_pending_diff WHERE settlement_id=p_key)
 OR EXISTS(SELECT 1 FROM settlement_item i JOIN v_order_balance o ON o.id=i.order_id WHERE i.settlement_id=p_key AND o.outstanding>0)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='completed batch, collectible orders and matching bilateral opinions required'; END IF;
 INSERT INTO settlement_confirmation(settlement_id,side,actor) VALUES(p_key,party,p_actor) ON DUPLICATE KEY UPDATE actor=settlement_confirmation.actor;
 IF (SELECT COUNT(*) FROM settlement_confirmation WHERE settlement_id=p_key)=2 THEN
  UPDATE settlement SET state='confirmed',confirmed_at=SYSDATE(6) WHERE id=p_key;
 END IF;
END$$
CREATE TRIGGER settlement_state_guard BEFORE UPDATE ON settlement FOR EACH ROW
BEGIN
 IF NEW.id<>OLD.id OR NEW.station_id<>OLD.station_id OR NEW.operator_id<>OLD.operator_id OR NEW.period<>OLD.period
 OR NOT(NEW.created_at<=>OLD.created_at)
 OR (OLD.state<>'draft' AND ((NEW.state<>OLD.state AND NOT(OLD.state='confirmed' AND NEW.state='paid')) OR NOT(NEW.confirmed_at<=>OLD.confirmed_at)))
 OR (OLD.state='draft' AND NEW.state NOT IN ('draft','confirmed'))
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='settlement identity or confirmed ledger is immutable'; END IF;
 IF OLD.state='draft' AND NEW.state='confirmed' AND
 ((SELECT COUNT(*) FROM settlement_confirmation WHERE settlement_id=OLD.id)<>2
 OR NOT EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=OLD.id AND state='complete')
 OR EXISTS(SELECT 1 FROM v_pending_diff WHERE settlement_id=OLD.id))
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='bilateral confirmation required'; END IF;
END$$
CREATE TRIGGER settlement_delete_guard BEFORE DELETE ON settlement FOR EACH ROW
BEGIN IF OLD.state<>'draft' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='confirmed settlement cannot be deleted'; END IF; END$$
CREATE TRIGGER external_bill_insert_guard BEFORE INSERT ON external_bill FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
 IF NOT EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=NEW.settlement_id AND state='open')
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='open declared batch required'; END IF;
END$$
CREATE TRIGGER external_bill_update_guard BEFORE UPDATE ON external_bill FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='import rows immutable; reset entire draft batch'; END$$
CREATE TRIGGER invoice_limit BEFORE INSERT ON settlement_invoice FOR EACH ROW
BEGIN
 DECLARE locked bigint; DECLARE limit_fee decimal(18,4); DECLARE original_fee decimal(12,2);
 SELECT id INTO locked FROM settlement WHERE id=NEW.settlement_id AND state IN ('confirmed','paid') FOR UPDATE;
 IF locked IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='settlement is not confirmed'; END IF;
 IF NEW.original_id IS NULL THEN
  SELECT remaining INTO limit_fee FROM v_invoice_balance WHERE id=NEW.settlement_id;
  IF NEW.amount>limit_fee THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invoice limit exceeded'; END IF;
 ELSE
  SELECT amount INTO original_fee FROM settlement_invoice WHERE id=NEW.original_id AND settlement_id=NEW.settlement_id AND original_id IS NULL;
  IF original_fee IS NULL OR NEW.amount<>original_fee THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='red invoice must reverse full amount'; END IF;
 END IF;
END$$
CREATE TRIGGER invoice_update_guard BEFORE UPDATE ON settlement_invoice FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='issued invoice immutable; issue red invoice'; END$$
CREATE TRIGGER invoice_delete_guard BEFORE DELETE ON settlement_invoice FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='issued invoice immutable; issue red invoice'; END$$
DELIMITER ;

-- Ledger mutations always lock and check the parent, including direct SQL.
DELIMITER $$
CREATE TRIGGER settlement_item_insert_guard BEFORE INSERT ON settlement_item FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
 IF EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=NEW.settlement_id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='reset draft import before changing ledger'; END IF;
END$$
CREATE TRIGGER settlement_item_update_guard BEFORE UPDATE ON settlement_item FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
 IF NEW.settlement_id<>OLD.settlement_id THEN CALL assert_draft_settlement(OLD.settlement_id); END IF;
 IF EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=NEW.settlement_id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='reset draft import before changing ledger'; END IF;
END$$
CREATE TRIGGER settlement_item_delete_guard BEFORE DELETE ON settlement_item FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(OLD.settlement_id);
 IF EXISTS(SELECT 1 FROM settlement_import WHERE settlement_id=OLD.settlement_id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='reset draft import before changing ledger'; END IF;
END$$
CREATE TRIGGER settlement_import_insert_guard BEFORE INSERT ON settlement_import FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
END$$
CREATE TRIGGER settlement_import_update_guard BEFORE UPDATE ON settlement_import FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
 IF NEW.settlement_id<>OLD.settlement_id THEN CALL assert_draft_settlement(OLD.settlement_id); END IF;
 IF NEW.batch<>OLD.batch OR NEW.expected_rows<>OLD.expected_rows OR OLD.state<>'open' OR NEW.state<>'complete'
 OR (SELECT COUNT(*) FROM external_bill WHERE settlement_id=OLD.settlement_id)<>OLD.expected_rows
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid import completion'; END IF;
END$$
CREATE TRIGGER settlement_import_delete_guard BEFORE DELETE ON settlement_import FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(OLD.settlement_id);
END$$
CREATE TRIGGER recon_diff_insert_guard BEFORE INSERT ON recon_diff FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
END$$
CREATE TRIGGER recon_diff_update_guard BEFORE UPDATE ON recon_diff FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
 IF NEW.settlement_id<>OLD.settlement_id THEN CALL assert_draft_settlement(OLD.settlement_id); END IF;
END$$
CREATE TRIGGER recon_diff_delete_guard BEFORE DELETE ON recon_diff FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(OLD.settlement_id);
END$$
CREATE TRIGGER settlement_adjustment_insert_guard BEFORE INSERT ON settlement_adjustment FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
END$$
CREATE TRIGGER settlement_adjustment_update_guard BEFORE UPDATE ON settlement_adjustment FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
 IF NEW.settlement_id<>OLD.settlement_id THEN CALL assert_draft_settlement(OLD.settlement_id); END IF;
END$$
CREATE TRIGGER settlement_adjustment_delete_guard BEFORE DELETE ON settlement_adjustment FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(OLD.settlement_id);
END$$
CREATE TRIGGER settlement_confirmation_insert_guard BEFORE INSERT ON settlement_confirmation FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
END$$
CREATE TRIGGER settlement_confirmation_update_guard BEFORE UPDATE ON settlement_confirmation FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(NEW.settlement_id);
 IF NEW.settlement_id<>OLD.settlement_id THEN CALL assert_draft_settlement(OLD.settlement_id); END IF;
END$$
CREATE TRIGGER settlement_confirmation_delete_guard BEFORE DELETE ON settlement_confirmation FOR EACH ROW
BEGIN
 CALL assert_draft_settlement(OLD.settlement_id);
END$$
CREATE TRIGGER external_bill_delete_guard BEFORE DELETE ON external_bill FOR EACH ROW
BEGIN CALL assert_draft_settlement(OLD.settlement_id); END$$
CREATE TRIGGER diff_confirmation_insert_guard BEFORE INSERT ON diff_confirmation FOR EACH ROW
BEGIN
 DECLARE k bigint;
 SET k=(SELECT settlement_id FROM recon_diff WHERE id=NEW.diff_id);
 CALL assert_draft_settlement(k);
END$$
CREATE TRIGGER diff_confirmation_update_guard BEFORE UPDATE ON diff_confirmation FOR EACH ROW
BEGIN
 DECLARE k bigint;
 SET k=(SELECT settlement_id FROM recon_diff WHERE id=OLD.diff_id);
 CALL assert_draft_settlement(k);
 IF NEW.diff_id<>OLD.diff_id OR NEW.side<>OLD.side THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='confirmation identity immutable'; END IF;
END$$
CREATE TRIGGER diff_confirmation_delete_guard BEFORE DELETE ON diff_confirmation FOR EACH ROW
BEGIN
 DECLARE k bigint;
 SET k=(SELECT settlement_id FROM recon_diff WHERE id=OLD.diff_id);
 CALL assert_draft_settlement(k);
END$$
DELIMITER ;

-- Educational invoice records, without a commercial tax-provider integration.
CREATE TABLE consumer_invoice (
 id bigint AUTO_INCREMENT PRIMARY KEY,
 request_id bigint NOT NULL, FOREIGN KEY(request_id) REFERENCES consumer_invoice_request(id),
 title varchar(255) NOT NULL, tax_id varchar(255) NOT NULL, amount decimal(12,2) NOT NULL CHECK(amount>0),
 original_id bigint UNIQUE, FOREIGN KEY(original_id) REFERENCES consumer_invoice(id),
 issued_by bigint NOT NULL, FOREIGN KEY(issued_by) REFERENCES account(id),
 issued_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE VIEW v_consumer_invoice_balance AS SELECT o.id order_id,
 GREATEST(0,LEAST(o.net_due,o.received-o.refunded)) limit_amount,
 COALESCE(i.net,0) invoiced,GREATEST(0,LEAST(o.net_due,o.received-o.refunded))-COALESCE(i.net,0) remaining
 FROM v_order_balance o LEFT JOIN (SELECT r.order_id,SUM(IF(i.original_id IS NULL,i.amount,-i.amount)) net
 FROM consumer_invoice i JOIN consumer_invoice_request r ON r.id=i.request_id GROUP BY r.order_id) i ON i.order_id=o.id;
DELIMITER $$
CREATE TRIGGER consumer_invoice_request_identity BEFORE UPDATE ON consumer_invoice_request FOR EACH ROW
BEGIN
 IF NEW.order_id<>OLD.order_id THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invoice request order is immutable'; END IF;
END$$
CREATE PROCEDURE issue_consumer_invoice(IN p_request bigint,IN p_actor bigint,IN p_tax varchar(255),IN p_amount decimal(12,2))
BEGIN
 DECLARE order_key bigint; DECLARE k bigint; DECLARE available decimal(12,2);
 DECLARE request_title varchar(255); DECLARE order_state varchar(20); DECLARE request_state varchar(20);
 SET order_key=(SELECT order_id FROM consumer_invoice_request WHERE id=p_request);
 SELECT id,state INTO k,order_state FROM charge_order WHERE id=order_key FOR UPDATE;
 SELECT title,state INTO request_title,request_state FROM consumer_invoice_request WHERE id=p_request FOR UPDATE;
 IF k IS NULL OR order_state<>'paid' OR request_state='rejected'
 OR NOT EXISTS(SELECT 1 FROM account WHERE id=p_actor AND role IN ('admin','settlement'))
 OR p_tax IS NULL OR CHAR_LENGTH(TRIM(p_tax))=0 OR p_amount IS NULL OR p_amount<=0
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='paid order, authorized reviewer and positive invoice amount required'; END IF;
 SELECT remaining INTO available FROM v_consumer_invoice_balance WHERE order_id=order_key;
 IF p_amount>available THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='consumer invoice exceeds net paid/net due limit'; END IF;
 INSERT INTO consumer_invoice(request_id,title,tax_id,amount,issued_by)
 VALUES(p_request,request_title,p_tax,p_amount,p_actor);
 UPDATE consumer_invoice_request SET state='issued' WHERE id=p_request;
END$$
CREATE PROCEDURE reverse_consumer_invoice(IN p_invoice bigint,IN p_actor bigint)
BEGIN
 DECLARE order_key bigint; DECLARE k bigint; DECLARE request_key bigint;
 SET order_key=(SELECT r.order_id FROM consumer_invoice i JOIN consumer_invoice_request r ON r.id=i.request_id
                WHERE i.id=p_invoice AND i.original_id IS NULL);
 SELECT id INTO k FROM charge_order WHERE id=order_key FOR UPDATE;
 IF k IS NULL OR NOT EXISTS(SELECT 1 FROM account WHERE id=p_actor AND role IN ('admin','settlement'))
 OR EXISTS(SELECT 1 FROM consumer_invoice WHERE original_id=p_invoice)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='authorized original invoice without prior red reversal required'; END IF;
 SET request_key=(SELECT request_id FROM consumer_invoice WHERE id=p_invoice);
 INSERT INTO consumer_invoice(request_id,title,tax_id,amount,original_id,issued_by)
 SELECT request_id,title,tax_id,amount,id,p_actor FROM consumer_invoice WHERE id=p_invoice;
 UPDATE consumer_invoice_request SET state=IF(
 (SELECT invoiced FROM v_consumer_invoice_balance WHERE order_id=order_key)>0,'issued','pending') WHERE id=request_key;
END$$
CREATE TRIGGER consumer_invoice_insert_guard BEFORE INSERT ON consumer_invoice FOR EACH ROW
BEGIN
 DECLARE k bigint; DECLARE request_order bigint; DECLARE available decimal(12,2); DECLARE original_fee decimal(12,2);
 SELECT order_id INTO request_order FROM consumer_invoice_request WHERE id=NEW.request_id;
 SELECT id INTO k FROM charge_order WHERE id=request_order FOR UPDATE;
 IF k IS NULL
 OR NOT EXISTS(SELECT 1 FROM account WHERE id=NEW.issued_by AND role IN ('admin','settlement'))
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid invoice order/request/reviewer'; END IF;
 IF NEW.original_id IS NULL THEN
  SELECT remaining INTO available FROM v_consumer_invoice_balance WHERE order_id=request_order;
  IF available IS NULL OR NEW.amount>available OR NOT EXISTS(SELECT 1 FROM charge_order WHERE id=request_order AND state='paid')
  THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='consumer invoice limit exceeded'; END IF;
 ELSE
  SELECT amount INTO original_fee FROM consumer_invoice WHERE id=NEW.original_id
   AND request_id=NEW.request_id AND original_id IS NULL
   AND title=NEW.title AND tax_id=NEW.tax_id;
  IF original_fee IS NULL OR NEW.amount<>original_fee THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='red invoice must reverse original amount and identity'; END IF;
 END IF;
END$$
CREATE TRIGGER consumer_invoice_update_guard BEFORE UPDATE ON consumer_invoice FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='consumer invoice immutable; retain original and red invoice'; END$$
CREATE TRIGGER consumer_invoice_delete_guard BEFORE DELETE ON consumer_invoice FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='consumer invoice immutable; retain original and red invoice'; END$$
CREATE TRIGGER refund_invoice_guard BEFORE INSERT ON refund FOR EACH ROW
BEGIN
 DECLARE order_key bigint; DECLARE net_limit decimal(12,2); DECLARE current_invoice decimal(12,2);
 SET order_key=(SELECT order_id FROM payment WHERE id=NEW.payment_id);
 SELECT GREATEST(0,LEAST(net_due-NEW.debt_reduction,received-refunded-NEW.amount))
 INTO net_limit FROM v_order_balance WHERE id=order_key;
 SELECT COALESCE(SUM(IF(i.original_id IS NULL,i.amount,-i.amount)),0) INTO current_invoice
 FROM consumer_invoice i JOIN consumer_invoice_request r ON r.id=i.request_id WHERE r.order_id=order_key;
 IF current_invoice>net_limit THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='red reverse consumer invoices before refund'; END IF;
END$$
DELIMITER ;
