-- 分场站活动核销
SELECT s.id,c.id,count(co.id),count(r.coupon_id) FROM station s JOIN campaign c ON c.station_id=s.id LEFT JOIN coupon co ON co.campaign_id=c.id LEFT JOIN redemption r ON r.coupon_id=co.id GROUP BY 1,2 ORDER BY 1,2;
SELECT c.station_id,c.id,v.issued,v.redeemed FROM campaign c JOIN v_campaign_stats v ON v.id=c.id WHERE c.station_id IS NOT NULL ORDER BY 1,2;

-- 未用有效券
SELECT id FROM v_unused_coupon ORDER BY id;
SELECT co.id FROM coupon co JOIN campaign c ON c.id=co.campaign_id LEFT JOIN redemption r ON r.coupon_id=co.id WHERE r.coupon_id IS NULL AND now()>=c.starts AND now()<c.expires ORDER BY 1;

-- 车队月消费
SELECT * FROM v_fleet_month ORDER BY fleet_id,period;
SELECT f.fleet_id,o.budget_period period,COUNT(*) orders,
 SUM(o.gross-o.discount-COALESCE((SELECT SUM(r.debt_reduction) FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=o.id),0)) amount,
 SUM(COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.order_id=o.id AND p.succeeded),0)
     -COALESCE((SELECT SUM(r.amount) FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=o.id),0)) paid,
 SUM(o.gross-o.discount-COALESCE((SELECT SUM(r.debt_reduction) FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=o.id),0)
     -COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.order_id=o.id AND p.succeeded),0)
     +COALESCE((SELECT SUM(r.amount) FROM refund r JOIN payment p ON p.id=r.payment_id WHERE p.order_id=o.id),0)) outstanding
 FROM fleet_card f JOIN charge_order o ON o.fleet_card_id=f.id WHERE o.state IN ('billed','paid')
 GROUP BY f.fleet_id,o.budget_period ORDER BY f.fleet_id,o.budget_period;
