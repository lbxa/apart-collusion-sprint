from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from veracity_harness.spending import (
    CampaignSpending,
    ModelPrice,
    SpendingLimitReached,
    cloudflare_charge,
    cloudflare_price,
)


def price():
    return ModelPrice(
        id="fixture/model", context_length=1000, pricing={"prompt": "0.001", "completion": "0.01"}
    )


@pytest.mark.parametrize("bound", [0, -1, 1001, True, 1.5])
def test_input_reservation_can_only_narrow_the_catalog_context(bound):
    with pytest.raises(ValueError, match="fit the model context"):
        price().request_ceiling(100, input_tokens=bound)


def test_checked_input_reservation_preserves_all_price_components():
    assert price().request_ceiling(100, input_tokens=100) == Decimal("1.100")
    assert price().request_ceiling(100) == Decimal("2.000")


def test_cloudflare_catalog_bound_covers_context_cache_tiers_and_credit_fee():
    from veracity_harness.spending import cloudflare_catalog_price

    entry = {
        "model_id": "openai/gpt-6.1-sol",
        "context_length": 1050000,
        "model_providers": [
            {
                "provider": "openai",
                "pricing": {
                    "short_context_input_tokens": 2,
                    "short_context_input_cached_tokens": 0.1,
                    "short_context_input_cache_creation_tokens": 2.5,
                    "short_context_output_tokens": 10,
                    "long_context_threshold_tokens": 272000,
                    "long_context_input_tokens": 4,
                    "long_context_input_cached_tokens": 0.2,
                    "long_context_input_cache_creation_tokens": 5,
                    "long_context_output_tokens": 15,
                },
            }
        ],
    }
    bounded = cloudflare_catalog_price(entry)
    assert bounded.maximum_rates["prompt"] == Decimal("0.00000525")
    assert bounded.maximum_rates["completion"] == Decimal("0.00001575")
    assert bounded.request_ceiling(100, input_tokens=1000) == Decimal("0.006825")
    entry["model_providers"][0]["pricing"]["search_request"] = 1
    with pytest.raises(ValueError, match="Unknown Cloudflare pricing dimension"):
        cloudflare_catalog_price(entry)


def test_cloudflare_usage_bound_is_distinct_from_a_confirmed_charge(tmp_path):
    from veracity_harness.spending import cloudflare_usage_cost_bound

    ledger = CampaignSpending(tmp_path / "spending.sqlite", Decimal(10))
    ledger.reserve("bounded", price(), 100)
    usage = {
        "input_tokens": 10,
        "output_tokens": 5,
        "input_token_details": {"cache_read": 2, "cache_creation": 3},
    }
    bound = cloudflare_usage_cost_bound(usage, price())
    assert bound == price().request_ceiling(5, input_tokens=15)
    ledger.reconcile("bounded", bound, usage_bound=True)
    snapshot = ledger.snapshot()
    assert Decimal(snapshot["usage_bounded_usd"]) == bound
    assert snapshot["usage_bounded_requests"] == 1
    assert snapshot["charged_usd"] == "0"
    assert snapshot["unresolved_requests"] == 0
    assert ledger.confirmed_charges({"bounded"}) == 0
    assert cloudflare_usage_cost_bound(None, price()) is None
    with pytest.raises(ValueError, match="nonnegative integer"):
        cloudflare_usage_cost_bound({"input_tokens": True, "output_tokens": 1}, price())


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


def test_charge_attribution_excludes_concurrent_studies_and_unresolved_holds(tmp_path):
    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(10))
    for identity in ("mine", "other", "unknown"):
        spending.reserve(identity, price(), 100)
    spending.reconcile("mine", Decimal("0.125"))
    spending.reconcile("other", Decimal("0.75"))
    assert spending.confirmed_charges({"mine", "unknown"}) == Decimal("0.125")
    assert spending.confirmed_charges(set()) == 0
    assert spending.snapshot()["unresolved_requests"] == 1


def test_authorised_cap_increase_retains_holds_and_invalidates_stale_writers(tmp_path):
    import sqlite3

    original = CampaignSpending(tmp_path / "spending.sqlite", Decimal(5))
    original.reserve("uncertain", price(), 100)
    increased = original.increase_limit(Decimal(100), authorization="Lucas authorised USD 100")
    assert increased.snapshot()["limit_usd"] == "100"
    assert increased.snapshot()["accounted_usd"] == "2.000"
    assert increased.snapshot()["unresolved_requests"] == 1
    with pytest.raises(ValueError, match="changed"):
        original.reserve("stale", price(), 100)
    with pytest.raises(ValueError, match="original campaign cap"):
        CampaignSpending(original.path, Decimal(5))
    with sqlite3.connect(original.path) as database:
        assert database.execute(
            "SELECT previous_limit_usd,new_limit_usd,authorization FROM cap_amendments"
        ).fetchall() == [("5", "100", "Lucas authorised USD 100")]


