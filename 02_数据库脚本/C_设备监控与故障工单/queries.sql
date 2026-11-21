-- 场站分级响应时间
SELECT s.id,a.severity,avg(TIMESTAMPDIFF(SECOND,a.opened_at,w.accepted_at)) FROM station s JOIN charger c ON c.station_id=s.id JOIN alarm a ON a.charger_id=c.id JOIN work_order w ON w.alarm_id=a.id GROUP BY 1,2 ORDER BY 1,2;
SELECT c.station_id,a.severity,avg(x.delay) FROM alarm a JOIN charger c ON c.id=a.charger_id JOIN LATERAL (SELECT TIMESTAMPDIFF(SECOND,a.opened_at,w.accepted_at) delay FROM work_order w WHERE w.alarm_id=a.id) x ON true GROUP BY 1,2 ORDER BY 1,2;

-- 逾期未响应
SELECT id FROM v_late_alarm ORDER BY id;
SELECT a.id FROM alarm a LEFT JOIN work_order w ON w.alarm_id=a.id AND w.accepted_at IS NOT NULL WHERE a.restored_at IS NULL AND a.deadline<=now() AND w.id IS NULL ORDER BY a.id;

-- 复修告警
SELECT alarm_id FROM work_order GROUP BY alarm_id HAVING count(*)>1 ORDER BY 1;
SELECT a.id FROM alarm a WHERE (SELECT count(*) FROM work_order WHERE alarm_id=a.id)>1 ORDER BY 1;
