CREATE TABLE tariff (
 id bigint AUTO_INCREMENT PRIMARY KEY, station_id bigint NOT NULL, FOREIGN KEY (station_id) REFERENCES station(id), fleet_id bigint, FOREIGN KEY (fleet_id) REFERENCES fleet(id),
 starts datetime(6) NOT NULL, ends datetime(6) NOT NULL,
 service_mode varchar(255) NOT NULL CHECK(service_mode IN ('kwh','hour')),
 free_minutes integer NOT NULL DEFAULT 0 CHECK(free_minutes>=0), minimum numeric(12,2) NOT NULL DEFAULT 0 CHECK(minimum>=0),
 authorization_amount numeric(12,2) NOT NULL DEFAULT 20 CHECK(authorization_amount>0), CHECK(ends>starts)
) ENGINE=InnoDB;
CREATE TABLE tariff_band (
 tariff_id bigint NOT NULL, FOREIGN KEY (tariff_id) REFERENCES tariff(id), minute_from integer NOT NULL, minute_to integer NOT NULL,
 label varchar(255) NOT NULL CHECK(label IN ('peak','flat','valley')), energy_rate numeric(8,4) NOT NULL CHECK(energy_rate>=0),
 service_rate numeric(8,4) NOT NULL CHECK(service_rate>=0),
 PRIMARY KEY(tariff_id,minute_from), CHECK(0<=minute_from AND minute_from<minute_to AND minute_to<=1440)
) ENGINE=InnoDB;
CREATE TABLE charge_order (
 id bigint AUTO_INCREMENT PRIMARY KEY, account_id bigint NOT NULL, FOREIGN KEY (account_id) REFERENCES account(id),
 connector_id bigint NOT NULL, FOREIGN KEY (connector_id) REFERENCES connector(id), vehicle_id bigint NOT NULL, FOREIGN KEY (vehicle_id) REFERENCES vehicle(id),
 tariff_id bigint NOT NULL, FOREIGN KEY (tariff_id) REFERENCES tariff(id), fleet_card_id bigint, FOREIGN KEY (fleet_card_id) REFERENCES fleet_card(id),
 station_id bigint NOT NULL DEFAULT 0, FOREIGN KEY (station_id) REFERENCES station(id),
 operator_id bigint NOT NULL DEFAULT 0, FOREIGN KEY (operator_id) REFERENCES operator(id),
 budget_period date NOT NULL DEFAULT '2000-01-01',
 authorized_amount numeric(12,2) NOT NULL DEFAULT 0 CHECK(authorized_amount>=0),
 wallet_hold numeric(12,2) NOT NULL DEFAULT 0, fleet_hold numeric(12,2) NOT NULL DEFAULT 0,
 budget_exceeded boolean NOT NULL DEFAULT false, stop_requested_at datetime(6),
 started_at datetime(6) NOT NULL, ended_at datetime(6), start_soc numeric(5,2), end_soc numeric(5,2),
 state varchar(255) NOT NULL CHECK(state IN ('starting','charging','finishing','review','billed','paid','cancelled')),
 kwh numeric(12,4) CHECK(kwh>=0), gross numeric(12,2) CHECK(gross>=0), discount numeric(12,2) NOT NULL DEFAULT 0,
 CHECK(ended_at IS NULL OR ended_at>started_at), CHECK(start_soc BETWEEN 0 AND 100), CHECK(end_soc BETWEEN 0 AND 100),
 CHECK(discount>=0 AND (gross IS NULL OR discount<=gross)),
 CHECK(wallet_hold>=0 AND wallet_hold<=authorized_amount AND fleet_hold>=0 AND fleet_hold<=authorized_amount),
 CHECK((fleet_card_id IS NULL AND fleet_hold=0) OR (fleet_card_id IS NOT NULL AND wallet_hold=0))
) ENGINE=InnoDB;
CREATE INDEX order_connector_end ON charge_order(connector_id,ended_at);
CREATE INDEX order_owner_time ON charge_order(account_id,started_at DESC,id DESC);
CREATE TABLE meter_sample (
 order_id bigint NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id), sampled_at datetime(6) NOT NULL,
 reading numeric(14,4) NOT NULL CHECK(reading>=0), PRIMARY KEY(order_id,sampled_at)
) ENGINE=InnoDB;
CREATE TABLE fee_detail (
 order_id bigint NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id), begins datetime(6) NOT NULL, ends datetime(6) NOT NULL,
 label varchar(255) NOT NULL, kwh numeric(12,4) NOT NULL CHECK(kwh>=0), energy_rate numeric(8,4) NOT NULL,
 service_rate numeric(8,4) NOT NULL, energy numeric(12,2) NOT NULL, service numeric(12,2) NOT NULL,
 estimated boolean NOT NULL, PRIMARY KEY(order_id,begins), CHECK(ends>begins)
) ENGINE=InnoDB;
CREATE TABLE order_review (
 order_id bigint PRIMARY KEY, FOREIGN KEY (order_id) REFERENCES charge_order(id), reason varchar(255) NOT NULL, last_reading numeric(14,4) NOT NULL,
 adjustment numeric(12,2), reviewed_by bigint, FOREIGN KEY (reviewed_by) REFERENCES account(id), reviewed_at datetime(6), conclusion varchar(255)
) ENGINE=InnoDB;
CREATE TABLE payment (
 id bigint AUTO_INCREMENT PRIMARY KEY, order_id bigint NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id),
 channel varchar(255) NOT NULL CHECK(channel IN ('mock','wallet')), reference varchar(255) NOT NULL,
 amount numeric(12,2) NOT NULL CHECK(amount>0), succeeded boolean NOT NULL,
 happened_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), UNIQUE(channel,reference)
) ENGINE=InnoDB;
CREATE INDEX payment_order ON payment(order_id);
CREATE TABLE refund (
 id bigint AUTO_INCREMENT PRIMARY KEY, payment_id bigint NOT NULL, FOREIGN KEY (payment_id) REFERENCES payment(id),
 reference varchar(255) NOT NULL UNIQUE, amount numeric(12,2) NOT NULL CHECK(amount>0),
 kind varchar(32) NOT NULL DEFAULT 'price_adjustment' CHECK(kind IN ('price_adjustment','payment_reversal')),
 debt_reduction numeric(12,2) NOT NULL DEFAULT 0,
 happened_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 CHECK(debt_reduction>=0 AND debt_reduction<=amount),
 CHECK((kind='price_adjustment' AND debt_reduction=amount) OR (kind='payment_reversal' AND debt_reduction=0))
) ENGINE=InnoDB;