@pytest.mark.parametrize("new_limit", [Decimal(0), Decimal(5), Decimal(4), Decimal("NaN")])
def test_cap_amendment_requires_a_finite_increase(tmp_path, new_limit):
    ledger = CampaignSpending(tmp_path / "spending.sqlite", Decimal(5))
    with pytest.raises(ValueError):
        ledger.increase_limit(new_limit, authorization="Operator approval")
    assert ledger.snapshot()["limit_usd"] == "5"


def test_cap_amendment_cannot_clear_pricing_halt_or_omit_authorisation(tmp_path):
    ledger = CampaignSpending(tmp_path / "spending.sqlite", Decimal(5))
    with pytest.raises(ValueError):
        ledger.increase_limit(Decimal(100), authorization=" ")
    ledger.reserve("overrun", price(), 100)
    with pytest.raises(SpendingLimitReached):
        ledger.reconcile("overrun", Decimal(3))
    with pytest.raises(SpendingLimitReached, match="pricing audit"):
        ledger.increase_limit(Decimal(100), authorization="Operator increase")
    assert ledger.snapshot()["limit_usd"] == "5"


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


def test_cloudflare_catalog_entry_becomes_per_token_ceiling_rates():
    entry = {
        "name": "@cf/deepseek-ai/deepseek-v4.1-flash-1017",
        "properties": [
            {"property_id": "context_window", "value": "1048576"},
            {
                "property_id": "price",
                "value": [
                    {"unit": "per M input tokens", "price": 0.3, "currency": "USD"},
                    {"unit": "per M output tokens", "price": 1.2, "currency": "USD"},
                    {"unit": "per M cached input tokens", "price": 0.006, "currency": "USD"},
                ],
            },
        ],
    }
    price = cloudflare_price(entry)
    assert price.id == "@cf/deepseek-ai/deepseek-v4.1-flash-1017"
    assert price.context_length == 1048576
    assert price.maximum_rates["prompt"] == Decimal("0.0000003")
    assert price.maximum_rates["completion"] == Decimal("0.0000012")


def test_cloudflare_entry_without_token_prices_is_rejected():
    entry = {"name": "@cf/fixture", "properties": [{"property_id": "context_window", "value": 8}]}
    with pytest.raises(ValueError, match="price"):
        cloudflare_price(entry)


def deepseek_price():
    return ModelPrice(
        id="@cf/fixture",
        context_length=1048576,
        pricing={"prompt": "0.0000003", "completion": "0.0000012"},
    )


def test_cloudflare_neurons_are_charged_when_consistent_with_catalog_token_prices():
    # Live 2026-10-28 observations: uncached and mostly cached requests.
    usage = {"input_tokens": 298, "output_tokens": 63, "input_token_details": {"cache_read": 0}}
    charge = cloudflare_charge(15.000000953674316, usage, deepseek_price())
    assert round(charge, 9) == Decimal("0.000165000")
    cached = {
        "input_tokens": 6304,
        "output_tokens": 97,
        "input_token_details": {"cache_read": 6080},
    }
    assert round(cloudflare_charge(20.007246, cached, deepseek_price()), 6) == Decimal("0.000220")
    # Nemotron billed 0.99x its catalog token price in a live smoke.
    nemotron = ModelPrice(
        id="@cf/nemotron",
        context_length=256000,
        pricing={"prompt": "0.0000005", "completion": "0.0000015"},
    )
    observed = {"input_tokens": 4720, "output_tokens": 79, "input_token_details": {"cache_read": 0}}
    assert cloudflare_charge(223.14, observed, nemotron) is not None


def test_missing_neurons_keep_the_conservative_hold():
    usage = {"input_tokens": 298, "output_tokens": 63}
    assert cloudflare_charge(None, usage, deepseek_price()) is None
    assert cloudflare_charge(15, None, deepseek_price()) is None


@pytest.mark.parametrize("neurons", [0, 1, 40])
def test_neurons_contradicting_catalog_token_prices_stop_spending(neurons):
    usage = {"input_tokens": 298, "output_tokens": 63, "input_token_details": {"cache_read": 0}}
    with pytest.raises(SpendingLimitReached, match="contradict"):
        cloudflare_charge(neurons, usage, deepseek_price())
