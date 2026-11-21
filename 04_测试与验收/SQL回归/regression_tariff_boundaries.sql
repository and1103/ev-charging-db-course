-- Synthetic exact-boundary cases. All business rows roll back on success/failure.
SET time_zone='+08:00';
DROP PROCEDURE IF EXISTS regression_tariff_boundaries;
DELIMITER $$
CREATE PROCEDURE regression_tariff_boundaries()
BEGIN
 DECLARE op bigint; DECLARE user_key bigint; DECLARE vehicle_key bigint;
 DECLARE station_key bigint; DECLARE charger_key bigint; DECLARE gun_key bigint; DECLARE tariff_key bigint;
 DECLARE order_key bigint; DECLARE hour_gun bigint; DECLARE hour_tariff bigint; DECLARE floor_gun bigint; DECLARE floor_tariff bigint;
 DECLARE t datetime(6); DECLARE duration_minutes int; DECLARE units decimal(12,4); DECLARE expected decimal(12,2);
 DECLARE n int DEFAULT 1; DECLARE prefix varchar(64);
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 SET prefix=CONCAT('tariff-test-',UUID());
 INSERT INTO operator(name) VALUES(prefix); SET op=LAST_INSERT_ID();
 INSERT INTO account(login,password_hash,role,balance,verified) VALUES(prefix,'!disabled-test-account','driver',100,true); SET user_key=LAST_INSERT_ID();
 INSERT INTO vehicle(plate_mask,model,capacity_kwh,max_kw,supports_dc,interface) VALUES('synthetic','tariff regression',60,60,true,'GB'); SET vehicle_key=LAST_INSERT_ID();
 INSERT INTO vehicle_binding(vehicle_id,account_id) VALUES(vehicle_key,user_key);
 WHILE n<=3 DO
  INSERT INTO station(operator_id,name,address,spaces) VALUES(op,CONCAT(prefix,'-',n),'synthetic tariff boundary',1); SET station_key=LAST_INSERT_ID();
  INSERT INTO charger(station_id,model,rated_kw,protocol,commissioned_on,heartbeat,state)
   VALUES(station_key,'boundary',60,'mock',CURRENT_DATE,SYSDATE(6),'idle'); SET charger_key=LAST_INSERT_ID();
  INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(charger_key,1,'DC','GB',60,'idle'); SET gun_key=LAST_INSERT_ID();
  INSERT INTO tariff(station_id,starts,ends,service_mode,free_minutes,minimum)
   VALUES(station_key,'2025-01-01','2035-01-01',IF(n=1,'kwh','hour'),IF(n=1,0,10),IF(n=3,3,0)); SET tariff_key=LAST_INSERT_ID();
  IF n=1 THEN
   INSERT INTO tariff_band VALUES(tariff_key,0,480,'valley',0.50,0.10),(tariff_key,480,1440,'peak',1.00,0.20);
   INSERT INTO charge_order(account_id,vehicle_id,connector_id,tariff_id,started_at,state)
    VALUES(user_key,vehicle_key,gun_key,tariff_key,'2026-11-10 23:50','charging'); SET order_key=LAST_INSERT_ID();
   INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(order_key,'2026-11-10 23:50',100),
    (order_key,'2026-11-11 00:00',102),(order_key,'2026-11-11 00:10',105);
   CALL finish_charge(order_key,'2026-11-11 00:10',false);
   IF (SELECT COUNT(*) FROM fee_detail WHERE order_id=order_key)<>2
    OR (SELECT SUM(kwh) FROM fee_detail WHERE order_id=order_key)<>5
    OR (SELECT SUM(energy) FROM fee_detail WHERE order_id=order_key)<>3.50
    OR (SELECT SUM(service) FROM fee_detail WHERE order_id=order_key)<>0.70
    OR (SELECT gross FROM charge_order WHERE id=order_key)<>4.20
    OR (SELECT state FROM charge_order WHERE id=order_key)<>'billed' THEN
     SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='midnight bands or measured segment energy billed incorrectly'; END IF;
  ELSEIF n=2 THEN
   SET hour_gun=gun_key,hour_tariff=tariff_key;
   INSERT INTO tariff_band VALUES(tariff_key,0,720,'flat',1,6),(tariff_key,720,1440,'peak',2,12);
   INSERT INTO charge_order(account_id,vehicle_id,connector_id,tariff_id,started_at,state)
    VALUES(user_key,vehicle_key,gun_key,tariff_key,'2026-11-11 11:55','charging'); SET order_key=LAST_INSERT_ID();
   INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(order_key,'2026-11-11 11:55',0),
    (order_key,'2026-11-11 12:00',1),(order_key,'2026-11-11 12:15',4);
   CALL finish_charge(order_key,'2026-11-11 12:15',false);
   IF (SELECT SUM(energy) FROM fee_detail WHERE order_id=order_key)<>7
    OR (SELECT SUM(service) FROM fee_detail WHERE order_id=order_key)<>2
    OR (SELECT gross FROM charge_order WHERE id=order_key)<>9 THEN
     SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='hour service free window must span price boundaries once per order'; END IF;
  ELSE
   SET floor_gun=gun_key,floor_tariff=tariff_key;
   INSERT INTO tariff_band VALUES(tariff_key,0,1440,'flat',1,6);
  END IF;
  SET n=n+1;
 END WHILE;
 -- Exact free-duration boundary: ten minutes are free; the eleventh costs 0.10.
 SET n=10;
 WHILE n<=11 DO
  SET t=TIMESTAMPADD(HOUR,n,'2026-11-12 00:00:00');
  INSERT INTO charge_order(account_id,vehicle_id,connector_id,tariff_id,started_at,state)
   VALUES(user_key,vehicle_key,hour_gun,hour_tariff,t,'charging'); SET order_key=LAST_INSERT_ID();
  INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(order_key,t,0),(order_key,TIMESTAMPADD(MINUTE,n,t),1);
  CALL finish_charge(order_key,TIMESTAMPADD(MINUTE,n,t),false);
  SET expected=IF(n=10,1,1.10);
  IF (SELECT gross FROM charge_order WHERE id=order_key)<>expected THEN
   SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='free-minute equality or first billable minute boundary incorrect'; END IF;
  SET n=n+1;
 END WHILE;
 -- The minimum is a floor, not an additional fee: below/equal/above 3.00.
 SET n=1;
 WHILE n<=3 DO
  SET t=TIMESTAMPADD(HOUR,n,'2026-11-13 10:00:00'),duration_minutes=8+n,
   units=IF(n=1,1,3),expected=IF(n=3,3.10,3.00);
  INSERT INTO charge_order(account_id,vehicle_id,connector_id,tariff_id,started_at,state)
   VALUES(user_key,vehicle_key,floor_gun,floor_tariff,t,'charging'); SET order_key=LAST_INSERT_ID();
  INSERT INTO meter_sample(order_id,sampled_at,reading) VALUES(order_key,t,0),(order_key,TIMESTAMPADD(MINUTE,duration_minutes,t),units);
  CALL finish_charge(order_key,TIMESTAMPADD(MINUTE,duration_minutes,t),false);
  IF (SELECT gross FROM charge_order WHERE id=order_key)<>expected THEN
   SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='minimum fee floor below/equal/above boundary incorrect'; END IF;
  SET n=n+1;
 END WHILE;
 ROLLBACK;
 SELECT 'tariff midnight/hour/free-minute/minimum boundary regression passed' AS result;
END$$
DELIMITER ;
CALL regression_tariff_boundaries();
DROP PROCEDURE regression_tariff_boundaries;
