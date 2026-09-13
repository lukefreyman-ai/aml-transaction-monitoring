import pandas as pd

from aml import rules as R, scoring as S, tuning as T


def test_every_rule_runs_and_returns_schema(generated, small_cfg):
    con = R.connect(generated.transactions, generated.customers)
    alerts = R.run_all(con, small_cfg["rules"], small_cfg["high_risk_countries"])
    assert list(alerts.columns) == ["alert_id"] + R.ALERT_COLUMNS
    assert alerts.rule_id.nunique() == len(small_cfg["rules"])


def test_rules_catch_injected_typologies(generated, small_cfg):
    con = R.connect(generated.transactions, generated.customers)
    alerts = S.label_alerts(R.run_all(con, small_cfg["rules"], small_cfg["high_risk_countries"]), generated.customers, S.RULE_TYPOLOGY)
    summ = S.rule_summary(alerts, generated.customers, small_cfg["generator"]["months"])
    core = summ[summ.rule_id.isin(["R1_structuring", "R5_geo_velocity", "R6_high_risk_wire"])]
    assert (core.recall >= 0.8).all(), core[["rule_id", "recall"]]
    assert (core.precision > 0.3).all(), core[["rule_id", "precision"]]
    r2 = summ[summ.rule_id == "R2_rapid_movement"].iloc[0]       # some injected cases pass through < 80 % on purpose
    assert r2.recall >= 0.4 and r2.precision > 0.3


def test_scoring_and_priority(generated, small_cfg):
    con = R.connect(generated.transactions, generated.customers)
    alerts = S.label_alerts(R.run_all(con, small_cfg["rules"], small_cfg["high_risk_countries"]), generated.customers, S.RULE_TYPOLOGY)
    scored = S.score_alerts(alerts, small_cfg["rules"], small_cfg["scoring"]) if False else S.score_alerts(alerts, generated.customers, small_cfg["rules"], small_cfg["scoring"])
    assert set(scored.priority) <= {"high", "medium", "low"} and scored.score.is_monotonic_decreasing
    assert (scored.score >= 0).all()


def test_tuning_reduces_volume_within_recall(generated, small_cfg):
    con = R.connect(generated.transactions, generated.customers)
    sw = T.sweep(con, small_cfg["rules"], small_cfg["high_risk_countries"], generated.customers, small_cfg["generator"]["months"])
    assert len(sw) and {"rule_id", "value", "alerts", "precision", "recall"} <= set(sw.columns)
    chosen, sel = T.choose(sw, small_cfg["rules"], target_per_month=3, min_recall=0.6)
    assert set(chosen) <= set(small_cfg["rules"]) and len(sel) == sw.rule_id.nunique()
    loose, _ = T.choose(sw, small_cfg["rules"], target_per_month=1e9, min_recall=0.6)
    assert sel.alerts_per_month.sum() <= sum(sw[(sw.rule_id == r) & (sw.value == v[list(v)[0]])].alerts_per_month.iloc[0] for r, v in loose.items())


def test_rule_sql_has_no_unfilled_placeholders(small_cfg):
    for rule_id, p in small_cfg["rules"].items():
        sql = R.render_sql(rule_id, p, small_cfg["high_risk_countries"])
        assert "{" not in sql and "}" not in sql, rule_id
