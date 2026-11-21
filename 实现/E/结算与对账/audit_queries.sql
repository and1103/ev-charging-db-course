-- Reconciliation expected customer cash. Prior-period refunds are negative rows.
SELECT settlement_id,order_id,kwh,amount,merchant_due FROM v_recon_expected ORDER BY settlement_id,order_id;
-- Batch completeness and bilateral settlement signatures.
SELECT s.id,b.batch,b.expected_rows,COUNT(e.order_id) imported_rows,b.state
FROM settlement s LEFT JOIN settlement_import b ON b.settlement_id=s.id
LEFT JOIN external_bill e ON e.settlement_id=s.id
GROUP BY s.id,b.batch,b.expected_rows,b.state ORDER BY s.id;
SELECT s.id,s.state,GROUP_CONCAT(CONCAT(c.side,':',c.actor) ORDER BY c.side) confirmations
FROM settlement s LEFT JOIN settlement_confirmation c ON c.settlement_id=s.id GROUP BY s.id,s.state ORDER BY s.id;

-- Refund reversal components; full original 100/90/0/2 results in net -88.
SELECT refund_id,order_id,customer_reduction,energy_reversal,service_reversal,fee_reversal,amount
FROM settlement_adjustment WHERE refund_id IS NOT NULL ORDER BY refund_id;
SELECT order_id,limit_amount,invoiced,remaining FROM v_consumer_invoice_balance ORDER BY order_id;
