"""Adapter wrapping the Rust core engine HTTP API as a GameAPI.

The core engine runs as a child process with --local (spawns Anvil internally).
This adapter:
  - Starts/stops the Rust binary
  - Maps harness agent IDs → engine participant IDs (creator, challenger, juror-1..7)
  - Converts float $ amounts ↔ integer base-unit strings (wei)
  - Handles commit-reveal voting (commit verdict+assessment, advance time, reveal)
  - Advances Anvil chain time between phases
  - Polls operations until confirmed

Requires: aiohttp, the compiled binary at CORE_ENGINE_BIN, and Foundry's anvil.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

from .interface import GameAPI
from .types import EpisodeConfig, Phase, SettlementResult, Verdict

logger = logging.getLogger(__name__)

# Fixed engine participant IDs (from main.rs local mode)
ENGINE_PARTICIPANTS = {
    "creator": "dev-creator",
    "challenger": "dev-challenger",
    "juror-1": "dev-juror-1",
    "juror-2": "dev-juror-2",
    "juror-3": "dev-juror-3",
    "juror-4": "dev-juror-4",
    "juror-5": "dev-juror-5",
    "juror-6": "dev-juror-6",
    "juror-7": "dev-juror-7",
    "treasury": "dev-treasury",
}

OPERATOR_TOKEN = "dev-operator"

# Phase durations in seconds for registering episodes
DEFAULT_PHASE_DURATION = 300  # 5 minutes — we advance Anvil time past these
COMMIT_PHASE_DURATION = 3600  # Allow time for multi-round LLM deliberation and voting
REVEAL_PHASE_DURATION = DEFAULT_PHASE_DURATION


@dataclass
class _EpisodeMapping:
    """Maps harness agent IDs to engine participant IDs for one episode."""
    harness_to_engine: dict[str, str] = field(default_factory=dict)
    engine_to_harness: dict[str, str] = field(default_factory=dict)
    juror_verdicts: dict[str, Verdict] = field(default_factory=dict)
    juror_assessments: dict[str, str] = field(default_factory=dict)
    config: EpisodeConfig | None = None
    claim_text: str = ""
    evidence_text: str = ""


class CoreEngineAPI(GameAPI):
    """GameAPI backed by the real Rust core engine over HTTP."""

    def __init__(
        self,
        core_engine_dir: str | Path | None = None,
        bind: str = "127.0.0.1:8080",
        beta_wei: int = 1000,
        gamma_bps: int = 1000,
    ):
        # Path to the repo root containing the compiled binary
        if core_engine_dir is None:
            core_engine_dir = os.environ.get(
                "CORE_ENGINE_DIR",
                str(Path(__file__).resolve().parents[2] / "core-engine" / "apart-collusion-sprint-feat-core-engine"),
            )
        self._engine_dir = Path(core_engine_dir)
        self._bind = bind
        self._base_url = f"http://{bind}"
        self._beta_wei = beta_wei  # party bond in base units
        self._gamma_bps = gamma_bps  # juror bond = floor(beta * gamma / 10000)
        self._process: subprocess.Popen | None = None
        self._session: aiohttp.ClientSession | None = None
        self._episodes: dict[str, _EpisodeMapping] = {}
        self._rpc_url: str | None = None  # Anvil RPC URL, extracted from logs
        self._started = False

    async def start(self):
        """Start the core engine server."""
        if self._started:
            return

        binary = self._engine_dir / "target" / "debug" / "veracity-game-service"
        if not binary.exists():
            raise FileNotFoundError(
                f"Core engine binary not found at {binary}. "
                f"Build it with: cd {self._engine_dir} && cargo build --workspace"
            )

        logger.info("Starting core engine at %s", self._bind)
        env = os.environ.copy()
        env["RUST_LOG"] = "info"

        self._process = subprocess.Popen(
            [str(binary), "--local", "--bind", self._bind],
            cwd=str(self._engine_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        # Collect stderr in a background thread to discover the Anvil RPC URL
        import re
        import threading
        self._stderr_lines: list[str] = []
        _ansi_re = re.compile(r'\x1b\[[0-9;]*m')

        def _read_stderr():
            for line in self._process.stderr:
                text = line.decode(errors="replace")
                self._stderr_lines.append(text)
                # Strip ANSI color codes before matching
                clean = _ansi_re.sub("", text)
                m = re.search(r'rpc_endpoint=(\S+)', clean)
                if m and not self._rpc_url:
                    self._rpc_url = m.group(1)
                    logger.info("Discovered Anvil RPC at %s", self._rpc_url)

        self._stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        self._stderr_thread.start()

        # Wait for server to be ready (poll health endpoint)
        self._session = aiohttp.ClientSession()
        for attempt in range(30):
            await asyncio.sleep(0.5)
            try:
                async with self._session.get(f"{self._base_url}/v1/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info("Core engine ready: %s", data)
                        self._started = True

                        # Give stderr reader a moment to find the RPC URL
                        if not self._rpc_url:
                            await asyncio.sleep(0.5)
                        if not self._rpc_url:
                            self._rpc_url = "http://127.0.0.1:8545"
                            logger.warning(
                                "Could not discover Anvil RPC URL from logs, "
                                "using fallback %s", self._rpc_url,
                            )
                        return
            except (aiohttp.ClientError, OSError):
                if self._process.poll() is not None:
                    stderr = "".join(self._stderr_lines)
                    raise RuntimeError(f"Core engine exited early: {stderr}")

        raise TimeoutError("Core engine failed to start within 15 seconds")

    async def stop(self):
        """Stop the core engine server."""
        if self._session:
            await self._session.close()
            self._session = None
        if self._process:
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        self._started = False
        logger.info("Core engine stopped")

    # ── HTTP helpers ──

    async def _request(
        self,
        method: str,
        path: str,
        token: str | None = None,
        body: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Make an HTTP request to the core engine API."""
        if not self._session:
            raise RuntimeError("Core engine not started")

        url = f"{self._base_url}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        async with self._session.request(
            method, url, json=body, headers=headers
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                logger.error(
                    "Core engine error %d %s: %s", resp.status, path, text[:500]
                )
                raise RuntimeError(f"Core engine {resp.status} on {path}: {text[:300]}")

            if not text.strip():
                return {"status": resp.status}

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text, "status": resp.status}

            # If operation pending (202), poll until confirmed
            if resp.status == 202 and "operation_id" in data:
                return await self._wait_operation(data["operation_id"])

            return data

    async def _wait_operation(self, operation_id: str, timeout: float = 30.0) -> dict:
        """Poll an operation until it reaches a terminal state."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            async with self._session.get(
                f"{self._base_url}/v1/operations/{operation_id}"
            ) as resp:
                data = await resp.json()
                status = data.get("status", "")
                if status in ("confirmed", "included"):
                    return data
                if status in ("reverted", "failed"):
                    raise RuntimeError(f"Operation {operation_id} {status}: {data}")
            await asyncio.sleep(0.3)
        raise TimeoutError(f"Operation {operation_id} did not confirm within {timeout}s")

    async def _advance_time(self, seconds: int = 301):
        """Advance Anvil chain time to move past phase deadlines."""
        if not self._rpc_url:
            logger.warning("No Anvil RPC URL — cannot advance time")
            return

        async with self._session.post(
            self._rpc_url,
            json={"jsonrpc": "2.0", "method": "evm_increaseTime", "params": [seconds], "id": 1},
        ) as resp:
            await resp.json()

    async def _advance_to_deadline(self, episode_id: str, deadline_name: str) -> None:
        """Mine just past an episode's absolute deadline without skipping later phases."""
        async with self._session.get(
            f"{self._base_url}/v1/episodes/{episode_id}"
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"Could not read episode {episode_id} before advancing time: "
                    f"HTTP {resp.status}: {(await resp.text())[:300]}"
                )
            episode = await resp.json()

        deadline = episode.get(deadline_name)
        if not isinstance(deadline, int):
            raise RuntimeError(
                f"Episode {episode_id} has no valid {deadline_name}: {deadline!r}"
            )
        if not self._rpc_url:
            raise RuntimeError("No Anvil RPC URL — cannot advance to episode deadline")

        async with self._session.post(
            self._rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_getBlockByNumber",
                "params": ["latest", False],
                "id": 3,
            },
        ) as resp:
            block_response = await resp.json()
        block = block_response.get("result")
        if not isinstance(block, dict) or not isinstance(block.get("timestamp"), str):
            raise RuntimeError(f"Could not read latest Anvil block timestamp: {block_response}")
        current_timestamp = int(block["timestamp"], 16)
        seconds_to_deadline = max(0, deadline - current_timestamp + 1)
        if seconds_to_deadline:
            await self._advance_time(seconds_to_deadline)
        else:
            await self._advance_time(0)

        async with self._session.post(
            self._rpc_url,
            json={"jsonrpc": "2.0", "method": "evm_mine", "params": [], "id": 2},
        ) as resp:
            await resp.json()

    def _idem_key(self, episode_id: str, action: str) -> str:
        """Generate an idempotency key for an action."""
        return f"{episode_id}-{action}"

    # ── GameAPI implementation ──

    async def register_episode(
        self,
        config: EpisodeConfig,
        creator_id: str,
        challenger_id: str,
        juror_ids: list[str],
        treasury_id: str,
    ) -> str:
        if not self._started:
            await self.start()

        eid = config.episode_id
        jury_size = len(juror_ids)
        assert 3 <= jury_size <= 7 and jury_size % 2 == 1, \
            f"Core engine requires odd jury size 3-7, got {jury_size}"

        # Build harness → engine ID mapping
        mapping = _EpisodeMapping(config=config)
        mapping.harness_to_engine[creator_id] = "creator"
        mapping.harness_to_engine[challenger_id] = "challenger"
        mapping.harness_to_engine[treasury_id] = "treasury"
        mapping.engine_to_harness["creator"] = creator_id
        mapping.engine_to_harness["challenger"] = challenger_id
        mapping.engine_to_harness["treasury"] = treasury_id

        engine_juror_ids = []
        for j_idx, jid in enumerate(juror_ids):
            engine_jid = f"juror-{j_idx + 1}"
            mapping.harness_to_engine[jid] = engine_jid
            mapping.engine_to_harness[engine_jid] = jid
            engine_juror_ids.append(engine_jid)

        self._episodes[eid] = mapping

        # Register with the core engine
        body = {
            "episode_id": eid,
            "creator_id": "creator",
            "challenger_id": "challenger",
            "juror_ids": engine_juror_ids,
            "treasury_id": "treasury",
            "parameters": {
                "beta_wei": str(self._beta_wei),
                "gamma_bps": self._gamma_bps,
                "posting_duration_secs": DEFAULT_PHASE_DURATION,
                "challenge_duration_secs": DEFAULT_PHASE_DURATION,
                "commit_duration_secs": COMMIT_PHASE_DURATION,
                "reveal_duration_secs": REVEAL_PHASE_DURATION,
            },
        }

        result = await self._request(
            "POST", "/v1/episodes",
            token=OPERATOR_TOKEN,
            body=body,
            idempotency_key=self._idem_key(eid, "register"),
        )
        logger.info("Episode %s registered with core engine: %s", eid, result.get("status", "ok"))
        return eid

    async def post_claim(self, episode_id: str, creator_id: str) -> bool:
        mapping = self._episodes[episode_id]
        content = mapping.claim_text or "Claim text for this episode."

        result = await self._request(
            "POST", f"/v1/episodes/{episode_id}/claims",
            token=ENGINE_PARTICIPANTS["creator"],
            body={"content": content},
            idempotency_key=self._idem_key(episode_id, "claim"),
        )
        logger.info("Episode %s: claim posted via core engine", episode_id)
        return True

    async def challenge(self, episode_id: str, challenger_id: str) -> bool:
        mapping = self._episodes[episode_id]
        evidence = mapping.evidence_text or "Counter-evidence for this episode."

        # Advance time past posting deadline so challenge window is open
        # (posting window is already open right after registration)
        # Actually the challenge window opens after the claim is posted,
        # not after posting deadline. The claim starts the challenge window.

        result = await self._request(
            "POST", f"/v1/episodes/{episode_id}/challenges",
            token=ENGINE_PARTICIPANTS["challenger"],
            body={"evidence": evidence},
            idempotency_key=self._idem_key(episode_id, "challenge"),
        )
        logger.info("Episode %s: challenge posted via core engine", episode_id)
        return True

    async def post_juror_bond(self, episode_id: str, juror_id: str) -> bool:
        # In the core engine, juror bond is posted with the commitment.
        # We track that this juror should participate, but the actual deposit
        # happens during cast_vote (commit).
        # This is a no-op for the core engine — the bond is deposited
        # automatically when the juror commits their vote.
        logger.debug("Episode %s: juror bond for %s (deferred to commit)", episode_id, juror_id)
        return True

    async def start_deliberation(self, episode_id: str) -> bool:
        # Deliberation is harness-only — no engine state change needed.
        # But we need to advance time past the challenge deadline to enter COMMIT phase.
        # Actually the challenge puts us into COMMIT automatically once the
        # challenge deadline is reached.
        logger.debug("Episode %s: deliberation started (harness-only)", episode_id)
        return True

    async def start_voting(self, episode_id: str) -> bool:
        # After challenge, the engine enters COMMIT phase immediately.
        # Deliberation rounds are harness-only (no chain interaction),
        # so chain time hasn't advanced — the commit window is still open.
        logger.debug("Episode %s: voting started (commit phase)", episode_id)
        return True

    async def cast_vote(
        self, episode_id: str, juror_id: str, verdict: Verdict
    ) -> bool:
        mapping = self._episodes[episode_id]
        engine_jid = mapping.harness_to_engine[juror_id]
        token = ENGINE_PARTICIPANTS[engine_jid]

        # Map verdict to engine format
        verdict_str = (
            "CREATOR_SUPPORTED" if verdict == Verdict.CREATOR_SUPPORTED
            else "CHALLENGER_SUPPORTED"
        )

        # Store the vote — we'll commit all at once then reveal all at once
        mapping.juror_verdicts[juror_id] = verdict
        mapping.juror_assessments[juror_id] = f"Assessment by {juror_id}: I vote {verdict_str}."

        # Commit this juror's vote (includes bond deposit)
        result = await self._request(
            "POST", f"/v1/episodes/{episode_id}/commitments",
            token=token,
            body={
                "verdict": verdict_str,
                "assessment": mapping.juror_assessments[juror_id],
            },
            idempotency_key=self._idem_key(episode_id, f"commit-{engine_jid}"),
        )
        logger.info("Episode %s: %s committed vote %s", episode_id, engine_jid, verdict_str)
        return True

    async def settle(self, episode_id: str) -> SettlementResult:
        mapping = self._episodes[episode_id]

        # Advance only to the commit deadline; deliberation may already have
        # consumed part of the commit window in real time.
        await self._advance_to_deadline(episode_id, "commit_deadline")

        # Reveal all committed votes
        for harness_jid, verdict in mapping.juror_verdicts.items():
            engine_jid = mapping.harness_to_engine[harness_jid]
            token = ENGINE_PARTICIPANTS[engine_jid]
            await self._request(
                "POST", f"/v1/episodes/{episode_id}/reveals",
                token=token,
                body={},
                idempotency_key=self._idem_key(episode_id, f"reveal-{engine_jid}"),
            )
            logger.info("Episode %s: %s revealed", episode_id, engine_jid)

        # Advance only to the reveal deadline, preserving the on-chain phase window.
        await self._advance_to_deadline(episode_id, "reveal_deadline")

        # Settle
        try:
            await self._request(
                "POST", f"/v1/episodes/{episode_id}/settle",
                token=OPERATOR_TOKEN,
                body={},
                idempotency_key=self._idem_key(episode_id, "settle"),
            )
        except Exception as e:
            logger.warning("Episode %s: settle call: %s", episode_id, e)

        # Read settlement result
        try:
            async with self._session.get(
                f"{self._base_url}/v1/episodes/{episode_id}/settlement"
            ) as resp:
                if resp.status == 200:
                    return self._parse_settlement(episode_id, await resp.json(), mapping)
        except Exception as e:
            logger.warning("Episode %s: settlement read: %s", episode_id, e)

        # Read episode state to determine outcome
        try:
            async with self._session.get(
                f"{self._base_url}/v1/episodes/{episode_id}"
            ) as resp:
                ep_data = await resp.json()
                phase_str = ep_data.get("phase", "ABORTED")
                return self._build_result_from_phase(episode_id, phase_str, mapping)
        except Exception as e:
            logger.error("Episode %s: could not read state: %s", episode_id, e)

        # Fallback: build result from our tracked votes
        return self._build_result_from_votes(episode_id, mapping)

    async def expire(self, episode_id: str) -> SettlementResult:
        mapping = self._episodes[episode_id]

        # Advance time past the relevant deadline
        await self._advance_time(DEFAULT_PHASE_DURATION + 1)

        try:
            await self._request(
                "POST", f"/v1/episodes/{episode_id}/expire",
                token=OPERATOR_TOKEN,
                body={},
                idempotency_key=self._idem_key(episode_id, "expire"),
            )
        except Exception as e:
            logger.warning("Episode %s: expire: %s", episode_id, e)

        result = SettlementResult(episode_id=episode_id, outcome=Phase.EXPIRED)
        if mapping.config:
            creator_harness = mapping.engine_to_harness.get("creator", "")
            result.refunds[creator_harness] = mapping.config.payout.creator_bet
        return result

    async def get_state(self, episode_id: str) -> Phase:
        try:
            async with self._session.get(
                f"{self._base_url}/v1/episodes/{episode_id}"
            ) as resp:
                data = await resp.json()
                return self._map_phase(data.get("phase", "REGISTERED"))
        except Exception:
            return Phase.SETUP

    async def get_balances(self, episode_id: str) -> dict[str, float]:
        mapping = self._episodes[episode_id]
        try:
            async with self._session.get(
                f"{self._base_url}/v1/episodes/{episode_id}/balances"
            ) as resp:
                data = await resp.json()
                balances: dict[str, float] = {}
                # Map engine IDs back to harness IDs and convert wei to float
                for engine_id, wei_str in data.get("credits", {}).items():
                    harness_id = mapping.engine_to_harness.get(engine_id, engine_id)
                    balances[harness_id] = int(wei_str) / self._beta_wei if self._beta_wei else 0
                return balances
        except Exception:
            return {}

    # ── Helpers for the runner to set claim/evidence text ──

    def set_claim_text(self, episode_id: str, text: str):
        """Set the claim text before post_claim is called."""
        if episode_id in self._episodes:
            self._episodes[episode_id].claim_text = text

    def set_evidence_text(self, episode_id: str, text: str):
        """Set the counter-evidence text before challenge is called."""
        if episode_id in self._episodes:
            self._episodes[episode_id].evidence_text = text

    # ── Settlement parsing ──

    def _wei_to_float(self, wei_str: str | int) -> float:
        """Convert base-unit string to a float dollar amount.

        The core engine uses integer base units. We treat beta_wei as $10
        equivalent, so 1000 wei = $10, or 1 wei = $0.01.
        """
        wei = int(wei_str) if isinstance(wei_str, str) else wei_str
        # Scale: beta_wei represents the creator/challenger bet in $
        if self._beta_wei > 0:
            return wei * 10.0 / self._beta_wei  # $10 per beta_wei
        return float(wei)

    def _parse_settlement(
        self, episode_id: str, data: dict, mapping: _EpisodeMapping
    ) -> SettlementResult:
        """Parse the core engine's settlement response."""
        result = SettlementResult(episode_id=episode_id)
        result.final_votes = {
            mapping.engine_to_harness.get(k, k): (
                Verdict.CREATOR_SUPPORTED if v == "CREATOR_SUPPORTED"
                else Verdict.CHALLENGER_SUPPORTED
            )
            for k, v in data.get("votes", {}).items()
        }

        phase = data.get("phase", data.get("outcome", "ABORTED"))
        result.outcome = self._map_phase(phase)

        if result.outcome == Phase.SETTLED_CREATOR:
            result.winner_id = mapping.engine_to_harness.get("creator", "creator")
        elif result.outcome == Phase.SETTLED_CHALLENGER:
            result.winner_id = mapping.engine_to_harness.get("challenger", "challenger")

        # Parse payouts
        winner_payout = data.get("winner_payout", "0")
        result.winner_payout = self._wei_to_float(winner_payout)

        for engine_jid, payout_wei in data.get("juror_payouts", {}).items():
            harness_jid = mapping.engine_to_harness.get(engine_jid, engine_jid)
            result.juror_payouts[harness_jid] = self._wei_to_float(payout_wei)

        result.protocol_fee = self._wei_to_float(data.get("protocol_fee", "0"))

        for engine_jid, bond_wei in data.get("forfeited_bonds", {}).items():
            harness_jid = mapping.engine_to_harness.get(engine_jid, engine_jid)
            result.forfeited_bonds[harness_jid] = self._wei_to_float(bond_wei)

        for engine_id, refund_wei in data.get("refunds", {}).items():
            harness_id = mapping.engine_to_harness.get(engine_id, engine_id)
            result.refunds[harness_id] = self._wei_to_float(refund_wei)

        return result

    def _build_result_from_phase(
        self, episode_id: str, phase_str: str, mapping: _EpisodeMapping
    ) -> SettlementResult:
        """Build a SettlementResult from the episode phase when settlement endpoint isn't available."""
        phase = self._map_phase(phase_str)
        return self._build_result_from_votes(episode_id, mapping, outcome_override=phase)

    def _build_result_from_votes(
        self, episode_id: str, mapping: _EpisodeMapping,
        outcome_override: Phase | None = None,
    ) -> SettlementResult:
        """Fallback: compute settlement from tracked votes (same logic as MockGameAPI)."""
        result = SettlementResult(episode_id=episode_id)
        result.final_votes = dict(mapping.juror_verdicts)

        if not mapping.config:
            result.outcome = outcome_override or Phase.ABORTED
            return result

        payout = mapping.config.payout
        creator_votes = sum(
            1 for v in mapping.juror_verdicts.values()
            if v == Verdict.CREATOR_SUPPORTED
        )
        challenger_votes = sum(
            1 for v in mapping.juror_verdicts.values()
            if v == Verdict.CHALLENGER_SUPPORTED
        )
        threshold = mapping.config.majority_threshold

        if outcome_override:
            result.outcome = outcome_override
        elif creator_votes >= threshold:
            result.outcome = Phase.SETTLED_CREATOR
        elif challenger_votes >= threshold:
            result.outcome = Phase.SETTLED_CHALLENGER
        else:
            result.outcome = Phase.ABORTED

        if result.outcome == Phase.SETTLED_CREATOR:
            result.winner_id = mapping.engine_to_harness.get("creator", "")
            result.winner_payout = payout.winner_payout()
        elif result.outcome == Phase.SETTLED_CHALLENGER:
            result.winner_id = mapping.engine_to_harness.get("challenger", "")
            result.winner_payout = payout.winner_payout()
        else:
            # Aborted — refund both
            result.refunds[mapping.engine_to_harness.get("creator", "")] = payout.creator_bet
            result.refunds[mapping.engine_to_harness.get("challenger", "")] = payout.challenger_bet
            return result

        # Juror payouts
        num_qual = len(mapping.juror_verdicts)
        per_juror = payout.juror_payout(num_qual)
        for jid in mapping.juror_verdicts:
            result.juror_payouts[jid] = per_juror

        result.protocol_fee = payout.protocol_fee()
        return result

    @staticmethod
    def _map_phase(phase_str: str) -> Phase:
        """Map core engine phase string to harness Phase enum."""
        phase_map = {
            "REGISTERED": Phase.SETUP,
            "OPEN": Phase.CLAIM_POSTED,
            "COMMIT": Phase.CHALLENGED,
            "REVEAL": Phase.VOTING,
            "SETTLED_CREATOR": Phase.SETTLED_CREATOR,
            "SETTLED_CHALLENGER": Phase.SETTLED_CHALLENGER,
            "ABORTED": Phase.ABORTED,
            "EXPIRED_UNCHALLENGED": Phase.EXPIRED,
            "EXPIRED_UNFUNDED": Phase.EXPIRED,
        }
        return phase_map.get(phase_str, Phase.SETUP)

    # ── Context manager ──

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
