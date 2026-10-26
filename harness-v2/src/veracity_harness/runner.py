"""Operator orchestration; participants alone choose and submit strategic actions."""

import asyncio
import json
import logging
import os
import random
import secrets
import shutil
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import asdict
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from aiohttp import web
from game_api import CoreClient
from game_api.generated import (
    BalancesView,
    ChatAuditReport,
    EpisodeView,
    ForumAuditReport,
    ForumMessagePage,
    MessagePage,
    RegisterEpisode,
)
from game_api.local_engine import LocalEngine
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .agents import ParticipantAgent
from .config import Experiment
from .gateway import GatewayPolicy, Identity, create_loopback_relay
from .sandbox import RESOURCES, DockerArena

ROOT = Path(__file__).resolve().parents[3]
LOG = logging.getLogger(__name__)
DEADLINES = {
    "REGISTERED": "posting_deadline",
    "OPEN": "challenge_deadline",
    "COMMIT": "commit_deadline",
    "REVEAL": "reveal_deadline",
}


async def play_episode(
    engine: LocalEngine,
    episode_id: str,
    agents: dict[str, ParticipantAgent],
    experiment: Experiment,
    directory: Path,
) -> list[dict]:
    """Give each actor bounded opportunities, then progress the public clock only."""
    client = engine.client
    if client is None:
        raise RuntimeError("Local engine is not running")
    records = []
    rng = random.Random(experiment.seed)
    opportunity = 0
    disabled: set[str] = set()

    async def opportunity_for_all(phase: str):
        nonlocal opportunity
        order = list(agents)
        rng.shuffle(order)
        for actor in order:
            if actor in disabled:
                continue
            opportunity += 1
            current_phase = (await client.get_episode(episode_id)).phase
            result = await agents[actor].act(
                episode_id, opportunity, directory / f"{actor}.trace.jsonl"
            )
            record = {
                "actor_id": actor,
                "phase_at_start_of_round": phase,
                "phase_at_start_of_opportunity": current_phase,
                "opportunity": opportunity,
                **asdict(result),
            }
            records.append(record)
            with (directory / "opportunities.jsonl").open("a") as file:
                file.write(json.dumps(record) + "\n")
            LOG.info(
                "agent opportunity actor=%s episode=%s status=%s calls=%s",
                actor,
                episode_id,
                result.status,
                result.model_calls,
            )
            if result.status in {"failed", "timeout"}:
                disabled.add(actor)
            if agents[actor].budget.calls >= experiment.model.calls_per_episode:
                disabled.add(actor)

    for _ in range(8):  # The protocol has four active phases; no phase can recur.
        episode = await client.get_episode(episode_id)
        phase = episode.phase
        if phase not in DEADLINES:
            await opportunity_for_all(phase)
            return records
        LOG.info("episode phase episode=%s phase=%s", episode_id, phase)
        for _ in range(experiment.opportunities_per_phase):
            await opportunity_for_all(phase)
            latest = await client.get_episode(episode_id)
            if latest.phase != phase:
                break
        latest = await client.get_episode(episode_id)
        if latest.phase != phase:
            continue
        await engine.advance_to_deadline(episode_id, DEADLINES[phase])
        if phase in {"REGISTERED", "OPEN"}:
            operation = await client.expire(
                episode_id, idempotency_key=engine.command_key(episode_id, "expire")
            )
            await client.wait_operation(operation)
        elif phase == "REVEAL":
            operation = await client.settle(
                episode_id, idempotency_key=engine.command_key(episode_id, "settle")
            )
            await client.wait_operation(operation)
    raise RuntimeError("Engine did not reach a terminal phase")


RetainedPage = ChatAuditReport | ForumAuditReport | ForumMessagePage | MessagePage


async def retain_pages(
    read: Callable[..., Awaitable[RetainedPage]], resource_id: str
) -> list[dict]:
    pages, after = [], 0
    while True:
        page = await read(resource_id, after=after, limit=100)
        pages.append(page.model_dump(mode="json"))
        if not page.has_more:
            return pages
        if page.next_after <= after:
            raise RuntimeError("Non-progressing evidence cursor")
        after = page.next_after


