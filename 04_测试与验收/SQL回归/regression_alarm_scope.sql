-- MySQL 8.4 regression; run after the alarm-scope schema/routines/views refresh.
-- Creates isolated fixtures. All fixture rows are rolled back on success/failure.
-- Creating/dropping this test procedure is DDL; AUTO_INCREMENT counters may advance.
-- Run in a dedicated session with no pending transaction and DDL/routine privileges.
DELIMITER $$
DROP PROCEDURE IF EXISTS regression_alarm_scope$$
CREATE PROCEDURE regression_alarm_scope()
BEGIN
 DECLARE op bigint; DECLARE site bigint; DECLARE c1 bigint; DECLARE c2 bigint;
 DECLARE g1 bigint; DECLARE g2 bigint; DECLARE foreign_gun bigint;
 DECLARE first_alarm bigint; DECLARE repeated_alarm bigint; DECLARE second_alarm bigint;
 DECLARE charger_alarm bigint; DECLARE charger_repeat bigint; DECLARE ignored_alarm bigint;
 DECLARE rule_code varchar(255); DECLARE rejected boolean DEFAULT false;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION
 BEGIN
  ROLLBACK;
  RESIGNAL;
 END;

 START TRANSACTION;
 SET rule_code=CONCAT('REG_SCOPE_',REPLACE(UUID(),'-',''));
 INSERT INTO operator(name) VALUES('alarm scope regression');
 SET op=LAST_INSERT_ID();
 INSERT INTO station(operator_id,name,address,spaces) VALUES(op,'alarm scope regression','transaction fixture',3);
 SET site=LAST_INSERT_ID();
 INSERT INTO charger(station_id,model,rated_kw,protocol,state) VALUES(site,'scope fixture',120,'demo','idle');
 SET c1=LAST_INSERT_ID();
 INSERT INTO charger(station_id,model,rated_kw,protocol,state) VALUES(site,'other scope fixture',120,'demo','idle');
 SET c2=LAST_INSERT_ID();
 INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(c1,1,'DC','demo',60,'idle');
 SET g1=LAST_INSERT_ID();
 INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(c1,2,'DC','demo',60,'idle');
 SET g2=LAST_INSERT_ID();
 INSERT INTO connector(charger_id,gun_position,kind,interface,max_kw,state) VALUES(c2,1,'DC','demo',60,'idle');
 SET foreign_gun=LAST_INSERT_ID();
 INSERT INTO alarm_rule(code,severity,response_minutes) VALUES(rule_code,2,15);

 SET first_alarm=raise_alarm_scope(c1,g1,rule_code);
 SET repeated_alarm=raise_alarm_scope(c1,g1,rule_code);
 IF first_alarm IS NULL OR first_alarm<>repeated_alarm
 OR (SELECT COUNT(*) FROM alarm_notice WHERE alarm_id=first_alarm AND kind='opened')<>1
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='same source must deduplicate'; END IF;

 SET second_alarm=raise_alarm_scope(c1,g2,rule_code);
 IF second_alarm IS NULL OR second_alarm=first_alarm
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='different guns must keep distinct alarms'; END IF;

 SET charger_alarm=raise_alarm(c1,rule_code);
 SET charger_repeat=raise_alarm_scope(c1,NULL,rule_code);
 IF charger_alarm IS NULL OR charger_alarm<>charger_repeat
 OR charger_alarm IN (first_alarm,second_alarm)
 OR NOT EXISTS(SELECT 1 FROM alarm WHERE id=charger_alarm AND connector_id IS NULL AND scope_connector=0)
 OR (SELECT COUNT(*) FROM alarm WHERE charger_id=c1 AND code=rule_code AND restored_at IS NULL)<>3
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='NULL scope must preserve charger compatibility'; END IF;

 IF NOT EXISTS(SELECT 1 FROM v_live_alarm WHERE id=first_alarm AND connector_id=g1 AND state='active')
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='live view must expose source gun and state'; END IF;

 SET rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  SET ignored_alarm=raise_alarm_scope(c1,foreign_gun,rule_code);
 END;
 IF NOT rejected THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='cross charger gun must be rejected by function'; END IF;

 SET rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  INSERT INTO alarm(charger_id,connector_id,code,severity,deadline)
  VALUES(c1,foreign_gun,rule_code,2,NOW()+INTERVAL 15 MINUTE);
 END;
 IF NOT rejected THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='direct insert must enforce gun ownership'; END IF;

 SET rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  UPDATE alarm SET connector_id=foreign_gun WHERE id=first_alarm;
 END;
 IF NOT rejected OR NOT EXISTS(SELECT 1 FROM alarm WHERE id=first_alarm AND connector_id=g1 AND charger_id=c1)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='direct gun update must enforce ownership'; END IF;

 SET rejected=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET rejected=true;
  UPDATE alarm SET charger_id=c2 WHERE id=first_alarm;
 END;
 IF NOT rejected OR NOT EXISTS(SELECT 1 FROM alarm WHERE id=first_alarm AND connector_id=g1 AND charger_id=c1)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='direct charger update must enforce ownership'; END IF;

 ROLLBACK;
 IF EXISTS(SELECT 1 FROM alarm_rule WHERE code=rule_code)
 OR EXISTS(SELECT 1 FROM operator WHERE id=op)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture rollback failed'; END IF;
 SELECT 'PASS: scoped deduplication, distinct guns, NULL compatibility, ownership guards and live view' AS result;
END$$
DELIMITER ;
CALL regression_alarm_scope();
DROP PROCEDURE regression_alarm_scope;
