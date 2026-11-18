"""A durable, shared campaign cap, independent of provider credential selection."""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import aiohttp
from pydantic import BaseModel, Field


class SpendingLimitReached(RuntimeError):
    """No new paid request may start within this campaign."""


class PriceTier(BaseModel):
    prompt: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    completion: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    input_cache_write: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    input_cache_write_1h: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    internal_reasoning: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    request: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)


class Pricing(PriceTier):
    overrides: list[PriceTier] = Field(default_factory=list)


class ModelPrice(BaseModel):
    id: str
    context_length: int = Field(gt=0)
    pricing: Pricing

    @property
    def maximum_rates(self) -> dict[str, Decimal]:
        # Use the highest published tier, including cache writes. No provider
        # web/search/image tools are enabled by this harness.
        tiers = [self.pricing, *self.pricing.overrides]
        input_rate = max(
            getattr(tier, key)
            for tier in tiers
            for key in ("prompt", "input_cache_write", "input_cache_write_1h")
        )
        output_rate = max(tier.completion for tier in tiers)
        reasoning_rate = max(tier.internal_reasoning for tier in tiers)
        request_rate = max(tier.request for tier in tiers)
        return {
            "prompt": input_rate,
            "completion": output_rate + reasoning_rate,
            "request": request_rate,
        }

    def request_ceiling(
        self, completion_tokens: int, *, input_tokens: int | None = None
    ) -> Decimal:
        if input_tokens is not None and (
            type(input_tokens) is not int or not 1 <= input_tokens <= self.context_length
        ):
            raise ValueError("Input reservation must fit the model context")
        rates = self.maximum_rates
        ceiling = (
            (self.context_length if input_tokens is None else input_tokens) * rates["prompt"]
            + completion_tokens * rates["completion"]
            + rates["request"]
        )
        if not ceiling.is_finite() or ceiling <= 0:
            raise ValueError("A finite positive text-model price is required")
        return ceiling


async def fetch_model_price(model_id: str) -> ModelPrice:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), trust_env=True
    ) as session:
        async with session.get("https://openrouter.ai/api/v1/models") as response:
            response.raise_for_status()
            catalog = await response.json()
    for entry in catalog["data"]:
        if entry["id"] == model_id:
            return ModelPrice.model_validate(entry)
    raise ValueError("Selected experiment model is absent from the current catalog")


def cloudflare_price(entry: dict) -> ModelPrice:
    """Workers AI catalog prices are USD per million tokens; cached input is cheaper."""
    properties = {item["property_id"]: item["value"] for item in entry.get("properties", [])}
    rates = {
        item["unit"]: Decimal(str(item["price"])) / 1_000_000
        for item in properties.get("price") or []
        if item.get("currency") == "USD"
    }
    if "per M input tokens" not in rates or "per M output tokens" not in rates:
        raise ValueError("Workers AI catalog entry has no per-token USD price")
    return ModelPrice(
        id=entry["name"],
        context_length=int(properties["context_window"]),
        pricing={
            "prompt": rates["per M input tokens"],
            "completion": rates["per M output tokens"],
        },
    )


class CloudflareCatalogProvider(BaseModel):
    provider: str
    pricing: dict[str, Decimal]


class CloudflareCatalogModel(BaseModel):
    model_id: str
    context_length: int = Field(gt=0)
    model_providers: list[CloudflareCatalogProvider] = Field(min_length=1)


def cloudflare_catalog_price(entry: dict) -> ModelPrice:
    """Bound unified-catalog text rates, including the 5% credit-purchase fee."""
    model = CloudflareCatalogModel.model_validate(entry)
    inputs, outputs = [], []
    input_keys = {
        prefix + key
        for prefix in ("", "short_context_", "long_context_")
        for key in (
            "input_tokens",
            "input_cached_tokens",
            "input_cache_creation_tokens",
            "input_cache_creation_1h_tokens",
        )
    }
    output_keys = {prefix + "output_tokens" for prefix in ("", "short_context_", "long_context_")}
    for provider in model.model_providers:
        for key, value in provider.pricing.items():
            if key == "long_context_threshold_tokens":
                continue
            if not value.is_finite() or value < 0:
                raise ValueError("Invalid Cloudflare catalog rate")
            if key in input_keys:
                inputs.append(value)
            elif key in output_keys:
                outputs.append(value)
            else:
                raise ValueError("Unknown Cloudflare pricing dimension")
    if not inputs or not outputs:
        raise ValueError("Cloudflare catalog requires input and output token prices")
    allowance = Decimal("1.05") / 1_000_000
    return ModelPrice(
        id=model.model_id,
        context_length=model.context_length,
        pricing={"prompt": max(inputs) * allowance, "completion": max(outputs) * allowance},
    )


