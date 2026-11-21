-- 近30天分时电量和费用
SELECT v.station_id,v.label,sum(v.kwh),sum(v.energy),sum(v.service) FROM v_band_income v JOIN station s ON s.id=v.station_id WHERE v.service_day>=CURRENT_DATE-INTERVAL 29 DAY GROUP BY 1,2 ORDER BY 1,2;
SELECT o.station_id,f.label,sum(f.kwh),sum(f.energy),sum(f.service) FROM fee_detail f JOIN charge_order o ON o.id=f.order_id JOIN station s ON s.id=o.station_id WHERE o.state IN ('billed','paid') AND DATE(f.begins)>=CURRENT_DATE-INTERVAL 29 DAY GROUP BY 1,2 ORDER BY 1,2;

-- 部分付款
SELECT id FROM v_unpaid_order WHERE received>refunded ORDER BY id;
SELECT id FROM v_order_balance WHERE state='billed' AND outstanding>0 AND received-refunded>0 ORDER BY id;

-- 核价对照
SELECT o.id,o.gross,coalesce(sum(f.energy+f.service),0) detail FROM charge_order o LEFT JOIN fee_detail f ON f.order_id=o.id GROUP BY o.id,o.gross ORDER BY 1;
SELECT o.id,o.gross,coalesce((SELECT sum(energy+service) FROM fee_detail WHERE order_id=o.id),0) detail FROM charge_order o ORDER BY 1;
