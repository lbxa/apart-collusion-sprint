from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from veracity_harness.spending import CampaignSpending, ModelPrice, SpendingLimitReached


def price():
    return ModelPrice(
        id="fixture/model", context_length=1000, pricing={"prompt": "0.001", "completion": "0.01"}
    )


def test_shared_cap_is_durable_and_unknown_charge_keeps_hold(tmp_path):
    path = tmp_path / "spending.sqlite"
    first = CampaignSpending(path, Decimal(3))
    first.reserve("first", price(), 100)
    first.reconcile("first", None)
    other = CampaignSpending(path, Decimal(3))
    with pytest.raises(SpendingLimitReached):
        other.reserve("second", price(), 100)
    first.reconcile("first", Decimal("0.25"))
    other.reserve("second", price(), 100)
    assert Decimal(other.snapshot()["accounted_usd"]) == Decimal("2.25")
    assert other.snapshot()["unresolved_requests"] == 1
    with pytest.raises(ValueError, match="original campaign cap"):
        CampaignSpending(path, Decimal(100))


def test_concurrent_requests_cannot_oversubscribe_the_cap(tmp_path):
    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(3))

    def reserve(index):
        try:
            spending.reserve(str(index), price(), 100)
            return True
        except SpendingLimitReached:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 1
    assert spending.snapshot()["requests"] == 1


def test_ceiling_covers_price_tiers_cache_write_and_reasoning():
    model = ModelPrice(
        id="fixture/tiered",
        context_length=1000,
        pricing={
            "prompt": "0.001",
            "completion": "0.01",
            "internal_reasoning": "0.02",
            "overrides": [{"input_cache_write_1h": "0.004", "completion": "0.03"}],
        },
    )
    assert model.request_ceiling(100) == Decimal(9)


def test_catalog_drift_stops_further_spending(tmp_path):
    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(100))
    spending.reserve("first", price(), 100)
    with pytest.raises(SpendingLimitReached, match="exceeded"):
        spending.reconcile("first", Decimal("3.1"))
    with pytest.raises(SpendingLimitReached):
        spending.reserve("next", price(), 100)
