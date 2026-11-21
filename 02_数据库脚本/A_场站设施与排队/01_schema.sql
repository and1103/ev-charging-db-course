CREATE TABLE operator (id bigint AUTO_INCREMENT PRIMARY KEY, name varchar(255) NOT NULL) ENGINE=InnoDB;
CREATE TABLE station (
 id bigint AUTO_INCREMENT PRIMARY KEY, operator_id bigint NOT NULL, FOREIGN KEY (operator_id) REFERENCES operator(id),
 name varchar(255) NOT NULL, address varchar(255) NOT NULL, longitude numeric(9,6), latitude numeric(8,6),
 spaces integer NOT NULL CHECK (spaces >= 0), opens time NOT NULL DEFAULT '00:00',
 closes time NOT NULL DEFAULT '00:00', parking_note varchar(255) NOT NULL DEFAULT '', enabled boolean NOT NULL DEFAULT true
) ENGINE=InnoDB;
CREATE TABLE charger (
 id bigint AUTO_INCREMENT PRIMARY KEY, station_id bigint NOT NULL, FOREIGN KEY (station_id) REFERENCES station(id),
 model varchar(255) NOT NULL, rated_kw numeric(8,2) NOT NULL CHECK (rated_kw > 0), protocol varchar(255) NOT NULL,
 commissioned_on date, warranty_until date, heartbeat datetime(6),
 state varchar(255) NOT NULL DEFAULT 'offline' CHECK (state IN ('idle','occupied','fault','offline'))
) ENGINE=InnoDB;
CREATE TABLE connector (
 id bigint AUTO_INCREMENT PRIMARY KEY, charger_id bigint NOT NULL, FOREIGN KEY (charger_id) REFERENCES charger(id),
 gun_position integer NOT NULL CHECK (gun_position > 0), kind varchar(255) NOT NULL CHECK (kind IN ('AC','DC')),
 interface varchar(255) NOT NULL, max_kw numeric(8,2) NOT NULL CHECK (max_kw > 0),
 state varchar(255) NOT NULL DEFAULT 'offline' CHECK (state IN ('idle','occupied','fault','offline')),
 UNIQUE(charger_id,gun_position)
) ENGINE=InnoDB;
CREATE TABLE asset_history (
 id bigint AUTO_INCREMENT PRIMARY KEY, charger_id bigint, FOREIGN KEY (charger_id) REFERENCES charger(id), connector_id bigint, FOREIGN KEY (connector_id) REFERENCES connector(id),
 old_state varchar(255) NOT NULL, new_state varchar(255) NOT NULL, happened_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 CHECK (((charger_id IS NOT NULL)+(connector_id IS NOT NULL))=1)
) ENGINE=InnoDB;
CREATE TABLE asset_request (
 id bigint AUTO_INCREMENT PRIMARY KEY, charger_id bigint NOT NULL, FOREIGN KEY (charger_id) REFERENCES charger(id),
 kind varchar(255) NOT NULL CHECK (kind IN ('acceptance','amendment','offline')),
 payload json NOT NULL DEFAULT (JSON_OBJECT()), state varchar(255) NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','rejected')),
 created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

ALTER TABLE asset_request ADD pending_charger bigint GENERATED ALWAYS AS (CASE WHEN kind='offline' AND state='pending' THEN charger_id END) STORED UNIQUE;
DELIMITER $$
CREATE TRIGGER connector_power BEFORE INSERT ON connector FOR EACH ROW
BEGIN
 DECLARE kw decimal(8,2);
 SELECT rated_kw INTO kw FROM charger WHERE id=NEW.charger_id FOR UPDATE;
 IF NEW.max_kw>kw THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='connector exceeds charger power'; END IF;
END$$
CREATE TRIGGER connector_power_update BEFORE UPDATE ON connector FOR EACH ROW
BEGIN
 DECLARE kw decimal(8,2);
 IF NEW.max_kw<>OLD.max_kw OR NEW.charger_id<>OLD.charger_id THEN
 SELECT rated_kw INTO kw FROM charger WHERE id=NEW.charger_id FOR UPDATE;
 IF NEW.max_kw>kw THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='connector exceeds charger power'; END IF;
 END IF;
END$$
CREATE TRIGGER charger_power BEFORE UPDATE ON charger FOR EACH ROW
BEGIN
 IF NEW.rated_kw<OLD.rated_kw AND EXISTS(SELECT 1 FROM connector WHERE charger_id=NEW.id AND max_kw>NEW.rated_kw) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='charger power below connector power'; END IF;
END$$
CREATE TRIGGER charger_history AFTER UPDATE ON charger FOR EACH ROW
BEGIN
 IF NEW.state<>OLD.state THEN INSERT INTO asset_history(charger_id,old_state,new_state) VALUES(NEW.id,OLD.state,NEW.state); END IF;
END$$
CREATE TRIGGER connector_history AFTER UPDATE ON connector FOR EACH ROW
BEGIN
 IF NEW.state<>OLD.state THEN INSERT INTO asset_history(connector_id,old_state,new_state) VALUES(NEW.id,OLD.state,NEW.state); END IF;
END$$
CREATE PROCEDURE commission_charger(IN p_charger bigint,IN p_request bigint)
BEGIN
 UPDATE asset_request SET state='approved' WHERE id=p_request AND charger_id=p_charger AND kind='acceptance' AND state='pending';
 IF ROW_COUNT()=0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='pending acceptance required'; END IF;
 UPDATE charger SET commissioned_on=CURRENT_DATE WHERE id=p_charger;
END$$
DELIMITER ;
