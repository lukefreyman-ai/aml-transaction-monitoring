-- R3 Round-dollar pattern: >= {min_count} transfers that are exact multiples of {round_to} and >= {min_amount} within {window_days} days.
WITH rd AS (
  SELECT customer_id, txn_id, timestamp, amount FROM transactions
  WHERE txn_type IN ('wire_in', 'wire_out', 'ach_in', 'ach_out') AND amount >= {min_amount} AND (amount % {round_to}) = 0
),
win AS (
  SELECT a.customer_id, a.timestamp AS window_start, COUNT(*) AS n_txns, SUM(b.amount) AS total_amount, LIST(b.txn_id) AS txn_ids
  FROM rd a JOIN rd b ON a.customer_id = b.customer_id AND b.timestamp >= a.timestamp AND b.timestamp < a.timestamp + INTERVAL ({window_days}) DAY
  GROUP BY 1, 2 HAVING COUNT(*) >= {min_count}
),
dedup AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id, date_trunc('month', window_start) ORDER BY n_txns DESC) AS rn FROM win)
SELECT customer_id, 'R3_round_dollar' AS rule_id, CAST(window_start AS DATE) AS alert_date, total_amount AS trigger_amount, n_txns, txn_ids,
       n_txns || ' round-dollar transfers (multiples of $' || {round_to} || ') totalling $' || CAST(ROUND(total_amount, 0) AS BIGINT) || ' in ' || {window_days} || ' days' AS detail
FROM dedup WHERE rn = 1
