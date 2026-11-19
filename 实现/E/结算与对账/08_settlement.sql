CREATE TABLE settlement (
 id bigint AUTO_INCREMENT PRIMARY KEY, station_id bigint NOT NULL, FOREIGN KEY (station_id) REFERENCES station(id), operator_id bigint NOT NULL, FOREIGN KEY (operator_id) REFERENCES operator(id),
 period date NOT NULL CHECK(DAY(period)=1), state varchar(255) NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','confirmed','paid')),
 UNIQUE(operator_id,station_id,period)
) ENGINE=InnoDB;
CREATE TABLE settlement_item (
 settlement_id bigint NOT NULL, FOREIGN KEY (settlement_id) REFERENCES settlement(id), order_id bigint NOT NULL UNIQUE, FOREIGN KEY (order_id) REFERENCES charge_order(id),
 kwh decimal(18,4) NOT NULL, energy_share decimal(18,4) NOT NULL, service_share decimal(18,4) NOT NULL, platform_fee decimal(18,4) NOT NULL,
 net_received decimal(18,4) NOT NULL, PRIMARY KEY(settlement_id,order_id)
) ENGINE=InnoDB;
CREATE TABLE external_bill (
 settlement_id bigint NOT NULL, FOREIGN KEY (settlement_id) REFERENCES settlement(id), order_id bigint NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id),
 batch varchar(255) NOT NULL, kwh decimal(18,4) NOT NULL CHECK(kwh>=0), amount decimal(18,4) NOT NULL CHECK(amount>=0), paid boolean NOT NULL,
 PRIMARY KEY(settlement_id,order_id)
) ENGINE=InnoDB;
CREATE TABLE recon_diff (
 id bigint AUTO_INCREMENT PRIMARY KEY, settlement_id bigint NOT NULL, FOREIGN KEY (settlement_id) REFERENCES settlement(id),
 order_id bigint NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id), kind varchar(255) NOT NULL CHECK(kind IN ('energy','price','payment')),
 delta decimal(18,4) NOT NULL, conclusion varchar(255), UNIQUE(settlement_id,order_id,kind)
) ENGINE=InnoDB;
CREATE TABLE diff_confirmation (
 diff_id bigint, FOREIGN KEY (diff_id) REFERENCES recon_diff(id), side varchar(255) CHECK(side IN ('platform','operator')),
 actor bigint NOT NULL, FOREIGN KEY (actor) REFERENCES account(id), confirmed_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(diff_id,side)
) ENGINE=InnoDB;
CREATE TABLE settlement_adjustment (
 id bigint AUTO_INCREMENT PRIMARY KEY, settlement_id bigint NOT NULL, FOREIGN KEY (settlement_id) REFERENCES settlement(id),
 order_id bigint NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id), diff_id bigint UNIQUE, FOREIGN KEY (diff_id) REFERENCES recon_diff(id), refund_id bigint UNIQUE, FOREIGN KEY (refund_id) REFERENCES refund(id),
 amount decimal(18,4) NOT NULL, reason varchar(255) NOT NULL, CHECK(((diff_id IS NOT NULL)+(refund_id IS NOT NULL))=1)
) ENGINE=InnoDB;
CREATE TABLE settlement_invoice (
 id bigint AUTO_INCREMENT PRIMARY KEY, settlement_id bigint NOT NULL, FOREIGN KEY (settlement_id) REFERENCES settlement(id),
 title varchar(255) NOT NULL, tax_id varchar(255) NOT NULL, amount numeric(12,2) NOT NULL CHECK(amount>0),
 original_id bigint UNIQUE, FOREIGN KEY (original_id) REFERENCES settlement_invoice(id), issued_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

CREATE VIEW v_settlement AS SELECT s.*,COALESCE(i.kwh,0) kwh,COALESCE(i.energy,0) energy_share,
 COALESCE(i.service,0) service_share,COALESCE(i.fee,0) platform_fee,COALESCE(i.energy+i.service-i.fee,0)+COALESCE(a.amount,0) due,
 COALESCE(i.orders,0) orders FROM settlement s LEFT JOIN
 (SELECT settlement_id,SUM(kwh) kwh,SUM(energy_share) energy,SUM(service_share) service,SUM(platform_fee) fee,COUNT(*) orders
 FROM settlement_item GROUP BY settlement_id) i ON i.settlement_id=s.id
 LEFT JOIN (SELECT settlement_id,SUM(amount) amount FROM settlement_adjustment GROUP BY settlement_id) a ON a.settlement_id=s.id;
CREATE VIEW v_pending_diff AS SELECT d.* FROM recon_diff d WHERE (SELECT COUNT(*) FROM diff_confirmation c WHERE c.diff_id=d.id)<2;
CREATE VIEW v_invoice_balance AS SELECT s.*,COALESCE(i.net,0) invoiced,s.due-COALESCE(i.net,0) remaining
 FROM v_settlement s LEFT JOIN (SELECT settlement_id,SUM(IF(original_id IS NULL,amount,-amount)) net FROM settlement_invoice GROUP BY settlement_id) i ON i.settlement_id=s.id;
DELIMITER $$
CREATE PROCEDURE build_settlement(IN p_station bigint,IN p_period date)
main: BEGIN
 DECLARE k bigint; DECLARE owner_key bigint; DECLARE s_state varchar(20);
 SELECT operator_id INTO owner_key FROM station WHERE id=p_station FOR UPDATE;
 IF owner_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='station not found'; END IF;
 INSERT INTO settlement(station_id,operator_id,period) VALUES(p_station,owner_key,p_period) ON DUPLICATE KEY UPDATE id=id;
 SELECT id,state INTO k,s_state FROM settlement WHERE station_id=p_station AND operator_id=owner_key AND period=p_period FOR UPDATE;
 IF s_state<>'draft' THEN LEAVE main; END IF;
 INSERT INTO settlement_item(settlement_id,order_id,kwh,energy_share,service_share,platform_fee,net_received)
 SELECT k,o.id,o.kwh,ROUND(f.energy*.90,2),ROUND(f.service*.80,2),ROUND((o.gross-o.discount)*.02,2),o.received-o.refunded
 FROM v_order_balance o JOIN v_gun_state g ON g.id=o.connector_id
 JOIN (SELECT order_id,SUM(energy) energy,SUM(service) service FROM fee_detail GROUP BY order_id) f ON f.order_id=o.id
 WHERE g.station_id=p_station AND o.state='paid' AND o.outstanding=0 AND o.ended_at>=p_period AND o.ended_at<p_period+INTERVAL 1 MONTH
 ON DUPLICATE KEY UPDATE settlement_id=settlement_item.settlement_id;
 DELETE i FROM settlement_item i JOIN v_order_balance o ON i.order_id=o.id WHERE i.settlement_id=k AND (o.state<>'paid' OR o.outstanding<>0);
 INSERT INTO settlement_adjustment(settlement_id,order_id,refund_id,amount,reason)
 SELECT k,i.order_id,r.id,-r.amount,'prior period refund' FROM settlement_item i JOIN settlement previous ON previous.id=i.settlement_id
 JOIN payment p ON p.order_id=i.order_id JOIN refund r ON r.payment_id=p.id
 WHERE previous.station_id=p_station AND previous.period<p_period AND previous.state IN ('confirmed','paid')
 AND r.happened_at>=p_period AND r.happened_at<p_period+INTERVAL 1 MONTH
 ON DUPLICATE KEY UPDATE refund_id=settlement_adjustment.refund_id;
END$$
CREATE PROCEDURE compare_settlement(IN p_key bigint)
BEGIN
 DECLARE locked bigint;
 SELECT id INTO locked FROM settlement WHERE id=p_key AND state='draft' FOR UPDATE;
 IF locked IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='draft settlement required'; END IF;
 INSERT INTO recon_diff(settlement_id,order_id,kind,delta)
 SELECT i.settlement_id,i.order_id,x.kind,CASE x.kind WHEN 'price' THEN b.amount-i.net_received WHEN 'payment' THEN -i.net_received ELSE 0 END
 FROM settlement_item i JOIN external_bill b USING(settlement_id,order_id)
 CROSS JOIN (SELECT 'energy' kind UNION ALL SELECT 'price' UNION ALL SELECT 'payment') x WHERE i.settlement_id=p_key
 AND ((x.kind='energy' AND b.kwh<>i.kwh) OR (x.kind='price' AND b.amount<>i.net_received) OR (x.kind='payment' AND NOT b.paid))
 ON DUPLICATE KEY UPDATE id=recon_diff.id;
END$$
CREATE PROCEDURE confirm_difference(IN p_diff bigint,IN p_actor bigint,IN p_conclusion varchar(20))
BEGIN
 DECLARE k bigint; DECLARE owner_key bigint; DECLARE actor_operator bigint; DECLARE actor_role varchar(20); DECLARE party varchar(20);
 DECLARE old_conclusion varchar(255); DECLARE order_key bigint; DECLARE delta_fee decimal(18,4);
 SET k=(SELECT settlement_id FROM recon_diff WHERE id=p_diff);
 SELECT operator_id INTO owner_key FROM settlement WHERE id=k AND state='draft' FOR UPDATE;
 SELECT conclusion,order_id,delta INTO old_conclusion,order_key,delta_fee FROM recon_diff WHERE id=p_diff FOR UPDATE;
 SELECT role,operator_id INTO actor_role,actor_operator FROM account WHERE id=p_actor;
 SET party=CASE WHEN actor_role='operator' AND actor_operator=owner_key THEN 'operator'
 WHEN actor_role IN ('admin','settlement') THEN 'platform' END;
 IF owner_key IS NULL OR party IS NULL OR p_conclusion NOT IN ('accept','reject') OR
 (old_conclusion IS NOT NULL AND old_conclusion<>p_conclusion) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid confirmation'; END IF;
 UPDATE recon_diff SET conclusion=p_conclusion WHERE id=p_diff;
 INSERT INTO diff_confirmation(diff_id,side,actor) VALUES(p_diff,party,p_actor) ON DUPLICATE KEY UPDATE actor=diff_confirmation.actor;
 IF (SELECT COUNT(*) FROM diff_confirmation WHERE diff_id=p_diff)=2 THEN
 INSERT INTO settlement_adjustment(settlement_id,order_id,diff_id,amount,reason)
 VALUES(k,order_key,p_diff,IF(p_conclusion='accept',delta_fee,0),p_conclusion) ON DUPLICATE KEY UPDATE diff_id=settlement_adjustment.diff_id; END IF;
END$$
CREATE PROCEDURE confirm_settlement(IN p_key bigint)
BEGIN
 DECLARE locked bigint;
 SELECT id INTO locked FROM settlement WHERE id=p_key AND state='draft' FOR UPDATE;
 IF locked IS NULL OR EXISTS(SELECT 1 FROM v_pending_diff WHERE settlement_id=p_key)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='unconfirmed settlement or differences'; END IF;
 UPDATE settlement SET state='confirmed' WHERE id=p_key;
END$$
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
DELIMITER ;
