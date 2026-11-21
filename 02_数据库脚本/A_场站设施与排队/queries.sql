-- 场站分枪型可用量
SELECT s.id,g.kind,count(*) n FROM station s JOIN charger c ON c.station_id=s.id JOIN connector g ON g.charger_id=c.id JOIN v_gun_state v ON v.id=g.id WHERE v.ready AND (v.deadline IS NULL OR v.deadline<=now()) GROUP BY s.id,g.kind ORDER BY 1,2;
SELECT s.id,x.kind,x.n FROM station s JOIN LATERAL (SELECT kind,count(*) n FROM v_gun_state WHERE station_id=s.id AND ready AND (deadline IS NULL OR deadline<=now()) GROUP BY kind) x ON true ORDER BY 1,2;

-- 即将过保
SELECT id FROM charger WHERE warranty_until BETWEEN CURRENT_DATE AND CURRENT_DATE+INTERVAL 30 DAY ORDER BY id;
SELECT id FROM charger WHERE warranty_until>=CURRENT_DATE AND warranty_until<CURRENT_DATE+INTERVAL 31 DAY ORDER BY id;

-- 历史离线
SELECT id FROM asset_history WHERE new_state='offline' AND happened_at>=NOW()-INTERVAL 1 DAY ORDER BY id;
SELECT id FROM asset_history WHERE new_state IN ('offline') AND TIMESTAMPDIFF(MICROSECOND,happened_at,NOW())<=86400000000 ORDER BY id;
