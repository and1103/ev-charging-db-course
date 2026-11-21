-- Equivalent query pairs; each pair must return the same ordered rows.
-- Operator monthly dues and discrepancy counts.
SELECT s.operator_id,s.period,SUM(s.due) due,SUM(COALESCE(d.n,0)) differences
FROM v_settlement s LEFT JOIN (SELECT settlement_id,COUNT(*) n FROM recon_diff GROUP BY settlement_id) d ON d.settlement_id=s.id
GROUP BY s.operator_id,s.period ORDER BY s.operator_id,s.period;
SELECT s.operator_id,s.period,SUM(s.due) due,
 SUM((SELECT COUNT(*) FROM recon_diff d WHERE d.settlement_id=s.id)) differences
FROM v_settlement s GROUP BY s.operator_id,s.period ORDER BY s.operator_id,s.period;

-- Pending includes absent opinions, opposing opinions and unsafe extra-row acceptance.
SELECT id FROM v_pending_diff ORDER BY id;
SELECT d.id FROM recon_diff d LEFT JOIN diff_confirmation c ON c.diff_id=d.id
GROUP BY d.id,d.automatic_allowed HAVING COUNT(c.side)<>2 OR COUNT(DISTINCT c.conclusion)<>1
 OR (NOT d.automatic_allowed AND SUM(c.conclusion='accept')>0) ORDER BY d.id;

-- Invoice balance, including full red reversals.
SELECT id,remaining FROM v_invoice_balance ORDER BY id;
SELECT s.id,s.due-COALESCE(SUM(IF(i.original_id IS NULL,i.amount,-i.amount)),0) remaining
FROM v_settlement s LEFT JOIN settlement_invoice i ON i.settlement_id=s.id GROUP BY s.id,s.due ORDER BY s.id;

