-- 运营商应结与差异
SELECT op.id,s.period,sum(s.due),sum(coalesce(d.n,0)) FROM operator op JOIN v_settlement s ON s.operator_id=op.id LEFT JOIN (SELECT settlement_id,count(*) n FROM recon_diff GROUP BY 1) d ON d.settlement_id=s.id GROUP BY 1,2 ORDER BY 1,2;
SELECT op.id,s.period,sum(s.due),sum((SELECT count(*) FROM recon_diff d WHERE d.settlement_id=s.id)) FROM operator op JOIN v_settlement s ON s.operator_id=op.id GROUP BY 1,2 ORDER BY 1,2;

-- 未确认差异
SELECT id FROM v_pending_diff ORDER BY id;
SELECT d.id FROM recon_diff d LEFT JOIN diff_confirmation c ON c.diff_id=d.id GROUP BY d.id HAVING count(c.side)<2 ORDER BY d.id;

-- 可开票余额
SELECT id,remaining FROM v_invoice_balance ORDER BY id;
SELECT s.id,s.due-coalesce(sum(CASE WHEN i.original_id IS NULL THEN i.amount ELSE -i.amount END),0) FROM v_settlement s LEFT JOIN settlement_invoice i ON i.settlement_id=s.id GROUP BY s.id,s.due ORDER BY 1;
