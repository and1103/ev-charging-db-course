CREATE TABLE telemetry (
 charger_id bigint NOT NULL, sampled_at datetime(6) NOT NULL,
 volts decimal(18,4), amps decimal(18,4), kw decimal(18,4), temperature decimal(18,4), offline_seconds integer CHECK(offline_seconds>=0),
 fault_code varchar(255), PRIMARY KEY(charger_id,sampled_at)
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS(sampled_at) SUBPARTITION BY HASH(charger_id) SUBPARTITIONS 2
(PARTITION p_before VALUES LESS THAN ('2026-11-01'), PARTITION p_demo VALUES LESS THAN ('2026-12-01'), PARTITION p_future VALUES LESS THAN (MAXVALUE));
CREATE TABLE alarm_rule (
 code varchar(255) PRIMARY KEY, severity integer NOT NULL CHECK(severity BETWEEN 1 AND 5),
 response_minutes integer NOT NULL CHECK(response_minutes>0)
) ENGINE=InnoDB;
CREATE TABLE alarm (
 id bigint AUTO_INCREMENT PRIMARY KEY, charger_id bigint NOT NULL, FOREIGN KEY (charger_id) REFERENCES charger(id),
 connector_id bigint, CONSTRAINT alarm_connector_fk FOREIGN KEY (connector_id) REFERENCES connector(id),
 code varchar(255) NOT NULL, FOREIGN KEY (code) REFERENCES alarm_rule(code), severity integer NOT NULL CHECK(severity BETWEEN 1 AND 5),
 opened_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), deadline datetime(6) NOT NULL, escalated_at datetime(6), restored_at datetime(6)
) ENGINE=InnoDB;
CREATE TABLE work_order (
 id bigint AUTO_INCREMENT PRIMARY KEY, alarm_id bigint NOT NULL, FOREIGN KEY (alarm_id) REFERENCES alarm(id),
 technician_id bigint NOT NULL, FOREIGN KEY (technician_id) REFERENCES account(id), assigned_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 accepted_at datetime(6), arrived_at datetime(6), repaired_at datetime(6), closed_at datetime(6), result varchar(255),
 CHECK(accepted_at IS NULL OR accepted_at>=assigned_at),
 CHECK(arrived_at IS NULL OR (accepted_at IS NOT NULL AND arrived_at>=accepted_at)),
 CHECK(repaired_at IS NULL OR (arrived_at IS NOT NULL AND repaired_at>=arrived_at)),
 CHECK(closed_at IS NULL OR (repaired_at IS NOT NULL AND closed_at>=repaired_at AND result IS NOT NULL))
) ENGINE=InnoDB;
CREATE INDEX work_alarm ON work_order(alarm_id);
CREATE TABLE work_part (work_id bigint, FOREIGN KEY (work_id) REFERENCES work_order(id), part varchar(255), quantity integer NOT NULL CHECK(quantity>0), PRIMARY KEY(work_id,part)) ENGINE=InnoDB;
CREATE TABLE alarm_notice (alarm_id bigint, FOREIGN KEY (alarm_id) REFERENCES alarm(id), kind varchar(255), created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(alarm_id,kind)) ENGINE=InnoDB;

ALTER TABLE alarm ADD live_charger bigint GENERATED ALWAYS AS (CASE WHEN restored_at IS NULL THEN charger_id END) STORED,
 ADD scope_connector bigint GENERATED ALWAYS AS (COALESCE(connector_id,0)) STORED,
 ADD CONSTRAINT alarm_positive_connector CHECK(connector_id IS NULL OR connector_id>0),
 ADD UNIQUE KEY one_live_alarm(live_charger,scope_connector,code), ADD KEY alarm_deadline(restored_at,escalated_at,deadline);
DELIMITER $$
-- NULL connector_id means a charger-wide alarm or an unspecified source gun.
-- Affected guns may be derived separately; they are not the source connector_id.
CREATE TRIGGER alarm_connector_insert BEFORE INSERT ON alarm FOR EACH ROW
BEGIN
 IF NEW.connector_id IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM connector WHERE id=NEW.connector_id AND charger_id=NEW.charger_id)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='alarm connector must belong to charger'; END IF;
END$$
CREATE TRIGGER alarm_connector_update BEFORE UPDATE ON alarm FOR EACH ROW
BEGIN
 IF NEW.connector_id IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM connector WHERE id=NEW.connector_id AND charger_id=NEW.charger_id)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='alarm connector must belong to charger'; END IF;
