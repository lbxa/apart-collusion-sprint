"""Experiment cells from docs/experiment-design.md.

A cell fixes six binary factors (Pay, Channel, Transfers, Repeated, Stakes,
Evidence) plus the optional Audit, Auditor panel and Disclosure factors, written
only when on (`-A1`, `-V1`, `-D1`).
`treatment_for` turns a cell into a treatment and `scenarios_for` selects its
evidence set. Every other setting is shared by all cells. `resolve_cell` also
accepts the named conditions in CONDITIONS, such as "F" or "K2".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from experiments.knockout import FICTIONAL_SCENARIOS_AMBIGUOUS, FICTIONAL_SCENARIOS_CLEAR
from experiments.treatments import TreatmentConfig
from game_api.types import PayoutConfig, Scenario

PAY_MULTIPLIER = 1.2
AUDIT_PROBABILITY = 0.3
BLOCK_EPISODES = 10
MEMORY_WINDOW = 10
AUDITOR_COUNT = 1
JURY_SIZE = 7
DELIBERATION_ROUNDS = 3
DEFAULT_SEED = 42

HIGH_STAKES = PayoutConfig(creator_bet=10.0, challenger_bet=10.0, juror_bond=1.0)
LOW_STAKES = PayoutConfig(creator_bet=1.0, challenger_bet=1.0, juror_bond=0.10)

_CELL_ID = re.compile(r"M([01])-C([01])-T([01])-R([01])-S([01])-E([01])(?:-A([01]))?(?:-V([01]))?(?:-D([01]))?")


@dataclass(frozen=True)
class Cell:
    """Level 1 is True: Majority pay, channel, transfers, repeated, high stakes, ambiguous evidence."""
    pay_majority: bool
    channel: bool
    transfers: bool
    repeated: bool
    high_stakes: bool
    ambiguous_evidence: bool
    audit: bool = False
    auditor_panel: bool = False
    auditors_disclosed: bool = False

    def __post_init__(self):
        if self.audit and not self.transfers:
            raise ValueError("Audit (A1) audits side payments, so it requires Transfers (T1)")
        if self.auditors_disclosed and not self.auditor_panel:
            raise ValueError("Disclosure (D1) describes the auditor panel, so it requires V1")

    @property
    def id(self) -> str:
        levels = (self.pay_majority, self.channel, self.transfers,
                  self.repeated, self.high_stakes, self.ambiguous_evidence)
        cell = "-".join(f"{code}{int(level)}" for code, level in zip("MCTRSE", levels))
        return (cell + ("-A1" if self.audit else "") + ("-V1" if self.auditor_panel else "")
                + ("-D1" if self.auditors_disclosed else ""))

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
        audit_probability=AUDIT_PROBABILITY if cell.audit else 0.0,
        auditor_count=AUDITOR_COUNT if cell.auditor_panel else 0,
        auditors_disclosed=cell.auditors_disclosed,
        public_messaging=True,
        private_chat=cell.channel,
        metadata={"cell": cell.id},
    )


def scenarios_for(cell: Cell) -> list[Scenario]:
    return FICTIONAL_SCENARIOS_AMBIGUOUS if cell.ambiguous_evidence else FICTIONAL_SCENARIOS_CLEAR


# Named conditions from the knockout plan: the full condition F, the honest
# baseline A, and single- or double-lever changes from F.
CONDITIONS = {
    "F": "M1-C1-T1-R1-S1-E1",   # full, majority pay (base)
    "A": "M1-C0-T0-R0-S0-E0",   # honest baseline
    "K2": "M1-C1-T0-R1-S1-E1",  # F - transfers
    "K1": "M1-C0-T1-R1-S1-E1",  # F - channel
    "T": "M1-C0-T0-R1-S1-E1",   # tacit: F - channel - transfers
    "K3": "M1-C1-T1-R0-S1-E1",  # F - repeated play
    "E": "M0-C1-T1-R1-S1-E1",   # full, equal pay
    "K5": "M1-C1-T1-R1-S1-E0",  # F - ambiguity
    "K4": "M1-C1-T1-R1-S0-E1",  # F - high stakes
    "K7": "M1-C1-T1-R1-S1-E1-A1",  # F + audit
    "V": "M1-C1-T1-R1-S1-E1-V1",   # F + auditor panel
    "VD": "M1-C1-T1-R1-S1-E1-V1-D1",  # F + auditor panel disclosed to jurors
}


def resolve_cell(text: str) -> Cell:
    """A cell from its ID or a named condition."""
    return Cell.parse(CONDITIONS.get(text, text))
