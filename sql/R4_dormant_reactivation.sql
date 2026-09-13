-- R4 Dormant-then-active: a gap of >= {dormant_days} days with no activity, then >= {min_burst_amount} moved within {burst_days} days.
WITH ordered AS (
  SELECT customer_id, txn_id, timestamp, amount,
         LAG(timestamp) OVER (PARTITION BY customer_id ORDER BY timestamp) AS prev_ts
  FROM transactions
),
wake AS (
  SELECT customer_id, txn_id AS wake_txn, timestamp AS wake_ts, date_diff('day', prev_ts, timestamp) AS gap_days
  FROM ordered WHERE prev_ts IS NOT NULL AND date_diff('day', prev_ts, timestamp) >= {dormant_days}
),
burst AS (
  SELECT w.customer_id, w.wake_ts, w.gap_days, COUNT(t.txn_id) AS n_txns, SUM(t.amount) AS total_amount, LIST(t.txn_id) AS txn_ids
  FROM wake w JOIN transactions t
    ON t.customer_id = w.customer_id AND t.timestamp >= w.wake_ts AND t.timestamp < w.wake_ts + INTERVAL ({burst_days}) DAY
  GROUP BY 1, 2, 3 HAVING SUM(t.amount) >= {min_burst_amount}
)
SELECT customer_id, 'R4_dormant_reactivation' AS rule_id, CAST(wake_ts AS DATE) AS alert_date, total_amount AS trigger_amount, n_txns, txn_ids,
       'no activity for ' || gap_days || ' days, then $' || CAST(ROUND(total_amount, 0) AS BIGINT) || ' in ' || n_txns || ' transactions within ' || {burst_days} || ' days' AS detail
FROM burst
