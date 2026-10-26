"""A durable, shared campaign cap, independent of provider credential selection."""

import sqlite3
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
        # Use the entire context and the highest published tier, including cache
        # writes. No provider web/search/image tools are enabled by this harness.
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

    def request_ceiling(self, completion_tokens: int) -> Decimal:
        rates = self.maximum_rates
        ceiling = (
            self.context_length * rates["prompt"]
            + completion_tokens * rates["completion"]
            + rates["request"]
        )
        if not ceiling.is_finite() or ceiling <= 0:
            raise ValueError("A finite positive text-model price is required")
        return ceiling


async def fetch_model_price(model_id: str) -> ModelPrice:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get("https://openrouter.ai/api/v1/models") as response:
            response.raise_for_status()
            catalog = await response.json()
    for entry in catalog["data"]:
        if entry["id"] == model_id:
            return ModelPrice.model_validate(entry)
    raise ValueError("Selected experiment model is absent from the current catalog")


class CampaignSpending:
    """Reserve before dispatch; replace a hold only with a known final charge.

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

    def reserve(self, request_id: str, price: ModelPrice, max_tokens: int):
        amount = price.request_ceiling(max_tokens)
        with sqlite3.connect(self.path, timeout=30) as database:
            database.execute("BEGIN IMMEDIATE")
            if database.execute("SELECT halted FROM campaign").fetchone()[0]:
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

    def reconcile(self, request_id: str, cost: Decimal | None):
        if cost is None:
            return  # Unknown is charged conservatively, never converted into zero.
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
                "UPDATE requests SET accounted_usd = ?, status = 'charged' WHERE id = ?",
                (str(cost), request_id),
            )
            if cost > Decimal(row[0]):
                database.execute("UPDATE campaign SET halted = 1")
        if cost > Decimal(row[0]):
            # Catalog drift invalidates the bound; stop rather than trust it again.
            raise SpendingLimitReached("Provider charge exceeded the catalog reservation")

    def snapshot(self) -> dict:
        with sqlite3.connect(self.path) as database:
            rows = database.execute("SELECT accounted_usd, status FROM requests").fetchall()
        return {
            "limit_usd": str(self.limit),
            "accounted_usd": str(sum((Decimal(row[0]) for row in rows), Decimal(0))),
            "charged_usd": str(
                sum((Decimal(row[0]) for row in rows if row[1] == "charged"), Decimal(0))
            ),
            "requests": len(rows),
            "unresolved_requests": sum(row[1] == "reserved" for row in rows),
        }