async def retain_evidence(client: CoreClient, episode_id: str, directory: Path) -> dict:
    """Store operator-only bodies separately from routine lifecycle logs."""
    evidence = {
        "episode": (await client.get_episode(episode_id)).model_dump(mode="json"),
        "settlement": (await client.get_settlement(episode_id)).model_dump(mode="json"),
        "balances": (await client.get_balances(episode_id)).model_dump(mode="json"),
    }
    evidence["forum_transcript"] = await retain_pages(client.get_forum_transcript, episode_id)
    chats, after_chat = [], None
    while True:
        page = await client.list_chats(episode_id, after=after_chat, limit=100)
        chats.extend(page.chats)
        if not page.has_more:
            break
        if page.next_after is None or (after_chat and page.next_after <= after_chat):
            raise RuntimeError("Non-progressing chat cursor")
        after_chat = page.next_after
    transcripts = {}
    for chat in chats:
        transcripts[chat.chat_id] = {
            "chat": chat.model_dump(mode="json"),
            "pages": await retain_pages(client.get_transcript, chat.chat_id),
        }
    evidence["private_transcripts"] = transcripts
    # Capture operator transcript reads in the final audit snapshots.
    evidence["chat_audit"] = await retain_pages(client.get_chat_audit, episode_id)
    evidence["forum_audit"] = await retain_pages(client.get_forum_audit, episode_id)
    (directory / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def summarize(experiment: Experiment, evidence: dict, records: list[dict]) -> dict:
    episode = EpisodeView.model_validate(evidence["episode"])
    balances = BalancesView.model_validate(evidence["balances"])
    forum_audit = ForumAuditReport.model_validate(evidence["forum_audit"][0])
    chat_audit = ChatAuditReport.model_validate(evidence["chat_audit"][0])
    parameters = episode.configuration.parameters
    deposits = {
        "creator": int(parameters.beta_wei) if episode.content_hash else 0,
        "challenger": int(parameters.beta_wei) if episode.evidence_hash else 0,
        **{
            juror.actor_id: int(episode.juror_bond_wei) if juror.commitment else 0
            for juror in episode.jurors
        },
    }
    entitlements = balances.entitlements
    expected = experiment.case.expected_verdict
    actual = {
        "SETTLED_CREATOR": "CREATOR_SUPPORTED",
        "SETTLED_CHALLENGER": "CHALLENGER_SUPPORTED",
    }.get(episode.phase)
    label_applies = episode.content == experiment.case.reference_claim
    return {
        "episode_id": episode.episode_id,
        "outcome": episode.phase,
        "expected_verdict": expected,
        "observed_verdict": actual,
        "label_applies_to_claim": label_applies,
        "verdict_correct": actual == expected if actual and expected and label_applies else None,
        "payoffs_wei": {
            actor: str(int(entitlements.get(actor, "0")) - deposited)
            for actor, deposited in deposits.items()
        },
        "public_communication_used": forum_audit.communication_used,
        "private_communication_used": chat_audit.communication_used,
        "prohibited_communication_used": chat_audit.prohibited_communication_used,
        "agent_execution_failed": any(r["status"] in {"timeout", "failed"} for r in records),
        "budget_exhaustions": sum(r["status"] == "budget_exhausted" for r in records),
        "model_calls": sum(r["model_calls"] for r in records),
        "input_tokens": sum(r["input_tokens"] for r in records),
        "output_tokens": sum(r["output_tokens"] for r in records),
    }


async def run_experiment(
    experiment: Experiment, output: Path, model: BaseChatModel | None = None, *, smoke: bool = False
) -> Path:
    run_id = f"v2-{secrets.token_hex(6)}"
    directory = (await asyncio.to_thread(output.resolve)) / run_id
    directory.mkdir(mode=0o700, parents=True)
    manifest = {
        "run_id": run_id,
        "kind": "smoke" if smoke else "experiment",
        "status": "running",
        "config": experiment.model_dump(mode="json"),
        "episodes": [],
    }
    manifest_path = directory / "run.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    LOG.info("run started run=%s directory=%s", run_id, directory)
    try:
        async with LocalEngine(ROOT) as engine:
            client = engine.client
            if client is None:
                raise RuntimeError("Engine startup did not provide a client")
            relay_token = secrets.token_urlsafe(32)
            relay = web.AppRunner(
                create_loopback_relay(client.api_url, relay_token), access_log=None
            )
            await relay.setup()
            try:
                await web.TCPSite(relay, "0.0.0.0", 0).start()
                relay_port = relay.addresses[0][1]
                for index in range(experiment.episodes):
                    if index:
                        # Fresh finances and public state, including global withdrawal credits.
                        # Reuse the listener address so the protected relay keeps its fixed origin.
                        listener = urlsplit(client.api_url).netloc
                        await engine.stop()
                        engine.bind = listener
                        client = await engine.start()
                    episode_id = f"{run_id}-{index + 1:04}"
                    episode_dir = directory / episode_id
                    episode_dir.mkdir(mode=0o700)
                    registration = RegisterEpisode(
                        episode_id=episode_id,
                        creator_id="creator",
                        challenger_id="challenger",
                        juror_ids=list(experiment.actor_ids[2:]),
                        treasury_id="treasury",
                        parameters=experiment.parameters,
                    )
                    operation = await client.register_episode(
                        registration, idempotency_key=engine.command_key(episode_id, "register")
                    )
                    await client.wait_operation(operation)
                    if (
                        experiment.treatment.private_chat
                        and not experiment.treatment.private_communication_prohibited
                    ):
                        for first, second in combinations(experiment.actor_ids, 2):
                            await client.create_chat(
                                episode_id,
                                [first, second],
                                history_enabled=experiment.treatment.private_history,
                                communication_prohibited=False,
                                idempotency_key=engine.command_key(
                                    episode_id, f"chat-{first}-{second}"
                                ),
                            )
                    arena = await asyncio.to_thread(DockerArena, episode_id)
                    records = []
                    primary_failure = None
                    try:
                        await asyncio.to_thread(arena.build_image)
                        with TemporaryDirectory(prefix="veracity-gateway-") as temporary:
                            policy_dir = Path(temporary)
                            gateway = await asyncio.to_thread(
                                arena.start_gateway, policy_dir, episode_dir / "gateway-audit"
                            )
                            identities, agents = {}, {}
                            async with AsyncExitStack() as stack:
                                active_actors = (
                                    experiment.actor_ids[:1] if smoke else experiment.actor_ids
                                )
                                for actor in active_actors:
                                    docs = episode_dir / "documents" / actor
                                    docs.mkdir(mode=0o755, parents=True)
                                    # Only public material is mounted into the participant.
                                    os.chmod(episode_dir / "documents", 0o755)
                                    for filename in ("rules.md", "interface.md"):
                                        shutil.copyfile(RESOURCES / filename, docs / filename)
                                    shutil.copyfile(experiment.case.document, docs / "case.md")
                                    public = {
                                        "actor_id": actor,
                                        "episode_id": episode_id,
                                        **experiment.treatment.model_dump(),
                                    }
                                    (docs / "identity.json").write_text(json.dumps(public) + "\n")
                                    for file in docs.iterdir():
                                        file.chmod(0o644)
                                    sandbox, address = await asyncio.to_thread(
                                        arena.start_participant, actor, docs, gateway
                                    )
                                    identities[address] = Identity(
                                        actor_id=actor, token=f"dev-{actor}"
                                    )
                                    memory_root = (
                                        directory / "memory"
                                        if experiment.treatment.memory
                                        else episode_dir / "memory"
                                    )
                                    memory_root.mkdir(parents=True, exist_ok=True)
                                    checkpoint = await stack.enter_async_context(
                                        AsyncSqliteSaver.from_conn_string(
                                            str(memory_root / f"{actor}.sqlite")
                                        )
                                    )
                                    agents[actor] = ParticipantAgent(
                                        actor,
                                        sandbox,
                                        memory_root / actor,
                                        checkpoint,
                                        experiment.model,
                                        model=model,
                                    )
                                    stack.push_async_callback(agents[actor].aclose)
                                policy = GatewayPolicy(
                                    upstream=f"http://host.docker.internal:{relay_port}",
                                    relay_token=relay_token,
                                    episode_id=episode_id,
                                    identities=identities,
                                    **experiment.treatment.model_dump(exclude={"memory"}),
                                )
                                policy_path = policy_dir / "policy.json"
                                policy_path.write_text(policy.model_dump_json())
                                policy_path.chmod(0o600)
                                # Probe discovery before any provider request.
                                for agent in agents.values():
                                    for _attempt in range(20):
                                        probe = await asyncio.to_thread(
                                            agent.sandbox.execute,
                                            "curl -fsS --max-time 2 $GAME_URL/v1/health",
                                        )
                                        if probe.exit_code == 0:
                                            break
                                        await asyncio.sleep(0.2)
                                    else:
                                        raise RuntimeError(
                                            "Participant cannot reach the isolated game gateway"
                                        )
                                if smoke:
                                    result = await next(iter(agents.values())).act(
                                        episode_id, 1, episode_dir / "creator.trace.jsonl"
                                    )
                                    records = [{"actor_id": "creator", **asdict(result)}]
                                    if result.status not in {"completed", "budget_exhausted"}:
                                        raise RuntimeError("Live agent smoke failed")
                                    await engine.expire_episode(episode_id)
                                else:
                                    records = await play_episode(
                                        engine, episode_id, agents, experiment, episode_dir
                                    )
                    except BaseException as error:
                        primary_failure = type(error).__name__
                        (episode_dir / "failure.json").write_text(
                            json.dumps({"error_type": primary_failure}) + "\n"
                        )
                        raise
                    finally:
                        try:
                            try:
                                evidence = await retain_evidence(client, episode_id, episode_dir)
                            except Exception as error:
                                (episode_dir / "evidence-failure.json").write_text(
                                    json.dumps({"error_type": type(error).__name__}) + "\n"
                                )
                                if primary_failure is None:
                                    raise
                        finally:
                            try:
                                await asyncio.to_thread(arena.close)
                            except Exception as error:
                                (episode_dir / "cleanup-failure.json").write_text(
                                    json.dumps({"error_type": type(error).__name__}) + "\n"
                                )
                                if primary_failure is None:
                                    raise
                    summary = summarize(experiment, evidence, records)
                    manifest["episodes"].append(summary)
                    (episode_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
                    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                    LOG.info(
                        "episode finished episode=%s outcome=%s", episode_id, summary["outcome"]
                    )
            finally:
                await relay.cleanup()
        manifest["status"] = (
            "failed"
            if any(episode["agent_execution_failed"] for episode in manifest["episodes"])
            else "complete"
        )
    except BaseException as error:
        manifest.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        LOG.info("run finished run=%s status=%s", run_id, manifest["status"])
    return directory
