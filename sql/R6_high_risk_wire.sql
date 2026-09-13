-- R6 High-risk jurisdiction: outbound wire >= {min_amount} to a high-risk country (list from config).
SELECT customer_id, 'R6_high_risk_wire' AS rule_id, CAST(timestamp AS DATE) AS alert_date, amount AS trigger_amount, 1 AS n_txns, [txn_id] AS txn_ids,
       'wire of $' || CAST(ROUND(amount, 0) AS BIGINT) || ' to high-risk jurisdiction ' || counterparty_country AS detail
FROM transactions
WHERE txn_type = 'wire_out' AND amount >= {min_amount} AND counterparty_country IN ({high_risk_list})
