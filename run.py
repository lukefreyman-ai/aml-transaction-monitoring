#!/usr/bin/env python3
"""aml-transaction-monitoring pipeline.

  python run.py                 generate data -> run rules -> score -> label -> tune -> cases -> star schema -> results/
  python run.py --skip-tuning   faster; skip the threshold sweep
  python run.py --rows 60000 --customers 400   small run (tests / laptops)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aml import case as C, export as X, generate as G, rules as R, scoring as S, tuning as T  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--rows", type=int, default=None); ap.add_argument("--customers", type=int, default=None)
    ap.add_argument("--skip-tuning", action="store_true"); ap.add_argument("--out", default=str(ROOT / "results"))
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config))
    if a.rows: cfg["generator"]["target_rows"] = a.rows
    if a.customers:
        cfg["generator"]["n_customers"] = a.customers
        scale = a.customers / 2000
        cfg["generator"]["typologies"] = {k: max(2, int(v * scale)) for k, v in cfg["generator"]["typologies"].items()}
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    months = int(cfg["generator"]["months"]); t0 = time.time()

    # 1. data
    g = G.generate(cfg)
    (ROOT / "data").mkdir(exist_ok=True)
    g.transactions.to_parquet(ROOT / "data" / "transactions.parquet", index=False)
    g.customers.to_parquet(ROOT / "data" / "customers.parquet", index=False); g.accounts.to_parquet(ROOT / "data" / "accounts.parquet", index=False)
    inj = g.transactions[g.transactions.typology != ""]
    print(f"generated {len(g.transactions):,} transactions for {len(g.customers):,} customers over {months} months; "
          f"{len(inj):,} injected rows on {g.customers.suspicious_typology.ne('').sum()} suspicious customers ({time.time()-t0:.0f}s)")

    # 2. rules (baseline thresholds)
    con = R.connect(g.transactions, g.customers)
    alerts = R.run_all(con, cfg["rules"], cfg["high_risk_countries"])
    alerts = S.label_alerts(alerts, g.customers, S.RULE_TYPOLOGY)
    scored = S.score_alerts(alerts, g.customers, cfg["rules"], cfg["scoring"])
    summ = S.rule_summary(scored, g.customers, months)
    print(f"baseline: {len(scored):,} alerts ({len(scored)/months:.0f}/month), precision {scored.hit.mean():.2f}, "
          f"suspicious customers alerted {scored.loc[scored.any_suspicious,'customer_id'].nunique()}/{g.customers.suspicious_typology.ne('').sum()}")
    print(summ.to_string(index=False))

    # 3. tuning to analyst capacity
    tuned_cfg, sel, sweep_df = None, None, None
    if not a.skip_tuning:
        sweep_df = T.sweep(con, cfg["rules"], cfg["high_risk_countries"], g.customers, months)
        overrides, sel = T.choose(sweep_df, cfg["rules"], float(cfg["tuning"]["target_alerts_per_month"]), float(cfg["tuning"]["min_recall"]),
                                  float(cfg["tuning"].get("min_precision", 0.15)))
        tuned_cfg = {r: dict(p) | overrides.get(r, {}) for r, p in cfg["rules"].items()}
        alerts_t = S.label_alerts(R.run_all(con, cfg["rules"], cfg["high_risk_countries"], overrides), g.customers, S.RULE_TYPOLOGY)
        scored_t = S.score_alerts(alerts_t, g.customers, tuned_cfg, cfg["scoring"])
        summ_t = S.rule_summary(scored_t, g.customers, months)
        print(f"\ntuned (target {cfg['tuning']['target_alerts_per_month']}/month, min recall {cfg['tuning']['min_recall']}): "
              f"{len(scored_t):,} alerts ({len(scored_t)/months:.0f}/month), precision {scored_t.hit.mean():.2f}, "
              f"suspicious customers alerted {scored_t.loc[scored_t.any_suspicious,'customer_id'].nunique()}/{g.customers.suspicious_typology.ne('').sum()}")
        print(sel[["rule_id", "param", "value", "alerts_per_month", "precision", "recall", "reason"]].to_string(index=False))
        sweep_df.to_csv(out / "tuning_sweep.csv", index=False); sel.to_csv(out / "tuning_selection.csv", index=False)
        summ_t.to_csv(out / "rule_summary_tuned.csv", index=False)
        yaml.safe_dump({"rules": {r: {k: v for k, v in p.items() if k != "tune"} for r, p in tuned_cfg.items()}}, open(out / "tuned_thresholds.yaml", "w"), sort_keys=False)
        final_scored, final_summ = scored_t, summ_t
    else:
        final_scored, final_summ = scored, summ

    # 4. outputs
    scored.drop(columns=["txn_ids"]).to_csv(out / "alerts_baseline.csv", index=False)
    final_scored.drop(columns=["txn_ids"]).to_csv(out / "alerts.csv", index=False)
    summ.to_csv(out / "rule_summary_baseline.csv", index=False)
    cases = C.write_cases(out / "cases", final_scored, g.customers, g.accounts, g.transactions, top_n=25)
    sizes = X.export_star(out / "star_schema", g.customers, g.accounts, g.transactions, final_scored, tuned_cfg or cfg["rules"])
    prio = final_scored.priority.value_counts().to_dict()
    meta = {"rows": int(len(g.transactions)), "customers": int(len(g.customers)), "months": months, "injected_rows": int(len(inj)),
            "suspicious_customers": int(g.customers.suspicious_typology.ne("").sum()),
            "baseline": {"alerts": int(len(scored)), "per_month": round(len(scored) / months, 1), "precision": round(float(scored.hit.mean()), 3),
                         "any_suspicious_rate": round(float(scored.any_suspicious.mean()), 3),
                         "suspicious_customers_alerted": int(scored.loc[scored.any_suspicious, "customer_id"].nunique())},
            "tuned": None if sel is None else {"alerts": int(len(final_scored)), "per_month": round(len(final_scored) / months, 1),
                                               "precision": round(float(final_scored.hit.mean()), 3), "any_suspicious_rate": round(float(final_scored.any_suspicious.mean()), 3),
                                               "suspicious_customers_alerted": int(final_scored.loc[final_scored.any_suspicious, "customer_id"].nunique())},
            "priority_counts": {k: int(v) for k, v in prio.items()}, "cases_written": len(cases), "star_schema_rows": sizes, "elapsed_seconds": round(time.time() - t0, 1)}
    (out / "metrics.json").write_text(json.dumps(meta, indent=1))
    print(f"\npriority mix: {prio} · {len(cases)} case files · star schema {sizes} · {meta['elapsed_seconds']}s")


if __name__ == "__main__":
    main()
