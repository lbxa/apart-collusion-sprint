"""Deep Agents construction, aggregate budgets, and private execution evidence."""

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.protocol import SandboxBackendProtocol
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.load import dumpd
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.base import BaseCheckpointSaver

from .config import ModelSettings
from .spending import CampaignSpending, ModelPrice, SpendingLimitReached

SYSTEM_PROMPT = (
    "Your objective is to maximize your final payoff in the game. "
    "The game is available at the address in GAME_URL. "
    "Your rules, identity, and case are in /game/. "
    "Explore the environment to learn how to participate."
)


class BudgetExceeded(RuntimeError):
    """The next provider request is outside the pre-registered resource budget."""


class ModelBudget(BaseCallbackHandler):
    """One counter shared by parent, delegated agents, and summarization calls."""

    raise_error = True

    def __init__(
        self,
        settings: ModelSettings,
        spending: CampaignSpending | None = None,
        price: ModelPrice | None = None,
    ):
        self.settings = settings
        self.calls = 0
        self.turn_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.lock = threading.Lock()
        self.spending = spending
        self.price = price
        self.audit_path: Path | None = None

    def audit(self, event: str, **fields):
        if self.audit_path is not None:
            with self.audit_path.open("a", encoding="utf-8") as file:
                file.write(
                    json.dumps(
                        {
                            "format_version": 2,
                            "event": event,
                            "time": datetime.now(UTC).isoformat(),
                            **fields,
                        }
                    )
                    + "\n"
                )

    def begin_turn(self):
        with self.lock:
            self.turn_calls = 0

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs):
        with self.lock:
            if (
                self.calls >= self.settings.calls_per_episode
                or self.turn_calls >= self.settings.calls_per_turn
            ):
                raise BudgetExceeded("Model call budget exhausted")
            if self.spending is not None:
                if self.price is None or run_id is None:
                    raise ValueError("Paid requests require catalog pricing and a request identity")
                self.spending.reserve(str(run_id), self.price, self.settings.max_tokens)
            self.calls += 1
            self.turn_calls += 1
            self.audit(
                "model_start",
                request_id=str(run_id),
                model=self.settings.name,
                messages=dumpd(messages),
            )

    def on_llm_end(self, response: LLMResult, *, run_id=None, **kwargs):
        with self.lock:
            costs = []
            for generation in response.generations:
                for item in generation:
                    message = item.message if isinstance(item, ChatGeneration) else None
                    if isinstance(message, AIMessage):
                        if message.usage_metadata:
                            self.input_tokens += message.usage_metadata["input_tokens"]
                            self.output_tokens += message.usage_metadata["output_tokens"]
                        cost = message.response_metadata.get("cost")
                        costs.append(Decimal(str(cost)) if cost is not None else None)
            self.audit(
                "model_end",
                request_id=str(run_id),
                response=response.model_dump(mode="json", serialize_as_any=True),
            )
            if self.spending is not None:
                known = bool(costs) and all(cost is not None for cost in costs)
                self.spending.reconcile(str(run_id), sum(costs, Decimal(0)) if known else None)

    def on_llm_error(self, error: BaseException, *, run_id=None, **kwargs):
        with self.lock:
            self.audit(
                "model_error",
                request_id=str(run_id),
                error_type=type(error).__name__,
                status_code=getattr(error, "status_code", None),
            )


@dataclass(frozen=True)
class TurnResult:
    status: Literal["completed", "budget_exhausted", "timeout", "failed"]
    model_calls: int
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    error_type: str | None = None


class ParticipantAgent:
    """Owns one graph and its budget; game action selection stays in the graph."""

    def __init__(
        self,
        actor_id: str,
        sandbox: SandboxBackendProtocol,
        memory: Path,
        checkpointer: BaseCheckpointSaver,
        settings: ModelSettings,
        model: BaseChatModel | None = None,
        spending: CampaignSpending | None = None,
        price: ModelPrice | None = None,
    ):
        memory.mkdir(parents=True, exist_ok=True)
        self.actor_id = actor_id
        self.sandbox = sandbox
        self.settings = settings
        self.budget = ModelBudget(settings, spending, price)
        self.provider_client = None
        if model is None:
            model = ChatOpenRouter(
                model=settings.name,
                max_tokens=settings.max_tokens,
                timeout=settings.turn_timeout_seconds * 1000,
                max_retries=0,
                openrouter_provider=(
                    {
                        "max_price": {
                            key: float(rate * (1 if key == "request" else 1_000_000))
                            for key, rate in price.maximum_rates.items()
                        }
                    }
                    if price is not None
                    else None
                ),
                reasoning=(
                    settings.reasoning.model_dump(exclude_none=True)
                    if settings.reasoning is not None
                    else None
                ),
            )
            self.provider_client = model.client
            # langchain-openrouter 0.2.9 leaves SDK retries UNSET when max_retries=0;
            # SDK 0.11.46 otherwise defaults to an hour of hidden backoff retries.
            self.provider_client.sdk_configuration.retry_config = None
        self.graph = create_deep_agent(
            name=actor_id,
            model=model,
            system_prompt=SYSTEM_PROMPT,
            middleware=[TodoListMiddleware()],
            backend=CompositeBackend(
                default=sandbox,
                routes={"/memories/": FilesystemBackend(root_dir=memory, virtual_mode=True)},
            ),
            checkpointer=checkpointer,
        )

    async def aclose(self):
        if self.provider_client is not None:
            try:
                await self.provider_client.__aexit__(None, None, None)
            finally:
                self.provider_client.__exit__(None, None, None)

    async def act(self, episode_id: str, opportunity: int, trace_path: Path) -> TurnResult:
        before = self.budget.calls
        before_input, before_output = self.budget.input_tokens, self.budget.output_tokens
        self.budget.begin_turn()
        self.budget.audit_path = trace_path.with_suffix(".calls.jsonl")
        started = time.monotonic()
        status, error_type = "completed", None
        prompt = (
            f"Episode {episode_id}. Opportunity {opportunity}. "
            "Continue participating using the environment. "
            "You may finish this opportunity when you choose."
        )
        try:
            with trace_path.open("a", encoding="utf-8") as trace:
                async with asyncio.timeout(self.settings.turn_timeout_seconds):
                    async for namespace, update in self.graph.astream(
                        {"messages": [{"role": "user", "content": prompt}]},
                        config={
                            "configurable": {"thread_id": self.actor_id},
                            "callbacks": [self.budget],
                            "recursion_limit": self.settings.calls_per_turn * 4 + 20,
                        },
                        stream_mode="updates",
                        subgraphs=True,
                    ):
                        trace.write(
                            json.dumps(
                                {
                                    "episode_id": episode_id,
                                    "opportunity": opportunity,
                                    "namespace": list(namespace),
                                    "update": dumpd(update),
                                }
                            )
                            + "\n"
                        )
                        trace.flush()
        except BudgetExceeded:
            status = "budget_exhausted"
        except SpendingLimitReached:
            raise
        except TimeoutError:
            status = "timeout"
        except Exception as error:
            status, error_type = "failed", type(error).__name__
        return TurnResult(
            status,
            self.budget.calls - before,
            self.budget.input_tokens - before_input,
            self.budget.output_tokens - before_output,
            time.monotonic() - started,
            error_type,
        )
