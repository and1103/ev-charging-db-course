CREATE TABLE queue_entry (
 id bigint AUTO_INCREMENT PRIMARY KEY, station_id bigint NOT NULL, FOREIGN KEY (station_id) REFERENCES station(id),
 vehicle_id bigint NOT NULL, FOREIGN KEY (vehicle_id) REFERENCES vehicle(id), account_id bigint NOT NULL, FOREIGN KEY (account_id) REFERENCES account(id),
 queued_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 state varchar(255) NOT NULL DEFAULT 'waiting' CHECK(state IN ('waiting','called','converted','expired','cancelled'))
) ENGINE=InnoDB;
CREATE TABLE queue_call (
 id bigint AUTO_INCREMENT PRIMARY KEY, entry_id bigint NOT NULL, FOREIGN KEY (entry_id) REFERENCES queue_entry(id),
 connector_id bigint NOT NULL, FOREIGN KEY (connector_id) REFERENCES connector(id), called_at datetime(6) NOT NULL, deadline datetime(6) NOT NULL,
 notified_at datetime(6) NOT NULL, UNIQUE(id,connector_id), CHECK(deadline>called_at)
) ENGINE=InnoDB;
CREATE TABLE gun_hold (
 call_id bigint PRIMARY KEY, connector_id bigint NOT NULL, state varchar(255) NOT NULL CHECK(state IN ('held','used','expired','released')),
 order_id bigint UNIQUE, FOREIGN KEY (order_id) REFERENCES charge_order(id), FOREIGN KEY(call_id,connector_id) REFERENCES queue_call(id,connector_id)
) ENGINE=InnoDB;

ALTER TABLE queue_entry ADD active_vehicle bigint GENERATED ALWAYS AS (CASE WHEN state IN ('waiting','called') THEN vehicle_id END) STORED,
 ADD UNIQUE KEY one_queue(station_id,active_vehicle),
 ADD KEY waiting_order(station_id,state,queued_at,id);
ALTER TABLE gun_hold ADD active_gun bigint GENERATED ALWAYS AS (CASE WHEN state='held' THEN connector_id END) STORED UNIQUE;
DELIMITER $$
CREATE FUNCTION in_hours(t time,a time,z time) RETURNS boolean DETERMINISTIC NO SQL
RETURN CASE WHEN a=z THEN true WHEN a<z THEN t>=a AND t<z ELSE t>=a OR t<z END$$
DELIMITER ;
CREATE VIEW v_gun_state AS
SELECT g.id,g.charger_id,c.station_id,g.kind,g.interface,g.max_kw,g.state,c.heartbeat,
 s.enabled AND in_hours(CURRENT_TIME,s.opens,s.closes) AND c.commissioned_on IS NOT NULL
 AND c.state IN ('idle','occupied') AND COALESCE(c.heartbeat>=NOW()-INTERVAL 3 MINUTE,false) AND g.state='idle' AS ready,
 h.call_id,q.deadline FROM connector g JOIN charger c ON c.id=g.charger_id JOIN station s ON s.id=c.station_id
 LEFT JOIN gun_hold h ON h.active_gun=g.id LEFT JOIN queue_call q ON q.id=h.call_id;
CREATE VIEW v_station_availability AS SELECT s.id,s.name,s.address,s.parking_note,s.enabled,
 COUNT(CASE WHEN g.ready AND (g.deadline IS NULL OR g.deadline<=NOW()) THEN 1 END) available
 FROM station s LEFT JOIN v_gun_state g ON g.station_id=s.id GROUP BY s.id,s.name,s.address,s.parking_note,s.enabled;
CREATE VIEW v_asset_history AS SELECT h.*,COALESCE(c.station_id,p.station_id) station_id FROM asset_history h
 LEFT JOIN charger c ON c.id=h.charger_id LEFT JOIN connector g ON g.id=h.connector_id LEFT JOIN charger p ON p.id=g.charger_id;
CREATE VIEW v_queue_station AS SELECT s.id,s.available,COUNT(CASE WHEN q.state='waiting' THEN 1 END) waiting
 FROM v_station_availability s LEFT JOIN queue_entry q ON q.station_id=s.id GROUP BY s.id,s.available;
