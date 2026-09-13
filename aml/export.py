"""Power BI-ready star schema (CSV): dim_customer, dim_account, dim_rule, dim_date, fact_transaction, fact_alert, bridge_alert_txn."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_star(out_dir: Path, customers: pd.DataFrame, accounts: pd.DataFrame, txns: pd.DataFrame, alerts: pd.DataFrame, rules_cfg: dict) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dim_customer = customers.rename(columns={"suspicious_typology": "label_typology"})
    dim_account = accounts
    dim_rule = pd.DataFrame([{"rule_id": r, "weight": p["weight"], "enabled": p.get("enabled", True), **{k: v for k, v in p.items() if k not in ("weight", "tune", "enabled")}} for r, p in rules_cfg.items()])
    dates = pd.date_range(txns.timestamp.min().normalize(), txns.timestamp.max().normalize(), freq="D")
    dim_date = pd.DataFrame({"date_key": dates.strftime("%Y%m%d").astype(int), "date": dates, "year": dates.year, "month": dates.month,
                             "month_name": dates.strftime("%b"), "week": dates.isocalendar().week.to_numpy(), "weekday": dates.day_name()})
    fact_txn = txns.assign(date_key=txns.timestamp.dt.strftime("%Y%m%d").astype(int))[
        ["txn_id", "customer_id", "account_id", "date_key", "timestamp", "txn_type", "direction", "channel", "amount", "country", "counterparty_id", "counterparty_country", "branch_id", "typology"]]
    fact_alert = alerts.assign(date_key=alerts.alert_date.dt.strftime("%Y%m%d").astype(int))[
        ["alert_id", "customer_id", "rule_id", "date_key", "alert_date", "trigger_amount", "n_txns", "score", "priority", "hit", "any_suspicious", "detail"]]
    bridge = alerts[["alert_id", "txn_ids"]].explode("txn_ids").rename(columns={"txn_ids": "txn_id"})
    tables = {"dim_customer": dim_customer, "dim_account": dim_account, "dim_rule": dim_rule, "dim_date": dim_date,
              "fact_transaction": fact_txn, "fact_alert": fact_alert, "bridge_alert_txn": bridge}
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    return {k: len(v) for k, v in tables.items()}