END$$
CREATE TRIGGER telemetry_charger BEFORE INSERT ON telemetry FOR EACH ROW
BEGIN
 IF NOT EXISTS(SELECT 1 FROM charger WHERE id=NEW.charger_id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='unknown charger'; END IF;
END$$
CREATE TRIGGER telemetry_charger_update BEFORE UPDATE ON telemetry FOR EACH ROW
BEGIN
 IF NOT EXISTS(SELECT 1 FROM charger WHERE id=NEW.charger_id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='unknown charger'; END IF;
END$$
CREATE TRIGGER charger_telemetry_delete BEFORE DELETE ON charger FOR EACH ROW
BEGIN
 IF EXISTS(SELECT 1 FROM telemetry WHERE charger_id=OLD.id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='charger has telemetry'; END IF;
END$$
CREATE TRIGGER work_flow BEFORE UPDATE ON work_order FOR EACH ROW
BEGIN
 IF OLD.closed_at IS NOT NULL OR NEW.alarm_id<>OLD.alarm_id
 OR (OLD.accepted_at IS NOT NULL AND NOT (NEW.accepted_at<=>OLD.accepted_at))
 OR (OLD.arrived_at IS NOT NULL AND NOT (NEW.arrived_at<=>OLD.arrived_at))
 OR (OLD.repaired_at IS NOT NULL AND NOT (NEW.repaired_at<=>OLD.repaired_at))
 OR ((NEW.accepted_at IS NOT NULL)+(NEW.arrived_at IS NOT NULL)+(NEW.repaired_at IS NOT NULL)+(NEW.closed_at IS NOT NULL))
 -((OLD.accepted_at IS NOT NULL)+(OLD.arrived_at IS NOT NULL)+(OLD.repaired_at IS NOT NULL))>1
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid work flow'; END IF;
END$$
CREATE TRIGGER work_assign BEFORE INSERT ON work_order FOR EACH ROW
BEGIN
 DECLARE key_id bigint;
 SELECT id INTO key_id FROM alarm WHERE id=NEW.alarm_id AND restored_at IS NULL FOR UPDATE;
 IF key_id IS NULL OR NEW.accepted_at IS NOT NULL OR NEW.arrived_at IS NOT NULL OR NEW.repaired_at IS NOT NULL OR NEW.closed_at IS NOT NULL
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='active alarm and pending assignment required'; END IF;
END$$
CREATE FUNCTION raise_alarm_scope(p_charger bigint,p_connector bigint,p_code varchar(255)) RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE k bigint;
 INSERT INTO alarm(charger_id,connector_id,code,severity,deadline)
 SELECT p_charger,p_connector,code,severity,TIMESTAMPADD(MINUTE,response_minutes,NOW()) FROM alarm_rule WHERE code=p_code
 ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id);
 IF NOT EXISTS(SELECT 1 FROM alarm_rule WHERE code=p_code) THEN RETURN NULL; END IF;
 SET k=(SELECT id FROM alarm WHERE live_charger=p_charger AND scope_connector=COALESCE(p_connector,0) AND code=p_code);
 INSERT INTO alarm_notice(alarm_id,kind) VALUES(k,'opened') ON DUPLICATE KEY UPDATE kind='opened';
 RETURN k;
END$$
CREATE FUNCTION raise_alarm(p_charger bigint,p_code varchar(255)) RETURNS bigint MODIFIES SQL DATA
BEGIN
 RETURN raise_alarm_scope(p_charger,NULL,p_code);
END$$
CREATE PROCEDURE escalate_alarms(IN p_now datetime(6))
BEGIN
 UPDATE alarm a SET severity=LEAST(5,a.severity+1),escalated_at=p_now
 WHERE a.restored_at IS NULL AND a.escalated_at IS NULL AND a.deadline<=p_now AND NOT EXISTS
 (SELECT 1 FROM work_order w WHERE w.alarm_id=a.id AND w.accepted_at IS NOT NULL);
 INSERT INTO alarm_notice(alarm_id,kind)
 SELECT id,'escalated' FROM alarm WHERE escalated_at IS NOT NULL ON DUPLICATE KEY UPDATE kind='escalated';
END$$
CREATE PROCEDURE process_charger(IN p_charger bigint,IN p_state varchar(20))
BEGIN
 DECLARE done boolean DEFAULT false; DECLARE g bigint; DECLARE o bigint; DECLARE start_time datetime(6);
 DECLARE last_sample datetime(6); DECLARE result bigint;
 DECLARE guns CURSOR FOR SELECT id FROM connector WHERE charger_id=p_charger ORDER BY id;
 DECLARE CONTINUE HANDLER FOR NOT FOUND SET done=true;
 IF p_state NOT IN ('idle','offline','fault') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid device state'; END IF;
 UPDATE charger SET state=p_state,heartbeat=IF(p_state='offline',heartbeat,SYSDATE(6)) WHERE id=p_charger;
 OPEN guns;
 scan: LOOP
  FETCH guns INTO g;
  IF done THEN LEAVE scan; END IF;
  UPDATE connector SET state=IF(p_state='idle' AND EXISTS(SELECT 1 FROM charge_order WHERE active_gun=g),'occupied',p_state) WHERE id=g;
  IF p_state<>'idle' THEN
   SET o=(SELECT id FROM charge_order WHERE active_gun=g);
   IF o IS NOT NULL THEN
    SET start_time=(SELECT started_at FROM charge_order WHERE id=o);
    SET last_sample=(SELECT MAX(sampled_at) FROM meter_sample WHERE order_id=o);
    IF last_sample>start_time THEN CALL finish_charge(o,last_sample,true);
    ELSE UPDATE charge_order SET state='cancelled' WHERE id=o; END IF;
   END IF;
  END IF;
  SET result=assign_gun(g);
 END LOOP;
 CLOSE guns;
 IF p_state='offline' THEN
  INSERT INTO asset_request(charger_id,kind) VALUES(p_charger,'offline') ON DUPLICATE KEY UPDATE state='pending';
  SET result=raise_alarm(p_charger,'OFFLINE');
 ELSEIF p_state='fault' THEN SET result=raise_alarm(p_charger,'FAULT');
 ELSE UPDATE asset_request SET state='approved' WHERE charger_id=p_charger AND kind='offline' AND state='pending'; END IF;
END$$
CREATE PROCEDURE scan_offline()
BEGIN
 DECLARE done boolean DEFAULT false; DECLARE c bigint;
 DECLARE devices CURSOR FOR SELECT id FROM charger WHERE commissioned_on IS NOT NULL AND state<>'offline'
 AND (heartbeat IS NULL OR heartbeat<SYSDATE(6)-INTERVAL 3 MINUTE) ORDER BY id FOR UPDATE;
 DECLARE CONTINUE HANDLER FOR NOT FOUND SET done=true;
 OPEN devices;
 scan: LOOP
  FETCH devices INTO c;
  IF done THEN LEAVE scan; END IF;
  CALL process_charger(c,'offline');
 END LOOP;
 CLOSE devices;
END$$
CREATE PROCEDURE recover_alarm(IN p_alarm bigint)
BEGIN
 DECLARE c bigint; DECLARE gun bigint; DECLARE opened datetime(6); DECLARE repaired datetime(6);
 DECLARE samples int; DECLARE normal_count int; DECLARE first_at datetime(6); DECLARE last_at datetime(6);
 SELECT charger_id,connector_id,opened_at INTO c,gun,opened FROM alarm WHERE id=p_alarm AND restored_at IS NULL FOR UPDATE;
 SELECT MAX(repaired_at) INTO repaired FROM work_order WHERE alarm_id=p_alarm;
 SELECT COUNT(*),COALESCE(SUM(fault_code IS NULL AND COALESCE(offline_seconds,0)=0),0),MIN(sampled_at),MAX(sampled_at)
 INTO samples,normal_count,first_at,last_at FROM
 (SELECT sampled_at,fault_code,offline_seconds FROM telemetry WHERE charger_id=c AND sampled_at>GREATEST(opened,repaired)
 AND sampled_at<=SYSDATE(6) ORDER BY sampled_at DESC LIMIT 3) t;
 IF c IS NULL OR NOT EXISTS(SELECT 1 FROM work_order WHERE alarm_id=p_alarm)
 OR EXISTS(SELECT 1 FROM work_order WHERE alarm_id=p_alarm AND closed_at IS NULL)
 OR repaired IS NULL OR samples<>3 OR normal_count<>3 OR last_at<SYSDATE(6)-INTERVAL 2 MINUTE
 OR TIMESTAMPDIFF(SECOND,first_at,last_at) NOT BETWEEN 90 AND 180
 OR NOT EXISTS(SELECT 1 FROM charger WHERE id=c AND heartbeat>=SYSDATE(6)-INTERVAL 3 MINUTE AND state NOT IN ('offline','fault'))
 -- Gun-scoped recovery also checks that specific gun. The three observations
 -- remain charger-level telemetry; this demo has no separate gun telemetry.
 OR (gun IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM connector WHERE id=gun AND charger_id=c AND state NOT IN ('offline','fault')))
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='recovery conditions not met'; END IF;
 UPDATE alarm SET restored_at=SYSDATE(6) WHERE id=p_alarm;
END$$
DELIMITER ;
CREATE VIEW v_live_alarm AS SELECT a.*,c.station_id,'active' AS state FROM alarm a JOIN charger c ON c.id=a.charger_id WHERE restored_at IS NULL;
CREATE VIEW v_late_alarm AS SELECT a.* FROM v_live_alarm a WHERE deadline<=NOW() AND NOT EXISTS
 (SELECT 1 FROM work_order w WHERE w.alarm_id=a.id AND w.accepted_at IS NOT NULL);
CREATE VIEW v_repair_time AS SELECT w.*,a.charger_id,TIMESTAMPDIFF(SECOND,w.arrived_at,w.repaired_at) duration FROM work_order w JOIN alarm a ON a.id=w.alarm_id;