async def fetch_cloudflare_catalog_price(model_id: str, account_id: str, token: str) -> ModelPrice:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/catalog/models"
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), trust_env=True
    ) as session:
        async with session.get(
            url,
            params={"search": model_id, "per_page": "100"},
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            response.raise_for_status()
            catalog = await response.json()
    if not catalog.get("success"):
        raise ValueError("Cloudflare unified catalog request failed")
    for entry in catalog["result"]:
        if entry.get("model_id") == model_id:
            return cloudflare_catalog_price(entry)
    raise ValueError("Selected model is absent from the Cloudflare unified catalog")


def cloudflare_usage_cost_bound(usage: dict | None, price: ModelPrice) -> Decimal | None:
    """Conservative token bound, not an invoice or a provider monetary receipt."""
    if usage is None:
        return None
    counts = [usage.get("input_tokens"), usage.get("output_tokens")]
    details = usage.get("input_token_details") or {}
    if not isinstance(details, dict):
        raise ValueError("Cloudflare usage requires nonnegative integer counts")
    counts.extend(details.values())
    if any(type(count) is not int or count < 0 for count in counts):
        raise ValueError("Cloudflare usage requires nonnegative integer counts")
    # Cache counts may be inclusive or separate. Adding them is conservative in
    # both cases, and every input token uses the maximum published cache/tier rate.
    return price.request_ceiling(counts[1], input_tokens=max(1, counts[0] + sum(counts[2:])))


CLOUDFLARE_NEURON_USD = Decimal("0.000011")  # Workers AI: USD 0.011 per 1,000 neurons.
# Observed billing differs from catalog token prices by up to ~1% (Nemotron, 2026-10-28);
# a changed neuron rate or a zero report falls far outside this band.
CLOUDFLARE_TOLERANCE = Decimal("0.05")


def cloudflare_charge(
    neurons: float | None, usage: dict | None, price: ModelPrice
) -> Decimal | None:
    """Billed neurons, checked against catalog token prices; None keeps the hold.

    Workers AI reports no USD cost. Uncached input and output fix a lower bound;
    cached input costs at most the uncached rate, which fixes the upper bound.
    """
    if neurons is None or usage is None:
        return None
    charge = Decimal(str(neurons)) * CLOUDFLARE_NEURON_USD
    rates = price.maximum_rates
    cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
    lower = (usage["input_tokens"] - cached) * rates["prompt"] + usage["output_tokens"] * rates[
        "completion"
    ]
    upper = lower + cached * rates["prompt"]
    if not lower * (1 - CLOUDFLARE_TOLERANCE) <= charge <= upper * (1 + CLOUDFLARE_TOLERANCE):
        raise SpendingLimitReached("Workers AI neurons contradict catalog token prices")
    return charge


async def fetch_cloudflare_price(model_id: str, account_id: str, token: str) -> ModelPrice:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search"
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), trust_env=True
    ) as session:
        async with session.get(
            url,
            params={"search": model_id, "per_page": "50"},
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            response.raise_for_status()
            catalog = await response.json()
    for entry in catalog["result"]:
        if entry["name"] == model_id:
            return cloudflare_price(entry)
    raise ValueError("Selected experiment model is absent from the Workers AI catalog")


class CampaignSpending:
    """Reserve before dispatch; distinguish receipts from conservative usage bounds.

    BEGIN IMMEDIATE serializes separate agents/processes against one ledger.
    Crashes, timeouts and missing usage retain their full hold. A ledger's cap
    cannot be increased accidentally by a later invocation.
    """

    def __init__(self, path: Path, limit: Decimal):
        if not limit.is_finite() or limit <= 0:
            raise ValueError("Campaign spending limit must be finite and positive")
        self.path = path
        self.limit = limit
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(path) as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS campaign "
                "(limit_usd TEXT NOT NULL, halted INTEGER NOT NULL)"
            )
            database.execute(
                "CREATE TABLE IF NOT EXISTS requests ("
                "id TEXT PRIMARY KEY, model TEXT NOT NULL, reserved_usd TEXT NOT NULL, "
                "accounted_usd TEXT NOT NULL, status TEXT NOT NULL)"
            )
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT limit_usd FROM campaign").fetchone()
            if row is None:
                database.execute("INSERT INTO campaign VALUES (?, 0)", (str(limit),))
            elif Decimal(row[0]) != limit:
                raise ValueError("Use the original campaign cap for this ledger")
        path.chmod(0o600)

    def increase_limit(self, new_limit: Decimal, *, authorization: str) -> "CampaignSpending":
        """Apply an explicit operator amendment without clearing charges or holds."""
        if not new_limit.is_finite() or new_limit <= self.limit or not authorization.strip():
            raise ValueError(
                "A cap increase needs a finite higher limit and explicit authorization"
            )
        with sqlite3.connect(self.path, timeout=30) as database:
            database.execute("BEGIN IMMEDIATE")
            current, halted = database.execute("SELECT limit_usd, halted FROM campaign").fetchone()
            if Decimal(current) != self.limit:
                raise ValueError("Campaign cap changed; reload the ledger")
            if halted:
                raise SpendingLimitReached("A cap increase cannot clear a pricing audit")
            database.execute(
                "CREATE TABLE IF NOT EXISTS cap_amendments ("
                "created_at TEXT NOT NULL, previous_limit_usd TEXT NOT NULL, "
                "new_limit_usd TEXT NOT NULL, authorization TEXT NOT NULL)"
            )
            database.execute(
                "INSERT INTO cap_amendments VALUES (?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(),
                    current,
                    str(new_limit),
                    authorization,
                ),
            )
            database.execute("UPDATE campaign SET limit_usd = ?", (str(new_limit),))
        return CampaignSpending(self.path, new_limit)

    def reserve(
        self,
        request_id: str,
        price: ModelPrice,
        max_tokens: int,
        *,
        input_tokens: int | None = None,
    ):
        amount = price.request_ceiling(max_tokens, input_tokens=input_tokens)
        with sqlite3.connect(self.path, timeout=30) as database:
            database.execute("BEGIN IMMEDIATE")
            current, halted = database.execute("SELECT limit_usd,halted FROM campaign").fetchone()
            if Decimal(current) != self.limit:
                raise ValueError("Campaign cap changed; reload the ledger")
            if halted:
                raise SpendingLimitReached("Campaign requires a pricing audit")
            spent = sum(
                (Decimal(row[0]) for row in database.execute("SELECT accounted_usd FROM requests")),
                Decimal(0),
            )
            if spent + amount > self.limit:
                raise SpendingLimitReached("Campaign cannot cover the next request")
            database.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, 'reserved')",
                (request_id, price.id, str(amount), str(amount)),
            )

    def reconcile(self, request_id: str, cost: Decimal | None, *, usage_bound: bool = False):
        """Replace one reservation with a monetary receipt or an explicit usage bound."""
        if cost is None:
            return  # Unknown retains its full reservation, never converted into zero.
        if not cost.is_finite() or cost < 0:
            raise ValueError("Invalid provider charge")
        with sqlite3.connect(self.path, timeout=30) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT reserved_usd, status FROM requests WHERE id = ?", (request_id,)
            ).fetchone()
            if row is None or row[1] != "reserved":
                raise ValueError("Provider charge must reconcile one outstanding request")
            database.execute(
                "UPDATE requests SET accounted_usd = ?, status = ? WHERE id = ?",
                (str(cost), "usage_bounded" if usage_bound else "charged", request_id),
            )
            if cost > Decimal(row[0]):
                database.execute("UPDATE campaign SET halted = 1")
        if cost > Decimal(row[0]):
            # Catalog drift invalidates the bound; stop rather than trust it again.
            raise SpendingLimitReached("Provider charge exceeded the catalog reservation")

    def confirmed_charges(self, request_ids: set[str]) -> Decimal:
        """Attribute confirmed charges to a run even when other runs share this ledger."""
        with sqlite3.connect(self.path) as database:
            rows = database.execute(
                "SELECT id, accounted_usd FROM requests WHERE status = 'charged'"
            ).fetchall()
        return sum(
            (Decimal(cost) for identity, cost in rows if identity in request_ids), Decimal(0)
        )

    def snapshot(self) -> dict:
        with sqlite3.connect(self.path) as database:
            rows = database.execute("SELECT accounted_usd, status FROM requests").fetchall()
        return {
            "limit_usd": str(self.limit),
            "accounted_usd": str(sum((Decimal(row[0]) for row in rows), Decimal(0))),
            "charged_usd": str(
                sum((Decimal(row[0]) for row in rows if row[1] == "charged"), Decimal(0))
            ),
            "usage_bounded_usd": str(
                sum((Decimal(row[0]) for row in rows if row[1] == "usage_bounded"), Decimal(0))
            ),
            "usage_bounded_requests": sum(row[1] == "usage_bounded" for row in rows),
            "requests": len(rows),
            "unresolved_requests": sum(row[1] == "reserved" for row in rows),
        }
