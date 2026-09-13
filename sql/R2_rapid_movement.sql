-- R2 Rapid movement / pass-through: inbound >= {min_inbound} followed within {window_days} days by outbound totalling
-- at least {min_out_share} of the inbound amount.
WITH inbound AS (
  SELECT customer_id, txn_id, timestamp, amount FROM transactions
  WHERE txn_type IN ('wire_in', 'ach_in') AND amount >= {min_inbound}
),
outbound AS (
  SELECT customer_id, txn_id, timestamp, amount, counterparty_country FROM transactions WHERE txn_type IN ('wire_out', 'ach_out')
),
paired AS (
  SELECT i.customer_id, i.txn_id AS inbound_txn, i.timestamp AS in_ts, i.amount AS inbound_amount,
         SUM(o.amount) AS outbound_amount, COUNT(o.txn_id) AS n_out, LIST(o.txn_id) AS out_ids,
         COUNT(DISTINCT o.counterparty_country) AS n_countries
  FROM inbound i JOIN outbound o
    ON i.customer_id = o.customer_id AND o.timestamp > i.timestamp AND o.timestamp <= i.timestamp + INTERVAL ({window_days}) DAY
  GROUP BY 1, 2, 3, 4
  HAVING SUM(o.amount) >= {min_out_share} * i.amount
)
SELECT customer_id, 'R2_rapid_movement' AS rule_id, CAST(in_ts AS DATE) AS alert_date, inbound_amount AS trigger_amount, n_out + 1 AS n_txns,
       list_prepend(inbound_txn, out_ids) AS txn_ids,
       'inbound $' || CAST(ROUND(inbound_amount, 0) AS BIGINT) || ' moved out within ' || {window_days} || ' days: $' || CAST(ROUND(outbound_amount, 0) AS BIGINT) || ' in ' || n_out || ' transfer(s) to ' || n_countries || ' country(ies)' AS detail
FROM paired
