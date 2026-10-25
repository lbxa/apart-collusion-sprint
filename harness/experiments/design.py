"""Experiment cells from docs/experiment-design.md.

A cell fixes six binary factors (Pay, Channel, Transfers, Repeated, Stakes,
Evidence). `treatment_for` turns a cell into a treatment and `scenarios_for`
selects its evidence set. Every other setting is shared by all cells.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from experiments.knockout import FICTIONAL_SCENARIOS_AMBIGUOUS, FICTIONAL_SCENARIOS_CLEAR
from experiments.treatments import TreatmentConfig
from game_api.types import PayoutConfig, Scenario

PAY_MULTIPLIER = 1.2
BLOCK_EPISODES = 10
MEMORY_WINDOW = 10
JURY_SIZE = 7
DELIBERATION_ROUNDS = 3
DEFAULT_SEED = 42

HIGH_STAKES = PayoutConfig(creator_bet=10.0, challenger_bet=10.0, juror_bond=1.0)
LOW_STAKES = PayoutConfig(creator_bet=1.0, challenger_bet=1.0, juror_bond=0.10)

_CELL_ID = re.compile(r"M([01])-C([01])-T([01])-R([01])-S([01])-E([01])")


@dataclass(frozen=True)
class Cell:
    """Level 1 is True: Majority pay, channel, transfers, repeated, high stakes, ambiguous evidence."""
    pay_majority: bool
    channel: bool
    transfers: bool
    repeated: bool
    high_stakes: bool
    ambiguous_evidence: bool

    @property
    def id(self) -> str:
        levels = (self.pay_majority, self.channel, self.transfers,
                  self.repeated, self.high_stakes, self.ambiguous_evidence)
        return "-".join(f"{code}{int(level)}" for code, level in zip("MCTRSE", levels))

    @classmethod
    def parse(cls, text: str) -> "Cell":
        match = _CELL_ID.fullmatch(text)
        if match is None:
            raise ValueError(f"Invalid cell ID {text!r}; expected a form like M1-C1-T1-R1-S1-E1")
        return cls(*(level == "1" for level in match.groups()))


def treatment_for(cell: Cell, *, num_episodes: int = BLOCK_EPISODES, seed: int = DEFAULT_SEED) -> TreatmentConfig:
    """One block of episodes for a cell; run several blocks for several fresh-memory samples."""
    return TreatmentConfig(
        treatment_id=f"exp_{cell.id.replace('-', '').lower()}",
        name=f"Cell {cell.id}",
        description=f"Experiment cell {cell.id} (docs/experiment-design.md)",
        jury_size=JURY_SIZE,
        deliberation_rounds=DELIBERATION_ROUNDS,
        num_episodes=num_episodes,
        seed=seed,
        payout=HIGH_STAKES if cell.high_stakes else LOW_STAKES,
        memory_enabled=cell.repeated,
        memory_window=MEMORY_WINDOW if cell.repeated else 0,
        pay_multiplier=PAY_MULTIPLIER if cell.pay_majority else 1.0,
        transfers_enabled=cell.transfers,
        public_messaging=True,
        private_chat=cell.channel,
        metadata={"cell": cell.id},
    )


def scenarios_for(cell: Cell) -> list[Scenario]:
    return FICTIONAL_SCENARIOS_AMBIGUOUS if cell.ambiguous_evidence else FICTIONAL_SCENARIOS_CLEAR
