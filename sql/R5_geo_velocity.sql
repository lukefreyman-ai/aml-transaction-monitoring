-- R5 Geographic velocity: two card/ATM transactions >= {min_amount} in different countries within {max_hours} hours.
WITH card AS (
  SELECT customer_id, txn_id, timestamp, amount, country FROM transactions
  WHERE channel = 'card' AND amount >= {min_amount}
),
pairs AS (
  SELECT a.customer_id, a.txn_id AS t1, b.txn_id AS t2, a.timestamp AS ts1, b.timestamp AS ts2, a.country AS c1, b.country AS c2,
         a.amount + b.amount AS total_amount, date_diff('minute', a.timestamp, b.timestamp) / 60.0 AS hours_apart
  FROM card a JOIN card b
    ON a.customer_id = b.customer_id AND b.timestamp > a.timestamp AND b.timestamp <= a.timestamp + INTERVAL ({max_hours}) HOUR AND a.country <> b.country
),
dedup AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id, CAST(ts1 AS DATE) ORDER BY hours_apart) AS rn FROM pairs)
SELECT customer_id, 'R5_geo_velocity' AS rule_id, CAST(ts1 AS DATE) AS alert_date, total_amount AS trigger_amount, 2 AS n_txns, [t1, t2] AS txn_ids,
       'card activity in ' || c1 || ' and ' || c2 || ' ' || ROUND(hours_apart, 1) || ' hours apart' AS detail
FROM dedup WHERE rn = 1
