"""False-positive analysis and threshold tuning.

For each rule, sweep its `tune.param` over `tune.grid`, measure alerts / hits / precision / recall of the rule's target
typology, then choose thresholds so the team's monthly alert budget is spent on the alerts most likely to be real (see `choose`)."""
from __future__ import annotations

import pandas as pd

from aml import rules as R, scoring as S


def sweep(con, rules_cfg: dict, high_risk: list[str], customers: pd.DataFrame, months: int) -> pd.DataFrame:
    rows = []
    for rule_id, params in rules_cfg.items():
        t = params.get("tune")
        if not t:
            continue
        for value in t["grid"]:
            p = dict(params) | {t["param"]: value}
            al = R.run_rule(con, rule_id, p, high_risk)
            al = S.label_alerts(al, customers, S.RULE_TYPOLOGY) if not al.empty else al.assign(hit=[], any_suspicious=[])
            summ = S.rule_summary(al.assign(rule_id=rule_id), customers, months) if not al.empty else None
            rows.append({"rule_id": rule_id, "param": t["param"], "value": value, "alerts": len(al), "alerts_per_month": round(len(al) / months, 1),
                         "precision": float(summ.precision.iloc[0]) if summ is not None else 0.0, "recall": float(summ.recall.iloc[0]) if summ is not None else 0.0,
                         "fp_rate": float(summ.fp_rate.iloc[0]) if summ is not None else 0.0})
    return pd.DataFrame(rows)


def choose(sweep_df: pd.DataFrame, rules_cfg: dict, target_per_month: float, min_recall: float, min_precision: float = 0.15) -> tuple[dict, pd.DataFrame]:
    """Pick one grid value per rule.

    1. Start every rule at its *loosest* setting that still clears `min_precision` (max recall the rule can offer).
       A rule that never clears the precision floor is parked at its tightest setting and flagged for redesign.
    2. While total alerts/month exceed the analyst budget, tighten one step the rule whose next step costs the fewest
       hits per alert removed (i.e. the least precise marginal alerts), never dropping a rule below `min_recall`
       unless nothing else can give.
    Returns ({rule_id: {param: value}}, selection table with a reason per rule)."""
    state, reasons = {}, {}
    ladders = {}
    for rule_id, grp in sweep_df.groupby("rule_id"):
        ladder = grp.sort_values("alerts", ascending=False).reset_index(drop=True)      # loosest -> tightest
        ladders[rule_id] = ladder
        ok = ladder.index[ladder.precision >= min_precision].tolist()
        if ok:
            state[rule_id] = ok[0]; reasons[rule_id] = "loosest setting above the precision floor (max recall)"
        else:
            state[rule_id] = None; reasons[rule_id] = f"never reaches precision {min_precision:.0%} at any threshold - disabled pending redesign"
    total = lambda: sum(ladders[r].loc[i, "alerts_per_month"] for r, i in state.items() if i is not None)  # noqa: E731
    while total() > target_per_month:
        best, best_cost = None, None
        for rule_id, i in state.items():
            lad = ladders[rule_id]
            if i is None or i + 1 >= len(lad):
                continue
            cur, nxt = lad.loc[i], lad.loc[i + 1]
            if nxt.recall < min_recall and cur.recall >= min_recall:
                continue                                        # would breach the recall floor
            removed = max(cur.alerts - nxt.alerts, 0); hits_lost = max(cur.alerts * cur.precision - nxt.alerts * nxt.precision, 0)
            cost = hits_lost / max(removed, 1e-9) if removed > 0 else float("inf")
            if best is None or cost < best_cost:
                best, best_cost = rule_id, cost
        if best is None:                                        # nothing can tighten without breaking the recall floor
            for rule_id, i in state.items():
                if i is not None and i + 1 < len(ladders[rule_id]):
                    best = rule_id; break
            if best is None:
                break
            reasons[best] = "tightened past the recall floor to fit analyst capacity"
        else:
            reasons[best] = "tightened to fit analyst capacity"
        state[best] += 1
    rows, chosen = [], {}
    for rule_id, i in state.items():
        if i is None:                                            # disabled: report its tightest setting, zero alerts
            pick = ladders[rule_id].iloc[-1].copy()
            chosen[rule_id] = {"enabled": False}
            rows.append(pick.to_dict() | {"alerts": 0, "alerts_per_month": 0.0, "reason": reasons[rule_id], "enabled": False})
            continue
        pick = ladders[rule_id].loc[i]
        val = pick["value"].item() if hasattr(pick["value"], "item") else pick["value"]
        chosen[rule_id] = {str(pick["param"]): val}
        rows.append(pick.to_dict() | {"reason": reasons[rule_id], "enabled": True})
    return chosen, pd.DataFrame(rows).sort_values("rule_id").reset_index(drop=True)