ALTER TABLE charge_order ADD active_gun bigint GENERATED ALWAYS AS (CASE WHEN state IN ('starting','charging','finishing') THEN connector_id END) STORED UNIQUE;
DELIMITER $$
-- Holds are changed only by order transitions. Callers must share one transaction.
CREATE PROCEDURE check_order_reservation(IN p_id bigint,IN p_account bigint,IN p_card bigint,
 IN p_old_wallet decimal(12,2),IN p_wallet decimal(12,2),IN p_old_fleet decimal(12,2),IN p_fleet decimal(12,2),
 IN p_period date,IN p_state varchar(20),IN p_gross decimal(12,2),IN p_discount decimal(12,2))
BEGIN
 DECLARE funds decimal(12,2); DECLARE reserved decimal(12,2); DECLARE used_credit decimal(18,2);
 DECLARE new_credit decimal(18,2) DEFAULT 0; DECLARE reduction decimal(12,2) DEFAULT 0;
 IF p_card IS NULL THEN
  SELECT balance,reserved_balance INTO funds,reserved FROM account WHERE id=p_account FOR UPDATE;
  IF funds IS NULL OR p_wallet>funds-reserved+p_old_wallet THEN
   SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='insufficient available wallet balance for authorization'; END IF;
 ELSE
  SELECT credit_limit,reserved_amount INTO funds,reserved FROM fleet_card
   WHERE id=p_card AND driver_id=p_account FOR UPDATE;
  IF funds IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet card owner mismatch'; END IF;
  SELECT COALESCE(SUM(GREATEST(0,o.gross-o.discount-COALESCE(r.reduction,0))),0) INTO used_credit
   FROM charge_order o LEFT JOIN
   (SELECT p.order_id,SUM(r.debt_reduction) reduction FROM refund r JOIN payment p ON p.id=r.payment_id GROUP BY p.order_id) r ON r.order_id=o.id
   WHERE o.fleet_card_id=p_card AND o.budget_period=p_period AND o.id<>p_id AND o.state IN ('billed','paid');
  SELECT COALESCE(SUM(r.debt_reduction),0) INTO reduction FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=p_id;
  IF p_state IN ('billed','paid') THEN SET new_credit=GREATEST(0,p_gross-p_discount-reduction); END IF;
  IF used_credit+new_credit+reserved-p_old_fleet+p_fleet>funds THEN
   SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet monthly credit including reservations exceeded'; END IF;
 END IF;
