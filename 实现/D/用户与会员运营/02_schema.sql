CREATE TABLE account (
 id bigint AUTO_INCREMENT PRIMARY KEY, login varchar(255) NOT NULL UNIQUE, password_hash varchar(255) NOT NULL,
 role varchar(255) NOT NULL CHECK(role IN ('driver','admin','maintenance','settlement','operator','fleet')),
 operator_id bigint, FOREIGN KEY (operator_id) REFERENCES operator(id), station_id bigint, FOREIGN KEY (station_id) REFERENCES station(id),
 phone_cipher blob, phone_mask varchar(255), verified boolean NOT NULL DEFAULT false,
 channel varchar(255) NOT NULL DEFAULT 'local', registered_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 tier varchar(255) NOT NULL DEFAULT 'regular', balance numeric(12,2) NOT NULL DEFAULT 0 CHECK(balance>=0),
 failed_logins integer NOT NULL DEFAULT 0, locked_until datetime(6)
) ENGINE=InnoDB;
CREATE TABLE vehicle (
 id bigint AUTO_INCREMENT PRIMARY KEY, plate_cipher blob, plate_mask varchar(255),
 model varchar(255) NOT NULL, capacity_kwh numeric(8,2) NOT NULL CHECK(capacity_kwh>0),
 max_kw numeric(8,2) NOT NULL CHECK(max_kw>0), supports_dc boolean NOT NULL, interface varchar(255) NOT NULL
) ENGINE=InnoDB;
CREATE TABLE vehicle_binding (
 id bigint AUTO_INCREMENT PRIMARY KEY, vehicle_id bigint NOT NULL, FOREIGN KEY (vehicle_id) REFERENCES vehicle(id),
 account_id bigint NOT NULL, FOREIGN KEY (account_id) REFERENCES account(id), since datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), binding_end datetime(6),
 CHECK(binding_end IS NULL OR binding_end>since)
) ENGINE=InnoDB;
CREATE TABLE fleet (
 id bigint AUTO_INCREMENT PRIMARY KEY, manager_id bigint NOT NULL, FOREIGN KEY (manager_id) REFERENCES account(id), name varchar(255) NOT NULL
) ENGINE=InnoDB;
CREATE TABLE fleet_card (
 id bigint AUTO_INCREMENT PRIMARY KEY, fleet_id bigint NOT NULL, FOREIGN KEY (fleet_id) REFERENCES fleet(id),
 vehicle_id bigint NOT NULL, FOREIGN KEY (vehicle_id) REFERENCES vehicle(id), driver_id bigint NOT NULL, FOREIGN KEY (driver_id) REFERENCES account(id),
 credit_limit numeric(12,2) NOT NULL CHECK(credit_limit>=0), enabled boolean NOT NULL DEFAULT true
) ENGINE=InnoDB;
CREATE TABLE campaign (
 id bigint AUTO_INCREMENT PRIMARY KEY, name varchar(255) NOT NULL, station_id bigint, FOREIGN KEY (station_id) REFERENCES station(id),
 tier varchar(255), face numeric(12,2) NOT NULL CHECK(face>0), minimum numeric(12,2) NOT NULL CHECK(minimum>=0),
 starts datetime(6) NOT NULL, expires datetime(6) NOT NULL CHECK(expires>starts), stock integer NOT NULL CHECK(stock>=0),
 opens time NOT NULL DEFAULT '00:00', closes time NOT NULL DEFAULT '00:00'
) ENGINE=InnoDB;
CREATE TABLE coupon (
 id bigint AUTO_INCREMENT PRIMARY KEY, campaign_id bigint NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaign(id),
 account_id bigint NOT NULL, FOREIGN KEY (account_id) REFERENCES account(id), issued_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE(campaign_id,account_id)
) ENGINE=InnoDB;

ALTER TABLE vehicle_binding ADD current_vehicle bigint GENERATED ALWAYS AS (CASE WHEN binding_end IS NULL THEN vehicle_id END) STORED UNIQUE;
DELIMITER $$
CREATE PROCEDURE check_binding(IN v bigint,IN excluding bigint,IN a datetime(6),IN z datetime(6))
BEGIN
 DECLARE locked bigint;
 SELECT id INTO locked FROM vehicle WHERE id=v FOR UPDATE;
 IF EXISTS(SELECT 1 FROM vehicle_binding b WHERE b.vehicle_id=v AND b.id<>excluding
  AND b.since<COALESCE(z,'9999-12-31') AND a<COALESCE(b.binding_end,'9999-12-31')) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='vehicle binding overlap'; END IF;
END$$
CREATE TRIGGER binding_insert BEFORE INSERT ON vehicle_binding FOR EACH ROW
BEGIN CALL check_binding(NEW.vehicle_id,0,NEW.since,NEW.binding_end); END$$
CREATE TRIGGER binding_update BEFORE UPDATE ON vehicle_binding FOR EACH ROW
BEGIN CALL check_binding(NEW.vehicle_id,OLD.id,NEW.since,NEW.binding_end); END$$
CREATE FUNCTION issue_coupon(p_campaign bigint,p_user bigint) RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE result bigint;
 DECLARE capacity int;
 SELECT stock INTO capacity FROM campaign WHERE id=p_campaign FOR UPDATE;
 SET result=(SELECT id FROM coupon WHERE campaign_id=p_campaign AND account_id=p_user);
 IF result IS NOT NULL THEN RETURN result; END IF;
 IF NOT EXISTS(SELECT 1 FROM campaign c JOIN account a ON a.id=p_user WHERE c.id=p_campaign AND NOW()>=c.starts
 AND NOW()<c.expires AND (c.tier IS NULL OR c.tier=a.tier)) OR
 (SELECT COUNT(*) FROM coupon WHERE campaign_id=p_campaign)>=capacity THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='campaign unavailable'; END IF;
 INSERT INTO coupon(campaign_id,account_id) VALUES(p_campaign,p_user);
 RETURN LAST_INSERT_ID();
END$$
DELIMITER ;
