"""Alert scoring and prioritisation.

score = rule weight x severity + risk-rating bonus + multi-rule bonus
  severity        = 1 + log2(trigger_amount / rule's amount threshold), floored at 1 (a $50k structuring case outranks a $25k one)
  risk-rating     = onboarding risk rating of the customer (low / medium / high)
  multi-rule      = each *additional* distinct rule firing on the same customer within 30 days
Priority bands (high / medium / low) come from config.scoring.priority_bands."""
from __future__ import annotations

import numpy as np
import pandas as pd

AMOUNT_PARAM = {  # the threshold that trigger_amount is compared against for severity
    "R1_structuring": lambda p: p["cash_min"] * p["min_count"], "R2_rapid_movement": lambda p: p["min_inbound"],
    "R3_round_dollar": lambda p: p["min_amount"] * p["min_count"], "R4_dormant_reactivation": lambda p: p["min_burst_amount"],
    "R5_geo_velocity": lambda p: p["min_amount"] * 2, "R6_high_risk_wire": lambda p: p["min_amount"],
    "R7_cash_intensity": lambda p: p["min_monthly_cash"], "R8_velocity_spike": lambda p: 5000.0,
}


def score_alerts(alerts: pd.DataFrame, customers: pd.DataFrame, rules_cfg: dict, scoring_cfg: dict) -> pd.DataFrame:
    if alerts.empty:
        return alerts.assign(score=[], priority=[])
    a = alerts.merge(customers[["customer_id", "risk_rating"]], on="customer_id", how="left")
    weight = a["rule_id"].map({r: p["weight"] for r, p in rules_cfg.items()}).astype(float)
    base = a["rule_id"].map({r: float(AMOUNT_PARAM[r](p)) for r, p in rules_cfg.items()}).astype(float)
    severity = np.maximum(1.0, 1.0 + np.log2(np.maximum(a["trigger_amount"].astype(float), 1.0) / base))
    risk_bonus = a["risk_rating"].map(scoring_cfg["risk_rating_bonus"]).fillna(0).astype(float)
    # distinct other rules on the same customer within +/-30 days
    a = a.sort_values(["customer_id", "alert_date"]).reset_index(drop=True)
    multi = np.zeros(len(a))
    for cid, grp in a.groupby("customer_id"):
        dates = grp["alert_date"].to_numpy(); rules = grp["rule_id"].to_numpy()
        for i, (d, r) in enumerate(zip(dates, rules)):
            near = np.abs((dates - d) / np.timedelta64(1, "D")) <= 30
            multi[grp.index[i]] = len(set(rules[near]) - {r})
    a["severity"] = severity.round(2)
    a["score"] = (weight * severity + risk_bonus + scoring_cfg["multi_rule_bonus"] * multi).round(1)
    a["n_other_rules_30d"] = multi.astype(int)
    bands = scoring_cfg["priority_bands"]
    a["priority"] = np.where(a["score"] >= bands["high"], "high", np.where(a["score"] >= bands["medium"], "medium", "low"))
    return a.sort_values("score", ascending=False).reset_index(drop=True)


def label_alerts(alerts: pd.DataFrame, customers: pd.DataFrame, rule_typology: dict[str, str]) -> pd.DataFrame:
    """Ground truth from the generator: an alert is a *hit* when the customer was injected with the typology the rule
    targets, and a *partial hit* when the customer is suspicious for a different typology."""
    truth = customers.set_index("customer_id")["suspicious_typology"]
    a = alerts.copy()
    a["customer_typology"] = a["customer_id"].map(truth).fillna("")
    a["target_typology"] = a["rule_id"].map(rule_typology)
    a["hit"] = (a["customer_typology"] == a["target_typology"]) & (a["customer_typology"] != "")
    a["any_suspicious"] = a["customer_typology"] != ""
    return a


RULE_TYPOLOGY = {
    "R1_structuring": "structuring", "R2_rapid_movement": "rapid_movement", "R3_round_dollar": "round_dollar",
    "R4_dormant_reactivation": "dormant_reactivation", "R5_geo_velocity": "geo_velocity", "R6_high_risk_wire": "high_risk_wires",
    "R7_cash_intensity": "structuring", "R8_velocity_spike": "dormant_reactivation",
}


def rule_summary(alerts: pd.DataFrame, customers: pd.DataFrame, months: int) -> pd.DataFrame:
    """Per rule: alerts, alerts per month, distinct customers, hits, precision, FP rate, recall of the target typology."""
    counts = customers[customers.suspicious_typology != ""].groupby("suspicious_typology").size()
    rows = []
    for rule_id, grp in alerts.groupby("rule_id"):
        target = RULE_TYPOLOGY[rule_id]
        hit_customers = grp.loc[grp.hit, "customer_id"].nunique()
        rows.append({"rule_id": rule_id, "target_typology": target, "alerts": len(grp), "alerts_per_month": round(len(grp) / months, 1),
                     "customers": grp.customer_id.nunique(), "hits": int(grp.hit.sum()), "precision": round(grp.hit.mean(), 3),
                     "any_suspicious_rate": round(grp.any_suspicious.mean(), 3), "fp_rate": round(1 - grp.any_suspicious.mean(), 3),
                     "typology_customers": int(counts.get(target, 0)), "customers_caught": int(hit_customers),
                     "recall": round(hit_customers / max(int(counts.get(target, 0)), 1), 3)})
    return pd.DataFrame(rows).sort_values("rule_id").reset_index(drop=True)
