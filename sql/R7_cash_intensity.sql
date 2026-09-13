-- R7 Cash intensity: calendar-month cash deposits >= {min_monthly_cash} and >= {multiple_of_expected} x the customer's expected monthly volume.
WITH monthly AS (
  SELECT t.customer_id, date_trunc('month', t.timestamp) AS month, SUM(t.amount) AS cash_total, COUNT(*) AS n_txns, LIST(t.txn_id) AS txn_ids
  FROM transactions t WHERE t.txn_type = 'cash_deposit'
  GROUP BY 1, 2
)
SELECT m.customer_id, 'R7_cash_intensity' AS rule_id, CAST(m.month AS DATE) AS alert_date, m.cash_total AS trigger_amount, m.n_txns, m.txn_ids,
       'cash deposits of $' || CAST(ROUND(m.cash_total, 0) AS BIGINT) || ' in the month vs expected monthly volume $' || CAST(ROUND(c.expected_monthly_volume, 0) AS BIGINT) AS detail
FROM monthly m JOIN customers c USING (customer_id)
WHERE m.cash_total >= {min_monthly_cash} AND m.cash_total >= {multiple_of_expected} * c.expected_monthly_volume