END$$
-- Called by service routines BEFORE their order INSERT/UPDATE, never by a trigger.
-- MySQL forbids locking the trigger's own source table (1442).
CREATE PROCEDURE check_fleet_credit_current(IN p_card bigint,IN p_order bigint,IN p_period date,
 IN p_old_hold decimal(12,2),IN p_new_hold decimal(12,2),IN p_new_amount decimal(12,2))
BEGIN
 DECLARE ceiling_fee decimal(12,2); DECLARE reserved_fee decimal(12,2);
 DECLARE used_fee decimal(18,2); DECLARE reduced_fee decimal(18,2); DECLARE own_reduction decimal(18,2);
 SELECT credit_limit,reserved_amount INTO ceiling_fee,reserved_fee FROM fleet_card WHERE id=p_card FOR UPDATE;
 IF ceiling_fee IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet card not found'; END IF;
 SELECT COALESCE(SUM(gross-discount),0) INTO used_fee FROM charge_order
  WHERE fleet_card_id=p_card AND budget_period=p_period AND id<>p_order AND state IN ('billed','paid') FOR UPDATE;
 SELECT COALESCE(SUM(r.debt_reduction),0) INTO reduced_fee FROM refund r JOIN payment p ON p.id=r.payment_id
  JOIN charge_order o ON o.id=p.order_id WHERE o.fleet_card_id=p_card AND o.budget_period=p_period
  AND o.id<>p_order AND o.state IN ('billed','paid') FOR UPDATE;
 SELECT COALESCE(SUM(r.debt_reduction),0) INTO own_reduction FROM refund r JOIN payment p ON p.id=r.payment_id
  WHERE p.order_id=p_order FOR UPDATE;
 IF used_fee-reduced_fee+GREATEST(0,p_new_amount-own_reduction)+reserved_fee-p_old_hold+p_new_hold>ceiling_fee THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet monthly credit current usage and reservations exceeded'; END IF;
END$$
CREATE TRIGGER order_funding_insert BEFORE INSERT ON charge_order FOR EACH ROW
BEGIN
 DECLARE station_key bigint; DECLARE operator_key bigint;
 SELECT c.station_id,s.operator_id INTO station_key,operator_key FROM connector g
  JOIN charger c ON c.id=g.charger_id JOIN station s ON s.id=c.station_id WHERE g.id=NEW.connector_id;
 SET NEW.station_id=station_key,NEW.operator_id=operator_key,
  NEW.budget_period=CAST(DATE_FORMAT(NEW.started_at,'%Y-%m-01') AS DATE);
 IF NEW.authorized_amount>0 AND NEW.state IN ('starting','charging','finishing','review') THEN
  SET NEW.wallet_hold=IF(NEW.fleet_card_id IS NULL,NEW.authorized_amount,0),
   NEW.fleet_hold=IF(NEW.fleet_card_id IS NOT NULL,NEW.authorized_amount,0);
 END IF;
 CALL check_order_reservation(NEW.id,NEW.account_id,NEW.fleet_card_id,0,NEW.wallet_hold,0,NEW.fleet_hold,
  NEW.budget_period,NEW.state,NEW.gross,NEW.discount);
END$$
CREATE TRIGGER order_reserve_insert AFTER INSERT ON charge_order FOR EACH ROW
BEGIN
 IF NEW.wallet_hold<>0 THEN UPDATE account SET reserved_balance=reserved_balance+NEW.wallet_hold WHERE id=NEW.account_id; END IF;
 IF NEW.fleet_hold<>0 THEN UPDATE fleet_card SET reserved_amount=reserved_amount+NEW.fleet_hold WHERE id=NEW.fleet_card_id; END IF;
