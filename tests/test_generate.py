def test_schema_and_labels(generated, small_cfg):
    t, c = generated.transactions, generated.customers
    assert {"txn_id", "customer_id", "account_id", "timestamp", "txn_type", "amount", "country", "counterparty_country", "typology", "direction"} <= set(t.columns)
    assert t.txn_id.is_unique and (t.amount > 0).all()
    assert t.timestamp.is_monotonic_increasing
    assert c.suspicious_typology.ne("").sum() == sum(small_cfg["generator"]["typologies"].values())
    assert set(t.loc[t.typology != "", "typology"]) == set(small_cfg["generator"]["typologies"])


def test_structuring_rows_are_under_ctr_threshold(generated):
    s = generated.transactions[generated.transactions.typology == "structuring"]
    assert len(s) and (s.amount < 10000).all() and (s.amount >= 8000).all() and (s.txn_type == "cash_deposit").all()


def test_deterministic(small_cfg):
    from aml import generate
    a = generate.generate(small_cfg).transactions; b = generate.generate(small_cfg).transactions
    assert a.shape == b.shape and (a.amount.to_numpy() == b.amount.to_numpy()).all()
