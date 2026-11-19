CREATE TABLE tariff (
 id bigint AUTO_INCREMENT PRIMARY KEY, station_id bigint NOT NULL, FOREIGN KEY (station_id) REFERENCES station(id), fleet_id bigint, FOREIGN KEY (fleet_id) REFERENCES fleet(id),
 starts datetime(6) NOT NULL, ends datetime(6) NOT NULL CHECK(ends>starts),
 service_mode varchar(255) NOT NULL CHECK(service_mode IN ('kwh','hour')),
 free_minutes integer NOT NULL DEFAULT 0 CHECK(free_minutes>=0), minimum numeric(12,2) NOT NULL DEFAULT 0 CHECK(minimum>=0)
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
 started_at datetime(6) NOT NULL, ended_at datetime(6), start_soc numeric(5,2), end_soc numeric(5,2),
 state varchar(255) NOT NULL CHECK(state IN ('starting','charging','finishing','review','billed','paid','cancelled')),
 kwh numeric(12,4) CHECK(kwh>=0), gross numeric(12,2) CHECK(gross>=0), discount numeric(12,2) NOT NULL DEFAULT 0,
 CHECK(ended_at IS NULL OR ended_at>started_at), CHECK(start_soc BETWEEN 0 AND 100), CHECK(end_soc BETWEEN 0 AND 100),
 CHECK(discount>=0 AND (gross IS NULL OR discount<=gross))
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
 reference varchar(255) NOT NULL UNIQUE, amount numeric(12,2) NOT NULL CHECK(amount>0), happened_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

ALTER TABLE charge_order ADD active_gun bigint GENERATED ALWAYS AS (CASE WHEN state IN ('starting','charging','finishing') THEN connector_id END) STORED UNIQUE;
DELIMITER $$
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
 DECLARE units decimal(14,4); DECLARE total decimal(12,2); DECLARE estimated boolean; DECLARE approx boolean DEFAULT false;
 SELECT connector_id INTO gun FROM charge_order WHERE id=p_order;
 SELECT id INTO gun FROM connector WHERE id=gun FOR UPDATE;
 SELECT state,started_at,tariff_id INTO o_state,started,tariff_key FROM charge_order WHERE id=p_order FOR UPDATE;
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
 UPDATE charge_order SET ended_at=cutoff,kwh=units,gross=GREATEST(total,minimum_fee),
 state=IF(approx OR p_disconnect,'review','billed') WHERE id=p_order;
 IF approx OR p_disconnect THEN INSERT INTO order_review(order_id,reason,last_reading)
 VALUES(p_order,IF(p_disconnect,'disconnect','interpolation'),meter_at(p_order,cutoff)); END IF;
 UPDATE connector SET state='idle' WHERE id=gun AND state='occupied';
END$$
DELIMITER ;