END$$
CREATE TRIGGER order_funding_update BEFORE UPDATE ON charge_order FOR EACH ROW
BEGIN
 IF NEW.account_id<>OLD.account_id OR NEW.connector_id<>OLD.connector_id OR NEW.vehicle_id<>OLD.vehicle_id
  OR NEW.station_id<>OLD.station_id OR NEW.operator_id<>OLD.operator_id OR NEW.tariff_id<>OLD.tariff_id
  OR NOT(NEW.fleet_card_id<=>OLD.fleet_card_id) OR NEW.started_at<>OLD.started_at OR NEW.budget_period<>OLD.budget_period THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='historical order identity and ownership are immutable'; END IF;
 IF NEW.authorized_amount<OLD.authorized_amount THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='authorization cannot be reduced'; END IF;
 IF NEW.state IN ('paid','cancelled') THEN SET NEW.wallet_hold=0,NEW.fleet_hold=0; END IF;
 IF NEW.authorized_amount>0 AND NEW.state IN ('billed','paid') AND NEW.gross-NEW.discount>NEW.authorized_amount THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='additional authorization required before billing'; END IF;
 CALL check_order_reservation(OLD.id,NEW.account_id,NEW.fleet_card_id,OLD.wallet_hold,NEW.wallet_hold,OLD.fleet_hold,NEW.fleet_hold,
  NEW.budget_period,NEW.state,NEW.gross,NEW.discount);
END$$
CREATE TRIGGER order_reserve_update AFTER UPDATE ON charge_order FOR EACH ROW
BEGIN
 IF NEW.wallet_hold<>OLD.wallet_hold THEN UPDATE account SET reserved_balance=reserved_balance+NEW.wallet_hold-OLD.wallet_hold WHERE id=NEW.account_id; END IF;
 IF NEW.fleet_hold<>OLD.fleet_hold THEN UPDATE fleet_card SET reserved_amount=reserved_amount+NEW.fleet_hold-OLD.fleet_hold WHERE id=NEW.fleet_card_id; END IF;
END$$
CREATE TRIGGER order_reserve_delete BEFORE DELETE ON charge_order FOR EACH ROW
BEGIN
 IF OLD.wallet_hold<>0 OR OLD.fleet_hold<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='cancel order to release authorization before deletion'; END IF;
END$$
CREATE PROCEDURE validate_tariff(IN p_id bigint,IN p_station bigint,IN p_fleet bigint,IN p_start datetime(6),IN p_end datetime(6))
BEGIN
 DECLARE locked bigint;
 SELECT id INTO locked FROM station WHERE id=p_station FOR UPDATE;
 IF EXISTS(SELECT 1 FROM tariff t WHERE t.id<>p_id AND t.station_id=p_station AND t.fleet_id<=>p_fleet
 AND t.starts<p_end AND p_start<t.ends) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='tariff overlap'; END IF;
END$$
CREATE TRIGGER tariff_insert BEFORE INSERT ON tariff FOR EACH ROW
BEGIN CALL validate_tariff(0,NEW.station_id,NEW.fleet_id,NEW.starts,NEW.ends); END$$
CREATE TRIGGER tariff_update BEFORE UPDATE ON tariff FOR EACH ROW
BEGIN
 IF EXISTS(SELECT 1 FROM charge_order WHERE tariff_id=OLD.id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='used tariff is immutable'; END IF;
 CALL validate_tariff(OLD.id,NEW.station_id,NEW.fleet_id,NEW.starts,NEW.ends);
END$$
CREATE PROCEDURE validate_band(IN p_id bigint,IN p_old bigint,IN p_min int,IN p_a int,IN p_z int)
BEGIN
 DECLARE locked bigint;
 SELECT id INTO locked FROM tariff WHERE id=p_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM charge_order WHERE tariff_id=p_id OR tariff_id=p_old) OR
 EXISTS(SELECT 1 FROM tariff_band b WHERE b.tariff_id=p_id AND NOT (b.tariff_id=p_old AND b.minute_from=p_min)
 AND b.minute_from<p_z AND p_a<b.minute_to) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='band overlap or used tariff'; END IF;