DELIMITER $$
CREATE FUNCTION compatible(v bigint,g bigint) RETURNS boolean READS SQL DATA
RETURN (SELECT a.interface=b.interface AND (b.kind='AC' OR a.supports_dc)
 FROM vehicle a CROSS JOIN connector b WHERE a.id=v AND b.id=g)$$
CREATE FUNCTION assign_gun(p_gun bigint) RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE lock_id bigint; DECLARE station_key bigint; DECLARE usable boolean; DECLARE call_key bigint;
 DECLARE entry_key bigint; DECLARE expiry datetime(6); DECLARE entry_state varchar(20); DECLARE t datetime(6);
 SELECT id INTO lock_id FROM connector WHERE id=p_gun FOR UPDATE;
 SET t=SYSDATE(6);
 SELECT station_id,ready,call_id,deadline INTO station_key,usable,call_key,expiry FROM v_gun_state WHERE id=p_gun;
 IF call_key IS NOT NULL THEN
  SELECT entry_id INTO entry_key FROM queue_call WHERE id=call_key;
  SELECT state INTO entry_state FROM queue_entry WHERE id=entry_key FOR UPDATE;
  IF usable AND entry_state='called' AND expiry>t THEN RETURN call_key; END IF;
  UPDATE gun_hold SET state=IF(expiry<=t,'expired','released') WHERE call_id=call_key;
  UPDATE queue_entry SET state=IF(expiry<=t,'expired','waiting') WHERE id=entry_key AND state='called';
 END IF;
 IF NOT COALESCE(usable,false) THEN RETURN NULL; END IF;
 SET entry_key=NULL;
 SELECT e.id INTO entry_key FROM queue_entry e WHERE e.station_id=station_key AND e.state='waiting'
 AND compatible(e.vehicle_id,p_gun) AND EXISTS(SELECT 1 FROM vehicle_binding b
  WHERE b.vehicle_id=e.vehicle_id AND b.account_id=e.account_id AND b.since<=t AND (b.binding_end IS NULL OR t<b.binding_end))
 ORDER BY e.queued_at,e.id LIMIT 1 FOR UPDATE;
 IF entry_key IS NULL THEN RETURN NULL; END IF;
 INSERT INTO queue_call(entry_id,connector_id,called_at,deadline,notified_at) VALUES(entry_key,p_gun,t,t+INTERVAL 5 MINUTE,t);
 SET call_key=LAST_INSERT_ID();
 INSERT INTO gun_hold(call_id,connector_id,state) VALUES(call_key,p_gun,'held');
 UPDATE queue_entry SET state='called' WHERE id=entry_key;
 RETURN call_key;
END$$
CREATE PROCEDURE dispatch_station(IN p_station bigint)
BEGIN
 DECLARE done boolean DEFAULT false; DECLARE gun bigint; DECLARE result bigint;
 DECLARE guns CURSOR FOR SELECT id FROM v_gun_state WHERE station_id=p_station AND (ready OR call_id IS NOT NULL) ORDER BY id;
 DECLARE CONTINUE HANDLER FOR NOT FOUND SET done=true;
 OPEN guns;
 scan: LOOP
  FETCH guns INTO gun;
  IF done THEN LEAVE scan; END IF;
  SET result=assign_gun(gun);
 END LOOP;
 CLOSE guns;
END$$
CREATE FUNCTION take_queue(p_user bigint,p_vehicle bigint,p_station bigint) RETURNS bigint MODIFIES SQL DATA
BEGIN
  IF NOT EXISTS(SELECT 1 FROM vehicle_binding WHERE account_id=p_user AND vehicle_id=p_vehicle AND since<=SYSDATE(6)
   AND (binding_end IS NULL OR SYSDATE(6)<binding_end))
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='vehicle not bound'; END IF;
 INSERT INTO queue_entry(station_id,vehicle_id,account_id) VALUES(p_station,p_vehicle,p_user);
 RETURN LAST_INSERT_ID();
