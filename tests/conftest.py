import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def small_cfg():
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    cfg["generator"].update({"n_customers": 300, "target_rows": 40000, "seed": 3,
                             "typologies": {"structuring": 6, "rapid_movement": 5, "round_dollar": 5, "dormant_reactivation": 5, "geo_velocity": 5, "high_risk_wires": 4}})
    return cfg


@pytest.fixture(scope="session")
def generated(small_cfg):
    from aml import generate
    return generate.generate(small_cfg)
