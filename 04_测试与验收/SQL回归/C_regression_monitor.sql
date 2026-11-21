DROP PROCEDURE IF EXISTS regression_monitor;
DELIMITER $$
CREATE PROCEDURE regression_monitor()
BEGIN
 DECLARE t datetime(6); DECLARE a bigint; DECLARE w bigint; DECLARE refused boolean DEFAULT false;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 SET t=SYSDATE(6);
 UPDATE charger SET state='idle',heartbeat=t WHERE id=1;
 INSERT INTO alarm(charger_id,connector_id,code,severity,opened_at,deadline) VALUES(1,1,'FAULT',3,t-INTERVAL 8 MINUTE,t-INTERVAL 7 MINUTE);
 SET a=LAST_INSERT_ID();
 INSERT INTO work_order(alarm_id,technician_id,assigned_at) VALUES(a,201,t-INTERVAL 6 MINUTE);
 SET w=LAST_INSERT_ID();
 BEGIN
  DECLARE CONTINUE HANDLER FOR 3819,1644 SET refused=true;
  UPDATE work_order SET arrived_at=t-INTERVAL 4 MINUTE WHERE id=w;
 END;
 IF NOT refused THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='work flow skipped acceptance'; END IF;
 UPDATE work_order SET accepted_at=t-INTERVAL 5 MINUTE WHERE id=w;
 UPDATE work_order SET arrived_at=t-INTERVAL 4 MINUTE WHERE id=w;
 UPDATE work_order SET repaired_at=t-INTERVAL 3 MINUTE,result='synthetic repaired device' WHERE id=w;
 UPDATE work_order SET closed_at=t-INTERVAL 2 MINUTE WHERE id=w;
 INSERT INTO telemetry(charger_id,sampled_at,offline_seconds) VALUES(1,t-INTERVAL 330 SECOND,0),(1,t-INTERVAL 270 SECOND,0),(1,t-INTERVAL 210 SECOND,0);
 SET refused=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR 3819,1644 SET refused=true;
  CALL recover_alarm(a);
 END;
 IF NOT refused THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='pre-repair observations incorrectly recovered device'; END IF;
 INSERT INTO telemetry(charger_id,sampled_at,offline_seconds) VALUES(1,t-INTERVAL 150 SECOND,0),(1,t-INTERVAL 90 SECOND,0),(1,t-INTERVAL 30 SECOND,0);
 UPDATE connector SET state='fault' WHERE id=1;
 SET refused=false;
 BEGIN
  DECLARE CONTINUE HANDLER FOR 3819,1644 SET refused=true;
  CALL recover_alarm(a);
 END;
 IF NOT refused THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='source gun still faulted but recovery succeeded'; END IF;
 UPDATE connector SET state='idle' WHERE id=1;
 CALL recover_alarm(a);
 IF NOT EXISTS(SELECT 1 FROM alarm WHERE id=a AND restored_at IS NOT NULL)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fresh post-repair observations failed recovery'; END IF;
 ROLLBACK;
 SELECT 'monitor workflow and fresh recovery regression passed' result;
END$$
DELIMITER ;
CALL regression_monitor();
DROP PROCEDURE regression_monitor;