END$$
CREATE FUNCTION open_charge(p_user bigint,p_vehicle bigint,p_gun bigint,p_card bigint) RETURNS bigint MODIFIES SQL DATA
BEGIN
 DECLARE lock_id bigint; DECLARE station_key bigint; DECLARE usable boolean; DECLARE call_key bigint;
 DECLARE entry_key bigint; DECLARE tariff_key bigint; DECLARE result bigint;
 DECLARE fleet_key bigint; DECLARE credit decimal(12,2); DECLARE budget decimal(12,2);
 SELECT id INTO lock_id FROM connector WHERE id=p_gun FOR UPDATE;
 -- Establish the first consistent read only after the funding owner is locked.
 -- Otherwise a completed order can disappear from holds before its billed usage
 -- becomes visible to this function's earlier read snapshot.
 IF p_card IS NULL THEN
  SELECT id INTO lock_id FROM account WHERE id=p_user FOR UPDATE;
 ELSE
  SELECT fleet_id,credit_limit INTO fleet_key,credit FROM fleet_card
   WHERE id=p_card AND vehicle_id=p_vehicle AND driver_id=p_user AND enabled FOR UPDATE;
  IF fleet_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet card owner or vehicle mismatch'; END IF;
 END IF;
 SELECT station_id,ready INTO station_key,usable FROM v_gun_state WHERE id=p_gun;
 IF NOT COALESCE(usable,false) OR NOT COALESCE(compatible(p_vehicle,p_gun),false)
 OR NOT EXISTS(SELECT 1 FROM vehicle_binding WHERE account_id=p_user AND vehicle_id=p_vehicle AND since<=SYSDATE(6)
  AND (binding_end IS NULL OR SYSDATE(6)<binding_end))
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='connector unavailable or vehicle not bound'; END IF;
 IF p_card IS NOT NULL THEN
  IF fleet_key IS NULL OR EXISTS(SELECT 1 FROM charge_order WHERE fleet_card_id=p_card AND active_gun IS NOT NULL)
  THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fleet card has no available credit'; END IF;
 END IF;
 SET call_key=assign_gun(p_gun);
 IF call_key IS NOT NULL THEN
  SELECT q.entry_id INTO entry_key FROM queue_call q JOIN queue_entry e ON e.id=q.entry_id
    WHERE q.id=call_key AND e.account_id=p_user AND e.vehicle_id=p_vehicle AND q.deadline>SYSDATE(6);
  IF entry_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='gun reserved for another vehicle or call expired'; END IF;
 END IF;
 SELECT id,GREATEST(minimum,authorization_amount) INTO tariff_key,budget FROM tariff WHERE station_id=station_key AND starts<=NOW() AND NOW()<ends
 AND (fleet_id IS NULL OR fleet_id=fleet_key) ORDER BY fleet_id IS NULL,id LIMIT 1 FOR UPDATE;
 IF tariff_key IS NULL OR (SELECT COALESCE(SUM(minute_to-minute_from),0) FROM tariff_band WHERE tariff_id=tariff_key)<>1440
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='missing or incomplete tariff'; END IF;
 IF p_card IS NOT NULL THEN CALL check_fleet_credit_current(p_card,0,CAST(DATE_FORMAT(SYSDATE(6),'%Y-%m-01') AS DATE),0,budget,0); END IF;
 -- The order trigger locks the account/card and reserves this budget atomically.
 INSERT INTO charge_order(account_id,vehicle_id,connector_id,tariff_id,fleet_card_id,started_at,state,authorized_amount)
 VALUES(p_user,p_vehicle,p_gun,tariff_key,p_card,SYSDATE(6),'charging',budget);
 SET result=LAST_INSERT_ID();
 UPDATE connector SET state='occupied' WHERE id=p_gun;
 IF call_key IS NOT NULL THEN
  UPDATE gun_hold SET state='used',order_id=result WHERE call_id=call_key;
  UPDATE queue_entry SET state='converted' WHERE id=entry_key;
 END IF;
 RETURN result;
END$$
DELIMITER ;