END$$
CREATE TRIGGER band_insert BEFORE INSERT ON tariff_band FOR EACH ROW
BEGIN CALL validate_band(NEW.tariff_id,0,-1,NEW.minute_from,NEW.minute_to); END$$
CREATE TRIGGER band_update BEFORE UPDATE ON tariff_band FOR EACH ROW
BEGIN CALL validate_band(NEW.tariff_id,OLD.tariff_id,OLD.minute_from,NEW.minute_from,NEW.minute_to); END$$
CREATE TRIGGER band_delete BEFORE DELETE ON tariff_band FOR EACH ROW
BEGIN CALL validate_band(OLD.tariff_id,OLD.tariff_id,OLD.minute_from,0,0); END$$
CREATE FUNCTION meter_at(p_order bigint,p_at datetime(6)) RETURNS decimal(14,4) READS SQL DATA
BEGIN
 DECLARE a datetime(6); DECLARE z datetime(6); DECLARE x decimal(14,4); DECLARE y decimal(14,4);
 SELECT sampled_at,reading INTO a,x FROM meter_sample WHERE order_id=p_order AND sampled_at<=p_at ORDER BY sampled_at DESC LIMIT 1;
 SELECT sampled_at,reading INTO z,y FROM meter_sample WHERE order_id=p_order AND sampled_at>=p_at ORDER BY sampled_at LIMIT 1;
 RETURN IF(a=z,x,ROUND(x+(y-x)*TIMESTAMPDIFF(MICROSECOND,a,p_at)/NULLIF(TIMESTAMPDIFF(MICROSECOND,a,z),0),4));
END$$
-- Read-only quotation over actual cumulative samples. Raw samples are never discarded.
CREATE FUNCTION order_cost_until(p_order bigint,p_end datetime(6)) RETURNS decimal(12,2) READS SQL DATA
BEGIN
 DECLARE a datetime(6); DECLARE started datetime(6); DECLARE z datetime(6); DECLARE tariff_key bigint;
 DECLARE boundary int; DECLARE m int; DECLARE free_time int; DECLARE mode varchar(10);
 DECLARE er decimal(8,4); DECLARE sr decimal(8,4); DECLARE floor_fee decimal(12,2);
 DECLARE units decimal(14,4); DECLARE total decimal(18,2) DEFAULT 0;
 SELECT started_at,tariff_id INTO started,tariff_key FROM charge_order WHERE id=p_order;
 IF started IS NULL OR p_end<started OR meter_at(p_order,started) IS NULL OR meter_at(p_order,p_end) IS NULL THEN RETURN NULL; END IF;
 SELECT service_mode,free_minutes,minimum INTO mode,free_time,floor_fee FROM tariff WHERE id=tariff_key;
 SET a=started;
 WHILE a<p_end DO
  SET m=HOUR(a)*60+MINUTE(a),boundary=NULL;
  SELECT minute_to,energy_rate,service_rate INTO boundary,er,sr FROM tariff_band
   WHERE tariff_id=tariff_key AND minute_from<=m AND m<minute_to;
  IF boundary IS NULL THEN RETURN NULL; END IF;
  SET z=LEAST(p_end,TIMESTAMPADD(MINUTE,boundary,DATE(a))),units=meter_at(p_order,z)-meter_at(p_order,a);
  IF units<0 THEN RETURN NULL; END IF;
  SET total=total+ROUND(units*er,2)+ROUND(sr*IF(mode='kwh',units,
   GREATEST(0,TIMESTAMPDIFF(MICROSECOND,GREATEST(a,TIMESTAMPADD(MINUTE,free_time,started)),z))/3600000000),2),a=z;
 END WHILE;
 RETURN GREATEST(total,floor_fee);
END$$
CREATE PROCEDURE inspect_charge_budget(IN p_order bigint)
BEGIN
 DECLARE budget decimal(12,2); DECLARE sample_end datetime(6); DECLARE actual decimal(12,2);
 SELECT authorized_amount INTO budget FROM charge_order WHERE id=p_order AND state IN ('starting','charging','finishing') FOR UPDATE;
 IF budget>0 THEN
  SELECT MAX(sampled_at) INTO sample_end FROM meter_sample WHERE order_id=p_order;
  SET actual=order_cost_until(p_order,sample_end);
  IF actual>budget THEN UPDATE charge_order SET budget_exceeded=true,stop_requested_at=COALESCE(stop_requested_at,SYSDATE(6)) WHERE id=p_order; END IF;
 END IF;
