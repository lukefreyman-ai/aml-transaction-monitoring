-- R1 Structuring: >= {min_count} cash deposits in [{cash_min}, {cash_max}) within {window_days} days for one customer.
-- Each qualifying deposit is anchored on itself and looks forward {window_days} days.
WITH cash AS (
  SELECT customer_id, txn_id, timestamp, amount, branch_id
  FROM transactions
  WHERE txn_type = 'cash_deposit' AND amount >= {cash_min} AND amount < {cash_max}
),
win AS (
  SELECT a.customer_id, a.txn_id AS anchor_txn, a.timestamp AS window_start,
         COUNT(*) AS n_txns, SUM(b.amount) AS total_amount, COUNT(DISTINCT b.branch_id) AS n_branches,
         MIN(b.timestamp) AS first_ts, MAX(b.timestamp) AS last_ts, LIST(b.txn_id) AS txn_ids
  FROM cash a JOIN cash b
    ON a.customer_id = b.customer_id AND b.timestamp >= a.timestamp AND b.timestamp < a.timestamp + INTERVAL ({window_days}) DAY
  GROUP BY 1, 2, 3
  HAVING COUNT(*) >= {min_count}
),
dedup AS (  -- keep one alert per customer per calendar week
  SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id, date_trunc('week', window_start) ORDER BY n_txns DESC, total_amount DESC) AS rn FROM win
)
SELECT customer_id, 'R1_structuring' AS rule_id, CAST(window_start AS DATE) AS alert_date, total_amount AS trigger_amount, n_txns, txn_ids,
       'cash deposits just under $10k: ' || n_txns || ' deposits totalling $' || CAST(ROUND(total_amount, 0) AS BIGINT) || ' across ' || n_branches || ' branch(es) in ' || {window_days} || ' days' AS detail
FROM dedup WHERE rn = 1
