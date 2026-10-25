"""Markdown episode logger — human-readable record of every handoff.

Produces one .md file per episode showing the full chain:
  Creator → Challenger → Juror bonds → Deliberation rounds → Votes → Settlement

Each handoff is timestamped and annotated with channel, role, money flow.
This is the audit trail for the hackathon judges.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game_api.types import Phase, Verdict


@dataclass
class HandoffEntry:
    """One step in the episode flow."""
    timestamp: float
    phase: str
    actor: str
    role: str
    action: str
    details: str
    channel: str = "game"   # game | public | private
    money_in: float = 0.0   # money deposited
    money_out: float = 0.0  # money received


class EpisodeLogger:
    """Records and exports a full episode transcript as markdown."""

    def __init__(self, episode_id: str, output_dir: Path):
        self.episode_id = episode_id
        self.output_dir = output_dir
        self.entries: list[HandoffEntry] = []
        self.metadata: dict[str, Any] = {}
        self._start = time.monotonic()

    def log(self, phase: str, actor: str, role: str, action: str,
            details: str, channel: str = "game",
            money_in: float = 0.0, money_out: float = 0.0):
        self.entries.append(HandoffEntry(
            timestamp=time.monotonic() - self._start,
            phase=phase, actor=actor, role=role,
            action=action, details=details, channel=channel,
            money_in=money_in, money_out=money_out,
        ))

    def set_metadata(self, **kwargs):
        self.metadata.update(kwargs)

    def export_markdown(self) -> str:
        """Render the full episode as a markdown document."""
        lines = []
        lines.append(f"# Episode: {self.episode_id}")
        lines.append("")

        # Metadata
        if self.metadata:
            lines.append("## Configuration")
            for k, v in self.metadata.items():
                if isinstance(v, dict):
                    lines.append(f"- **{k}**:")
                    for kk, vv in v.items():
                        lines.append(f"  - {kk}: {vv}")
                else:
                    lines.append(f"- **{k}**: {v}")
            lines.append("")

        # Group entries by phase
        current_phase = None
        for entry in self.entries:
            if entry.phase != current_phase:
                current_phase = entry.phase
                lines.append(f"## Phase: {current_phase}")
                lines.append("")

            # Timestamp
            ts = f"[{entry.timestamp:6.1f}s]"

            # Channel badge
            ch = ""
            if entry.channel != "game" and entry.channel != "public":
                ch = f" 🔒{entry.channel}"
            elif entry.channel == "public":
                ch = " 📢public"

            # Money flow
            money = ""
            if entry.money_in > 0:
                money += f" 💰-${entry.money_in:.2f}"
            if entry.money_out > 0:
                money += f" 💰+${entry.money_out:.2f}"

            # Role badge
            role_emoji = {"CREATOR": "📝", "CHALLENGER": "⚔️", "JUROR": "⚖️"}.get(
                entry.role, "🔧"
            )

            lines.append(
                f"{ts} {role_emoji} **{entry.actor}** ({entry.role}){ch}{money}"
            )
            lines.append(f"  → {entry.action}: {entry.details}")
            lines.append("")

        # Money summary
        total_in = sum(e.money_in for e in self.entries)
        total_out = sum(e.money_out for e in self.entries)
        lines.append("## Money Flow Summary")
        lines.append(f"- Total deposited: ${total_in:.2f}")
        lines.append(f"- Total paid out: ${total_out:.2f}")
        lines.append(f"- Protocol revenue: ${total_in - total_out:.2f}")
        lines.append("")

        # Per-agent P&L
        agent_pl: dict[str, dict[str, float]] = {}
        for e in self.entries:
            if e.actor not in agent_pl:
                agent_pl[e.actor] = {"in": 0, "out": 0}
            agent_pl[e.actor]["in"] += e.money_in
            agent_pl[e.actor]["out"] += e.money_out

        lines.append("### Per-Agent Profit & Loss")
        lines.append("| Agent | Role | Deposited | Received | Net |")
        lines.append("|-------|------|-----------|----------|-----|")
        for actor, pl in agent_pl.items():
            net = pl["out"] - pl["in"]
            sign = "+" if net >= 0 else ""
            # Find role
            role = next((e.role for e in self.entries if e.actor == actor), "?")
            lines.append(
                f"| {actor[:30]} | {role} | ${pl['in']:.2f} | ${pl['out']:.2f} | {sign}${net:.2f} |"
            )
        lines.append("")

        return "\n".join(lines)

    def save(self):
        """Write the markdown log to disk."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        md_path = self.output_dir / f"{self.episode_id}.md"
        md_path.write_text(self.export_markdown())
        return md_path

    def export_json(self) -> dict[str, Any]:
        """Export as structured JSON for programmatic analysis."""
        return {
            "episode_id": self.episode_id,
            "metadata": self.metadata,
            "entries": [
                {
                    "timestamp": round(e.timestamp, 3),
                    "phase": e.phase,
                    "actor": e.actor,
                    "role": e.role,
                    "action": e.action,
                    "details": e.details,
                    "channel": e.channel,
                    "money_in": e.money_in,
                    "money_out": e.money_out,
                }
                for e in self.entries
            ],
        }