END$$
CREATE PROCEDURE authorize_more(IN p_order bigint,IN p_total_budget decimal(12,2))
BEGIN
 DECLARE prior decimal(12,2); DECLARE card bigint; DECLARE o_state varchar(20); DECLARE old_hold decimal(12,2); DECLARE period_key date;
 SELECT authorized_amount,fleet_card_id,state,fleet_hold,budget_period INTO prior,card,o_state,old_hold,period_key FROM charge_order WHERE id=p_order FOR UPDATE;
 IF prior IS NULL OR prior=0 OR p_total_budget<=prior OR o_state NOT IN ('starting','charging','finishing','review') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='larger authorization for an active or reviewed order required'; END IF;
 IF card IS NOT NULL THEN CALL check_fleet_credit_current(card,p_order,period_key,old_hold,p_total_budget,0); END IF;
 UPDATE charge_order SET authorized_amount=p_total_budget,
  wallet_hold=IF(card IS NULL,p_total_budget,0),fleet_hold=IF(card IS NOT NULL,p_total_budget,0) WHERE id=p_order;
END$$
CREATE FUNCTION estimate_charge(p_tariff bigint,p_at datetime(6),p_kwh decimal(14,4),p_kw decimal(14,4)) RETURNS decimal(12,2) READS SQL DATA
BEGIN
 DECLARE a datetime(6); DECLARE z datetime(6); DECLARE cutoff datetime(6);
 DECLARE boundary int; DECLARE m int; DECLARE free_time int; DECLARE mode varchar(10);
 DECLARE er decimal(8,4); DECLARE sr decimal(8,4); DECLARE minimum_fee decimal(12,2);
 DECLARE seconds_total decimal(20,6); DECLARE seconds_part decimal(20,6); DECLARE total decimal(18,4) DEFAULT 0;
 IF p_kwh<=0 OR p_kw<=0 THEN RETURN NULL; END IF;
 SELECT service_mode,free_minutes,minimum INTO mode,free_time,minimum_fee FROM tariff WHERE id=p_tariff;
 SET cutoff=TIMESTAMPADD(MICROSECOND,ROUND(p_kwh/p_kw*3600000000),p_at);
 SET seconds_total=TIMESTAMPDIFF(MICROSECOND,p_at,cutoff)/1000000;
 SET a=p_at;
 WHILE a<cutoff DO
  SET m=HOUR(a)*60+MINUTE(a),boundary=NULL;
  SELECT minute_to,energy_rate,service_rate INTO boundary,er,sr FROM tariff_band WHERE tariff_id=p_tariff AND minute_from<=m AND m<minute_to;
  IF boundary IS NULL THEN RETURN NULL; END IF;
  SET z=LEAST(cutoff,TIMESTAMPADD(MINUTE,boundary,DATE(a)));
  SET seconds_part=TIMESTAMPDIFF(MICROSECOND,a,z)/1000000;
  SET total=total+er*p_kwh*seconds_part/seconds_total+sr*IF(mode='kwh',p_kwh*seconds_part/seconds_total,
    GREATEST(0,TIMESTAMPDIFF(MICROSECOND,GREATEST(a,TIMESTAMPADD(MINUTE,free_time,p_at)),z))/3600000000);
  SET a=z;
 END WHILE;
 RETURN GREATEST(ROUND(total,2),minimum_fee);
