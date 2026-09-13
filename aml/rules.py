"""Rules engine: each scenario is a SQL file in sql/ with {parameter} placeholders filled from config.yaml, run in DuckDB
against the `transactions` and `customers` tables. Every rule returns the same alert schema."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
ALERT_COLUMNS = ["customer_id", "rule_id", "alert_date", "trigger_amount", "n_txns", "txn_ids", "detail"]


def connect(transactions: pd.DataFrame, customers: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("transactions", transactions)
    con.register("customers", customers)
    return con


def render_sql(rule_id: str, params: dict, high_risk: list[str]) -> str:
    sql = (SQL_DIR / f"{rule_id}.sql").read_text()
    values = {k: v for k, v in params.items() if k not in ("weight", "tune", "enabled")}
    values["high_risk_list"] = ", ".join(f"'{c}'" for c in high_risk)
    return sql.format(**values)


def run_rule(con: duckdb.DuckDBPyConnection, rule_id: str, params: dict, high_risk: list[str]) -> pd.DataFrame:
    df = con.execute(render_sql(rule_id, params, high_risk)).df()
    if df.empty:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    df["alert_date"] = pd.to_datetime(df["alert_date"])
    return df[ALERT_COLUMNS]


def run_all(con: duckdb.DuckDBPyConnection, rules_cfg: dict, high_risk: list[str], overrides: dict | None = None) -> pd.DataFrame:
    """Run every rule; `overrides` = {rule_id: {param: value}} lets the tuner try alternative thresholds."""
    out = []
    for rule_id, params in rules_cfg.items():
        p = dict(params) | (overrides or {}).get(rule_id, {})
        if p.get("enabled", True) is False:
            continue
        out.append(run_rule(con, rule_id, p, high_risk))
    alerts = pd.concat(out, ignore_index=True)
    alerts.insert(0, "alert_id", [f"AL{i:06d}" for i in range(len(alerts))])
    return alerts.sort_values(["alert_date", "customer_id"], kind="stable").reset_index(drop=True)
