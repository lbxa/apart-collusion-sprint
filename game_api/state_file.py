"""Game state file adapter.

Instead of calling a live API, the game can dump its state as a markdown
or JSON file after each phase. This adapter reads those files and provides
the same interface to the harness.

Expected file format (markdown):

    # Episode: ep_001
    ## Config
    - creator_bet: 10.0
    - challenger_bet: 10.0
    - jury_size: 5
    - winner_pct: 0.60
    - juror_pool_pct: 0.30
    - protocol_pct: 0.10
    - juror_bond: 1.0
    - deliberation_rounds: 3

    ## Participants
    - creator: agent_alice
    - challenger: agent_bob
    - jurors: agent_c, agent_d, agent_e, agent_f, agent_g
    - treasury: treasury_001

    ## Scenario
    - claim: "The Earth is flat"
    - evidence_for: "..."
    - evidence_against: "..."
    - ground_truth: false

    ## Phase: DELIBERATION (round 2 of 3)
    ## Messages:
    - [R1] agent_c (public): "I believe the evidence supports..."
    - [R1] agent_d (public): "Looking at the data..."
    ## Straw Polls:
    - Round 1: CREATOR=3, CHALLENGER=2

    ## Final Votes: agent_c (CREATOR), agent_d (CHALLENGER), agent_e (CREATOR)
    ## Settlement: SETTLED_CREATOR
    ## Payouts:
    - agent_alice: 16.0
    - agent_c: 1.60
    - agent_d: 1.60
    - treasury: 1.0

Or JSON:

    {
      "episode_id": "ep_001",
      "config": { "creator_bet": 10.0, "challenger_bet": 10.0, ... },
      "participants": { "creator": "...", ... },
      "scenario": { "claim": "...", ... },
      "current_phase": "DELIBERATION",
      "current_round": 2,
      "deliberation": { "messages": [...], "straw_polls": [...] },
      "votes": { "agent_c": "CREATOR_SUPPORTED" },
      "settlement": { "outcome": "SETTLED_CREATOR", "winner_payout": 16.0, ... }
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .types import (
    EpisodeConfig,
    PayoutConfig,
    Phase,
    Scenario,
    SettlementResult,
    Verdict,
)


def parse_game_state_json(path: Path) -> dict[str, Any]:
    """Parse a JSON game state file."""
    with open(path) as f:
        return json.load(f)


def parse_game_state_markdown(path: Path) -> dict[str, Any]:
    """Parse a markdown game state file into structured data."""
    text = path.read_text()
    state: dict[str, Any] = {}

    # Episode ID
    m = re.search(r"^# Episode:\s*(.+)$", text, re.MULTILINE)
    if m:
        state["episode_id"] = m.group(1).strip()

    # Config section
    state["config"] = {}
    config_float_fields = [
        "creator_bet", "challenger_bet", "winner_pct",
        "juror_pool_pct", "protocol_pct", "juror_bond",
    ]
    config_int_fields = ["jury_size", "deliberation_rounds"]

    for field in config_float_fields:
        m = re.search(rf"- {field}:\s*\$?([\d.]+)", text)
        if m:
            state["config"][field] = float(m.group(1))

    for field in config_int_fields:
        m = re.search(rf"- {field}:\s*(\d+)", text)
        if m:
            state["config"][field] = int(m.group(1))

    # Handle percentage format (e.g., "60%" → 0.60)
    for field in ["winner_pct", "juror_pool_pct", "protocol_pct"]:
        m = re.search(rf"- {field}:\s*([\d.]+)%", text)
        if m:
            state["config"][field] = float(m.group(1)) / 100.0

    # Participants
    state["participants"] = {}
    for role in ["creator", "challenger", "treasury"]:
        m = re.search(rf"- {role}:\s*(\S+)", text)
        if m:
            state["participants"][role] = m.group(1).strip()

    m = re.search(r"- jurors:\s*(.+)$", text, re.MULTILINE)
    if m:
        state["participants"]["jurors"] = [
            j.strip() for j in m.group(1).split(",")
        ]

    # Scenario
    state["scenario"] = {}
    for field in ["claim", "ground_truth"]:
        m = re.search(rf"- {field}:\s*(.+)$", text, re.MULTILINE)
        if m:
            val = m.group(1).strip().strip('"')
            if field == "ground_truth":
                val = {"true": True, "false": False, "null": None, "none": None}.get(
                    val.lower(), None
                )
            state["scenario"][field] = val

    for field in ["evidence_for", "evidence_against"]:
        m = re.search(rf"- {field}:\s*(.+)$", text, re.MULTILINE)
        if m:
            state["scenario"][field] = m.group(1).strip().strip('"')

    # Phase and round
    m = re.search(r"## Phase:\s*(\w+)", text)
    if m:
        state["current_phase"] = m.group(1).strip()

    m = re.search(r"\(round\s+(\d+)\s+of\s+(\d+)\)", text)
    if m:
        state["current_round"] = int(m.group(1))

    # Deliberation messages
    state["deliberation"] = {"messages": [], "straw_polls": []}
    for m in re.finditer(
        r"\[R(\d+)\]\s+(\S+)\s+\((\w+)\):\s*\"(.+?)\"", text
    ):
        state["deliberation"]["messages"].append({
            "round": int(m.group(1)),
            "sender": m.group(2),
            "channel": m.group(3),
            "content": m.group(4),
        })

    # Straw polls
    for m in re.finditer(
        r"Round\s+(\d+):\s*CREATOR=(\d+),\s*CHALLENGER=(\d+)", text
    ):
        state["deliberation"]["straw_polls"].append({
            "round": int(m.group(1)),
            "creator_votes": int(m.group(2)),
            "challenger_votes": int(m.group(3)),
        })

    # Final votes
    state["votes"] = {}
    votes_match = re.search(r"## Final Votes:\s*(.+)$", text, re.MULTILINE)
    if votes_match:
        for m in re.finditer(r"(\w+)\s*\((\w+)\)", votes_match.group(1)):
            state["votes"][m.group(1)] = m.group(2) + "_SUPPORTED"

    # Settlement
    m = re.search(r"## Settlement:\s*(\w+)", text)
    if m:
        state["settlement"] = {"outcome": m.group(1).strip()}

    # Payouts
    state["payouts"] = {}
    payout_section = text[text.find("## Payouts"):] if "## Payouts" in text else ""
    for m in re.finditer(r"- (\S+):\s*\$?([\d.]+)", payout_section):
        state["payouts"][m.group(1)] = float(m.group(2))

    return state


def state_to_payout_config(state: dict[str, Any]) -> PayoutConfig:
    """Convert parsed state to PayoutConfig."""
    cfg = state.get("config", {})
    return PayoutConfig(
        creator_bet=cfg.get("creator_bet", 10.0),
        challenger_bet=cfg.get("challenger_bet", 10.0),
        winner_pct=cfg.get("winner_pct", 0.60),
        juror_pool_pct=cfg.get("juror_pool_pct", 0.30),
        protocol_pct=cfg.get("protocol_pct", 0.10),
        juror_bond=cfg.get("juror_bond", 1.0),
    )


def state_to_episode_config(state: dict[str, Any]) -> EpisodeConfig:
    """Convert parsed state to EpisodeConfig."""
    cfg = state.get("config", {})
    return EpisodeConfig(
        episode_id=state.get("episode_id", "unknown"),
        payout=state_to_payout_config(state),
        jury_size=cfg.get("jury_size", 5),
        deliberation_rounds=cfg.get("deliberation_rounds", 3),
    )


def state_to_scenario(state: dict[str, Any]) -> Scenario:
    """Convert parsed state to Scenario."""
    sc = state.get("scenario", {})
    return Scenario(
        scenario_id=state.get("episode_id", "unknown"),
        claim=sc.get("claim", ""),
        evidence_for=sc.get("evidence_for", ""),
        evidence_against=sc.get("evidence_against", ""),
        ground_truth=sc.get("ground_truth"),
    )


def state_to_settlement(state: dict[str, Any]) -> SettlementResult | None:
    """Convert parsed state to SettlementResult if settled."""
    settlement = state.get("settlement")
    if not settlement:
        return None

    outcome_map = {
        "SETTLED_CREATOR": Phase.SETTLED_CREATOR,
        "SETTLED_CHALLENGER": Phase.SETTLED_CHALLENGER,
        "ABORTED": Phase.ABORTED,
        "EXPIRED": Phase.EXPIRED,
    }

    outcome = outcome_map.get(settlement.get("outcome", ""), Phase.ABORTED)
    payouts = state.get("payouts", {})

    return SettlementResult(
        episode_id=state.get("episode_id", "unknown"),
        outcome=outcome,
        juror_payouts={k: v for k, v in payouts.items() if k.startswith("juror") or k.startswith("agent")},
    )