END$$
CREATE PROCEDURE finish_charge(IN p_order bigint,IN p_end datetime(6),IN p_disconnect boolean)
BEGIN
 DECLARE gun bigint; DECLARE tariff_key bigint; DECLARE o_state varchar(20);
 DECLARE started datetime(6); DECLARE a datetime(6); DECLARE z datetime(6); DECLARE cutoff datetime(6);
 DECLARE boundary int; DECLARE m int; DECLARE free_time int; DECLARE band varchar(20); DECLARE mode varchar(10);
 DECLARE er decimal(8,4); DECLARE sr decimal(8,4); DECLARE minimum_fee decimal(12,2);
 DECLARE units decimal(14,4); DECLARE total decimal(12,2); DECLARE budget decimal(12,2); DECLARE card bigint;
 DECLARE old_hold decimal(12,2); DECLARE period_key date;
 DECLARE over_budget boolean DEFAULT false; DECLARE estimated boolean; DECLARE approx boolean DEFAULT false;
 SELECT connector_id INTO gun FROM charge_order WHERE id=p_order;
 SELECT id INTO gun FROM connector WHERE id=gun FOR UPDATE;
 SELECT state,started_at,tariff_id,authorized_amount,fleet_card_id,fleet_hold,budget_period
  INTO o_state,started,tariff_key,budget,card,old_hold,period_key FROM charge_order WHERE id=p_order FOR UPDATE;
 SET cutoff=IF(p_disconnect,(SELECT MAX(sampled_at) FROM meter_sample WHERE order_id=p_order AND sampled_at<=p_end),p_end);
 IF o_state IS NULL OR o_state NOT IN ('charging','finishing') OR cutoff IS NULL OR cutoff<=started OR
 meter_at(p_order,started) IS NULL OR meter_at(p_order,cutoff) IS NULL THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid charge or missing readings'; END IF;
 IF EXISTS(SELECT 1 FROM (SELECT reading,LAG(reading) OVER(ORDER BY sampled_at) AS previous_reading
 FROM meter_sample WHERE order_id=p_order AND sampled_at BETWEEN started AND cutoff) readings WHERE reading<previous_reading) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='meter regressed'; END IF;
 SELECT service_mode,free_minutes,minimum INTO mode,free_time,minimum_fee FROM tariff WHERE id=tariff_key;
 SET a=started;
 WHILE a<cutoff DO
  SET m=HOUR(a)*60+MINUTE(a),boundary=NULL;
  SELECT minute_to,label,energy_rate,service_rate INTO boundary,band,er,sr FROM tariff_band
    WHERE tariff_id=tariff_key AND minute_from<=m AND m<minute_to;
  IF boundary IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='tariff has gaps'; END IF;
  SET z=LEAST(cutoff,TIMESTAMPADD(MINUTE,boundary,DATE(a))),units=meter_at(p_order,z)-meter_at(p_order,a);
  SET estimated=NOT EXISTS(SELECT 1 FROM meter_sample WHERE order_id=p_order AND sampled_at=a)
     OR NOT EXISTS(SELECT 1 FROM meter_sample WHERE order_id=p_order AND sampled_at=z);
  INSERT INTO fee_detail VALUES(p_order,a,z,band,units,er,sr,ROUND(units*er,2),ROUND(sr*IF(mode='kwh',units,
    GREATEST(0,TIMESTAMPDIFF(MICROSECOND,GREATEST(a,TIMESTAMPADD(MINUTE,free_time,started)),z))/3600000000),2),estimated);
  SET approx=approx OR estimated,a=z;
 END WHILE;
 SELECT SUM(energy+service),SUM(kwh) INTO total,units FROM fee_detail WHERE order_id=p_order;
 SET total=GREATEST(total,minimum_fee),over_budget=(budget>0 AND total>budget);
 IF card IS NOT NULL THEN CALL check_fleet_credit_current(card,p_order,period_key,old_hold,
  IF(approx OR p_disconnect OR over_budget,budget,0),IF(approx OR p_disconnect OR over_budget,0,total)); END IF;
 UPDATE charge_order SET ended_at=cutoff,kwh=units,gross=total,
  budget_exceeded=budget_exceeded OR over_budget,
  stop_requested_at=IF(over_budget,COALESCE(stop_requested_at,SYSDATE(6)),stop_requested_at),
  wallet_hold=IF(card IS NULL AND budget>0,LEAST(total,budget),0),
  fleet_hold=IF(card IS NOT NULL AND (approx OR p_disconnect OR over_budget),budget,0),
  state=IF(approx OR p_disconnect OR over_budget,'review',IF(total=0,'paid','billed')) WHERE id=p_order;
 IF approx OR p_disconnect OR over_budget THEN INSERT INTO order_review(order_id,reason,last_reading)
 VALUES(p_order,IF(over_budget,'authorization_exceeded',IF(p_disconnect,'disconnect','interpolation')),meter_at(p_order,cutoff)); END IF;
 UPDATE connector SET state='idle' WHERE id=gun AND state='occupied';
END$$
DELIMITER ;
