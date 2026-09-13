"""Synthetic retail-bank transaction generator with injected AML typologies.

Everything is labelled: each transaction carries `typology` ('' for baseline) and each customer carries
`suspicious_typology`, so rule hit rates and false-positive rates can be measured exactly.

Typologies (injected on a subset of customers):
  structuring            - several cash deposits just under $10,000 within a week, split across branches
  rapid_movement         - a large inbound wire/ACH followed within 0-2 days by outbound wires of ~90-100 %
  round_dollar           - repeated exact round-thousand wires/ACH (5k, 10k, 20k ...)
  dormant_reactivation   - >= 90 days of silence, then a burst of large transactions in a week
  geo_velocity           - card / ATM activity in two countries within a few hours (impossible travel)
  high_risk_wires        - outbound wires to high-risk jurisdictions
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TXN_TYPES = ["cash_deposit", "cash_withdrawal", "wire_in", "wire_out", "ach_in", "ach_out", "card_purchase", "atm_withdrawal", "check_deposit"]
TYPE_P = np.array([0.08, 0.07, 0.04, 0.04, 0.12, 0.12, 0.38, 0.08, 0.07])
TYPE_LOGNORM = {  # (mu, sigma) of log-amount by type
    "cash_deposit": (6.2, 0.9), "cash_withdrawal": (5.3, 0.8), "wire_in": (8.2, 1.0), "wire_out": (8.0, 1.0),
    "ach_in": (7.0, 0.9), "ach_out": (6.3, 0.9), "card_purchase": (3.6, 1.0), "atm_withdrawal": (5.0, 0.5), "check_deposit": (6.8, 0.9),
}
INBOUND = {"cash_deposit", "wire_in", "ach_in", "check_deposit"}
COUNTRIES = ["US"] * 90 + ["CA", "MX", "GB", "DE", "FR", "ES", "IT", "NL", "BR", "IN"]
OCCUPATIONS = ["salaried", "self-employed", "student", "retired", "small business", "consultant", "restaurant owner", "real estate", "cash-intensive retail"]


@dataclass
class Generated:
    customers: pd.DataFrame
    accounts: pd.DataFrame
    transactions: pd.DataFrame


def _customers(rng: np.random.Generator, n: int, start: pd.Timestamp) -> pd.DataFrame:
    ctype = rng.choice(["individual", "business"], n, p=[0.8, 0.2])
    risk = rng.choice(["low", "medium", "high"], n, p=[0.7, 0.22, 0.08])
    expected = np.where(ctype == "business", rng.lognormal(9.3, 0.7, n), rng.lognormal(7.9, 0.6, n)).round(-2)
    return pd.DataFrame({
        "customer_id": [f"C{i:05d}" for i in range(n)],
        "customer_name": [f"Customer {i:05d}" for i in range(n)],
        "customer_type": ctype, "risk_rating": risk,
        "occupation": rng.choice(OCCUPATIONS, n),
        "country": rng.choice(COUNTRIES, n),
        "onboarding_date": start - pd.to_timedelta(rng.integers(120, 3000, n), unit="D"),
        "expected_monthly_volume": expected,
        "suspicious_typology": "",
    })


def _accounts(rng: np.random.Generator, customers: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cid, ctype in zip(customers.customer_id, customers.customer_type):
        k = 2 if (ctype == "business" or rng.random() < 0.25) else 1
        for j in range(k):
            rows.append({"account_id": f"A{cid[1:]}{j}", "customer_id": cid, "account_type": rng.choice(["checking", "savings", "business"]),
                         "branch_id": f"B{rng.integers(1, 40):03d}"})
    return pd.DataFrame(rows)


def _baseline(rng: np.random.Generator, customers: pd.DataFrame, accounts: pd.DataFrame, start: pd.Timestamp, months: int, target_rows: int) -> pd.DataFrame:
    days = months * 30
    per_month = np.where(customers.customer_type == "business", rng.gamma(4, 9, len(customers)), rng.gamma(3, 6, len(customers)))
    scale = target_rows / (per_month.sum() * months)
    counts = rng.poisson(per_month * months * scale)
    acct_by_cust = accounts.groupby("customer_id")["account_id"].apply(list).to_dict()
    branch_by_acct = accounts.set_index("account_id")["branch_id"].to_dict()
    home = customers.set_index("customer_id")["country"].to_dict()
    parts = []
    for cid, n in zip(customers.customer_id, counts):
        if n == 0:
            continue
        types = rng.choice(TXN_TYPES, n, p=TYPE_P)
        mu = np.array([TYPE_LOGNORM[t][0] for t in types]); sd = np.array([TYPE_LOGNORM[t][1] for t in types])
        amt = np.round(np.exp(rng.normal(mu, sd)), 2)
        accts = rng.choice(acct_by_cust[cid], n)
        secs = rng.uniform(0, days * 86400, n)
        parts.append(pd.DataFrame({
            "customer_id": cid, "account_id": accts, "txn_type": types, "amount": amt,
            "timestamp": start + pd.to_timedelta(secs, unit="s"),
            "country": np.where(rng.random(n) < 0.985, home[cid], rng.choice(COUNTRIES, n)),
            "counterparty_id": [f"X{rng.integers(0, 60000):05d}" for _ in range(n)],
            "counterparty_country": np.where(rng.random(n) < 0.95, "US", rng.choice(COUNTRIES, n)),
            "branch_id": [branch_by_acct[a] for a in accts], "channel": np.where(np.isin(types, ["cash_deposit", "cash_withdrawal", "check_deposit"]), "branch",
                                                                                  np.where(np.isin(types, ["card_purchase", "atm_withdrawal"]), "card", "online")),
            "typology": "",
        }))
    return pd.concat(parts, ignore_index=True)


def _inject(rng: np.random.Generator, customers: pd.DataFrame, accounts: pd.DataFrame, base: pd.DataFrame, start: pd.Timestamp,
            months: int, plan: dict[str, int], high_risk: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = months * 30
    acct_by_cust = accounts.groupby("customer_id")["account_id"].apply(list).to_dict()
    cust = customers.copy().set_index("customer_id")
    pool = list(customers.customer_id)
    rng.shuffle(pool)
    injected, drop_idx = [], []
    for typology, k in plan.items():
        chosen, pool = pool[:k], pool[k:]
        cust.loc[chosen, "suspicious_typology"] = typology
        for cid in chosen:
            accts = acct_by_cust[cid]
            t0 = start + pd.Timedelta(days=int(rng.integers(30, days - 30)))
            if typology == "dormant_reactivation":          # the quiet period must sit inside the observed history
                t0 = start + pd.Timedelta(days=int(rng.integers(200, days - 20)))
            rows: list[dict] = []
            if typology == "structuring":
                n = int(rng.integers(3, 7))
                total = 0.0
                for j in range(n):
                    a = float(np.round(rng.uniform(8200, 9900), 0)); total += a
                    rows.append(dict(account_id=rng.choice(accts), txn_type="cash_deposit", amount=a, channel="branch",
                                     timestamp=t0 + pd.Timedelta(hours=float(rng.uniform(0, 24 * 5))), branch_id=f"B{rng.integers(1, 40):03d}",
                                     counterparty_id="CASH", counterparty_country="US", country="US"))
            elif typology == "rapid_movement":
                for rep in range(int(rng.integers(1, 3))):
                    ti = t0 + pd.Timedelta(days=rep * 20)
                    amt = float(np.round(rng.uniform(25000, 150000), 2))
                    rows.append(dict(account_id=accts[0], txn_type="wire_in", amount=amt, channel="online", timestamp=ti,
                                     branch_id="B000", counterparty_id=f"X{rng.integers(0, 60000):05d}", counterparty_country=rng.choice(["US", "GB", "AE", "HK"]), country="US"))
                    remaining = amt * rng.uniform(0.6, 1.0)      # some cases only pass through 60-80 % (evade a strict share rule)
                    n_out = int(rng.integers(1, 4))
                    for j in range(n_out):
                        share = remaining if j == n_out - 1 else remaining * rng.uniform(0.3, 0.7)
                        remaining -= share
                        rows.append(dict(account_id=accts[0], txn_type="wire_out", amount=float(np.round(share, 2)), channel="online",
                                         timestamp=ti + pd.Timedelta(hours=float(rng.uniform(2, 48))), branch_id="B000",
                                         counterparty_id=f"X{rng.integers(0, 60000):05d}", counterparty_country=rng.choice(["US", "GB", "AE", "HK", "PA"]), country="US"))
                        if remaining <= 0:
                            break
            elif typology == "round_dollar":
                for j in range(int(rng.integers(5, 10))):
                    rows.append(dict(account_id=rng.choice(accts), txn_type=rng.choice(["wire_out", "ach_out", "wire_in"]),
                                     amount=float(rng.choice([5000, 10000, 15000, 20000, 25000, 50000])), channel="online",
                                     timestamp=t0 + pd.Timedelta(days=float(rng.uniform(0, 28))), branch_id="B000",
                                     counterparty_id=f"X{rng.integers(0, 300):05d}", counterparty_country="US", country="US"))
            elif typology == "dormant_reactivation":
                quiet_from, quiet_to = t0 - pd.Timedelta(days=int(rng.integers(100, 160))), t0
                mask = (base.customer_id == cid) & (base.timestamp >= quiet_from) & (base.timestamp < quiet_to)
                drop_idx.extend(base.index[mask].tolist())
                for j in range(int(rng.integers(4, 9))):
                    rows.append(dict(account_id=rng.choice(accts), txn_type=rng.choice(["wire_in", "wire_out", "cash_deposit", "ach_out"]),
                                     amount=float(np.round(rng.uniform(4000, 30000), 2)), channel="online",
                                     timestamp=t0 + pd.Timedelta(hours=float(rng.uniform(0, 24 * 6))), branch_id="B000",
                                     counterparty_id=f"X{rng.integers(0, 60000):05d}", counterparty_country="US", country="US"))
            elif typology == "geo_velocity":
                for rep in range(int(rng.integers(2, 5))):
                    ti = t0 + pd.Timedelta(days=rep * 9 + float(rng.uniform(0, 3)))
                    c1, c2 = rng.choice(["US", "GB", "FR", "ES", "MX", "BR"], 2, replace=False)
                    rows.append(dict(account_id=accts[0], txn_type="card_purchase", amount=float(np.round(rng.uniform(120, 900), 2)), channel="card",
                                     timestamp=ti, branch_id="B000", counterparty_id=f"M{rng.integers(0, 9000):04d}", counterparty_country=c1, country=c1))
                    rows.append(dict(account_id=accts[0], txn_type=rng.choice(["card_purchase", "atm_withdrawal"]), amount=float(np.round(rng.uniform(150, 1200), 2)),
                                     channel="card", timestamp=ti + pd.Timedelta(hours=float(rng.uniform(0.5, 4))), branch_id="B000",
                                     counterparty_id=f"M{rng.integers(0, 9000):04d}", counterparty_country=c2, country=c2))
            elif typology == "high_risk_wires":
                for j in range(int(rng.integers(2, 5))):
                    rows.append(dict(account_id=accts[0], txn_type="wire_out", amount=float(np.round(rng.uniform(6000, 60000), 2)), channel="online",
                                     timestamp=t0 + pd.Timedelta(days=float(rng.uniform(0, 60))), branch_id="B000",
                                     counterparty_id=f"X{rng.integers(0, 60000):05d}", counterparty_country=str(rng.choice(high_risk)), country="US"))
            for r in rows:
                r.update(customer_id=cid, typology=typology)
            injected.extend(rows)
    base = base.drop(index=drop_idx)
    inj = pd.DataFrame(injected)
    txns = pd.concat([base, inj[base.columns]], ignore_index=True).sort_values("timestamp", kind="stable").reset_index(drop=True)
    return cust.reset_index(), txns


def generate(cfg: dict) -> Generated:
    g = cfg["generator"]
    rng = np.random.default_rng(int(g.get("seed", 7)))
    start = pd.Timestamp(g["start_date"])
    customers = _customers(rng, int(g["n_customers"]), start)
    accounts = _accounts(rng, customers)
    base = _baseline(rng, customers, accounts, start, int(g["months"]), int(g["target_rows"]))
    customers, txns = _inject(rng, customers, accounts, base, start, int(g["months"]), dict(g["typologies"]), list(cfg["high_risk_countries"]))
    txns.insert(0, "txn_id", [f"T{i:07d}" for i in range(len(txns))])
    txns["direction"] = np.where(txns.txn_type.isin(list(INBOUND)), "in", "out")
    txns["is_cash"] = txns.txn_type.isin(["cash_deposit", "cash_withdrawal"])
    txns["amount"] = txns["amount"].astype(float)
    return Generated(customers, accounts, txns)
