from pathlib import Path

from aml import case as C, export as X, rules as R, scoring as S


def test_case_and_star_schema(tmp_path: Path, generated, small_cfg):
    con = R.connect(generated.transactions, generated.customers)
    alerts = S.label_alerts(R.run_all(con, small_cfg["rules"], small_cfg["high_risk_countries"]), generated.customers, S.RULE_TYPOLOGY)
    scored = S.score_alerts(alerts, generated.customers, small_cfg["rules"], small_cfg["scoring"])
    paths = C.write_cases(tmp_path / "cases", scored, generated.customers, generated.accounts, generated.transactions, top_n=3)
    assert len(paths) == 3 and "Recommendation" in paths[0].read_text() and "$" in paths[0].read_text()
    sizes = X.export_star(tmp_path / "star", generated.customers, generated.accounts, generated.transactions, scored, small_cfg["rules"])
    assert sizes["fact_transaction"] == len(generated.transactions) and sizes["fact_alert"] == len(scored)
    assert (tmp_path / "star" / "dim_date.csv").exists() and sizes["bridge_alert_txn"] >= len(scored)
