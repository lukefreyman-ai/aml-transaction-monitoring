-- R8 Velocity spike: transactions in a {window_days}-day window >= {multiple} x the customer's average {window_days}-day count
-- over the prior {lookback_days} days, and at least {min_count}.
WITH daily AS (
  SELECT customer_id, CAST(timestamp AS DATE) AS d, COUNT(*) AS n FROM transactions GROUP BY 1, 2
),
win AS (
  SELECT a.customer_id, a.d AS window_start,
         (SELECT SUM(n) FROM daily b WHERE b.customer_id = a.customer_id AND b.d >= a.d AND b.d < a.d + INTERVAL ({window_days}) DAY) AS n_window,
         (SELECT COALESCE(SUM(n), 0) FROM daily b WHERE b.customer_id = a.customer_id AND b.d < a.d AND b.d >= a.d - INTERVAL ({lookback_days}) DAY) AS n_lookback
  FROM daily a
),
flagged AS (
  SELECT *, n_lookback * {window_days} / {lookback_days} AS baseline
  FROM win
  WHERE n_window >= {min_count} AND n_window >= {multiple} * GREATEST(n_lookback * {window_days} / {lookback_days}, 1)
),
dedup AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id, date_trunc('month', window_start) ORDER BY n_window DESC) AS rn FROM flagged),
ids AS (
  SELECT f.customer_id, f.window_start, LIST(t.txn_id) AS txn_ids, SUM(t.amount) AS total_amount
  FROM dedup f JOIN transactions t ON t.customer_id = f.customer_id AND CAST(t.timestamp AS DATE) >= f.window_start AND CAST(t.timestamp AS DATE) < f.window_start + INTERVAL ({window_days}) DAY
  WHERE f.rn = 1 GROUP BY 1, 2
)
SELECT f.customer_id, 'R8_velocity_spike' AS rule_id, f.window_start AS alert_date, i.total_amount AS trigger_amount, f.n_window AS n_txns, i.txn_ids,
       f.n_window || ' transactions in ' || {window_days} || ' days vs a baseline of ' || ROUND(f.baseline, 1) AS detail
FROM dedup f JOIN ids i USING (customer_id, window_start) WHERE f.rn = 1
