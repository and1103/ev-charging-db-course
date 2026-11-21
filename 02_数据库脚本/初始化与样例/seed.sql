-- Execute once on an empty business schema. All dates are Beijing local time.
DELIMITER $$
CREATE PROCEDURE seed_charge_demo()
BEGIN
 DECLARE n int DEFAULT 1;
 DECLARE x bigint;
 DECLARE t datetime(6);
 WHILE n<=20 DO
  INSERT INTO operator(id,name) VALUES(n,CONCAT('运营商 ',n));
  INSERT INTO station(id,operator_id,name,address,spaces,parking_note) VALUES(n,n,CONCAT('场站 ',n),CONCAT('校园周边示例地址 ',n),20,'前 30 分钟免费');
  INSERT INTO charger(id,station_id,model,rated_kw,protocol,commissioned_on,heartbeat,state) VALUES(n,n,'Demo-120',120,'模拟',CURRENT_DATE,SYSDATE(6),'idle');
  INSERT INTO connector(id,charger_id,gun_position,kind,interface,max_kw,state) VALUES(n,n,1,'DC','GB',60,'idle'),(n+20,n,2,'AC','GB',7,'idle');
  INSERT INTO account(id,login,password_hash,role,balance,verified,phone_mask) VALUES(n,CONCAT('driver',n),'demo-pending','driver',100,true,CONCAT('*******',LPAD(n,4,'0')));
  INSERT INTO wallet_entry(account_id,`change`,happened_at) VALUES(n,100,'2026-10-31 00:00');
  INSERT INTO account(id,login,password_hash,role,operator_id) VALUES(n+100,CONCAT('operator',n),'demo-pending','operator',n);
  INSERT INTO account(id,login,password_hash,role,station_id) VALUES(n+200,CONCAT('tech',n),'demo-pending','maintenance',n);
  INSERT INTO account(id,login,password_hash,role) VALUES(n+300,CONCAT('fleet',n),'demo-pending','fleet');
  INSERT INTO vehicle(id,plate_mask,model,capacity_kwh,max_kw,supports_dc,interface) VALUES(n,CONCAT('******',n),'Demo EV',60,90,true,'GB');
  INSERT INTO vehicle_binding(vehicle_id,account_id,since) VALUES(n,n,'2025-01-01');
  INSERT INTO fleet(id,manager_id,name) VALUES(n,n+300,CONCAT('车队 ',n));
  INSERT INTO fleet_card(fleet_id,vehicle_id,driver_id,credit_limit) VALUES(n,n,n,1000);
  INSERT INTO campaign(id,name,station_id,face,minimum,starts,expires,stock) VALUES(n,'满 5 减 2',n,2,5,'2025-01-01','2035-01-01',100);
  INSERT INTO coupon(id,campaign_id,account_id) VALUES(n,n,n);
  INSERT INTO asset_request(charger_id,kind) VALUES(n,'acceptance');
  INSERT INTO asset_history(charger_id,old_state,new_state) VALUES(n,'offline','idle');
  INSERT INTO tariff(id,station_id,starts,ends,service_mode) VALUES(n,n,'2025-01-01','2035-01-01','kwh');
  INSERT INTO tariff_band VALUES(n,0,480,'valley',0.30,0.30),(n,480,1080,'flat',0.60,0.30),(n,1080,1440,'peak',1.00,0.30);
  INSERT INTO telemetry(charger_id,sampled_at,volts,amps,kw,temperature,offline_seconds) VALUES(n,SYSDATE(6)-INTERVAL 1 MINUTE,400,20,8,32,0);
  INSERT INTO charge_order(id,account_id,connector_id,vehicle_id,tariff_id,started_at,state) VALUES(n,n,n,n,n,'2026-11-01 17:55','charging');
  INSERT INTO meter_sample VALUES(n,'2026-11-01 17:55',100),(n,'2026-11-01 18:00',104),(n,'2026-11-01 18:06',110);
  CALL finish_charge(n,'2026-11-01 18:06',false);
  CALL redeem_coupon(n,n,n);
  SET x=post_payment(n,n,'mock',CONCAT('seed-a-',n),4,true);
  SET x=post_payment(n,n,'wallet',CONCAT('seed-b-',n),5.40,true);
  INSERT INTO consumer_invoice_request(order_id,title) VALUES(n,'演示车主');
  INSERT INTO driver_feedback(order_id,kind,content) VALUES(n,'rating','演示评价');
  SET x=raise_alarm(n,'DEMO1');
  INSERT INTO work_order(alarm_id,technician_id) VALUES(x,n+200);
  INSERT INTO work_part(work_id,part,quantity) VALUES(LAST_INSERT_ID(),'演示备件',1);
  CALL build_settlement(n,'2026-11-01');
  SET x=(SELECT id FROM settlement WHERE station_id=n AND period='2026-11-01');
  CALL begin_bill_import(x,'seed',1);
  INSERT INTO external_bill VALUES(x,n,'seed',10,10.40,true);
  CALL compare_settlement(x);
  INSERT INTO queue_entry(station_id,vehicle_id,account_id,state) VALUES(n,n,n,'expired');
  SET x=LAST_INSERT_ID(),t=NOW()-INTERVAL 10 MINUTE;
  INSERT INTO queue_call(entry_id,connector_id,called_at,deadline,notified_at) VALUES(x,n,t,t+INTERVAL 5 MINUTE,t);
  INSERT INTO gun_hold(call_id,connector_id,state) VALUES(LAST_INSERT_ID(),n,'expired');
  SET n=n+1;
 END WHILE;
END$$
DELIMITER ;
INSERT INTO account(id,login,password_hash,role) VALUES(500,'admin','demo-pending','admin'),(501,'settlement','demo-pending','settlement');
INSERT INTO alarm_rule VALUES('OFFLINE',2,10),('FAULT',3,5),('DEMO1',2,15);
INSERT INTO alarm_rule(code,severity,response_minutes)
WITH RECURSIVE samples(n) AS (SELECT 2 UNION ALL SELECT n+1 FROM samples WHERE n<18)
SELECT CONCAT('DEMO',n),2,15 FROM samples;
CALL seed_charge_demo();
DROP PROCEDURE seed_charge_demo;
