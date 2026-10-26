"""Content-free snapshot and results table for the exploratory single-episode probes.

Normal use renders the committed snapshot into the LaTeX table the report inputs:
  python report/analysis/probe_snapshot.py

To admit or refresh evidence, re-extract from the ignored local run exports:
  python report/analysis/probe_snapshot.py --extract --experiments .harness/experiments

Only counts, settings and provenance cross that boundary. Prompts, messages,
reasoning, assessments, interview text and monitor evidence quotes stay in the
local exports. Each probe is one episode, so no spread or uncertainty is computed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

REPORT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPORT / "data" / "exploratory-probes.json"
TABLE = REPORT / "tables" / "exploratory-probes.tex"
BEHAVIOURS = ("collusion", "payment", "deception", "auditor_evasion", "watched")

# One DeepSeek V4.1 Flash episode each, all on scenario fic_001 (a false claim).
# The offer rule is fixed by code revision: before 0ff13bd a juror could hold one
# offer and the creator's offers were processed first. X2's auditor received a case
# file that marked both of a juror's offers accepted (fixed in 97018a1), so its
# auditor and interview observations are inadmissible; its juror decisions precede
# the auditor and are unaffected.
PROBES = [
    {"id": "X1", "output": "one-V-deepseek_flash", "wandb_run": "q1c4i5fc", "offer_rule": "single",
     "auditor_admissible": True},
    {"id": "X2", "output": "one-V-deepseek_flash-competing", "wandb_run": "yy778qcf", "offer_rule": "competing",
     "auditor_admissible": False},
    {"id": "X3", "output": "one-F-deepseek_flash-competing", "wandb_run": "d6on7p4r", "offer_rule": "competing",
     "auditor_admissible": True},
    {"id": "X4", "output": "one-V-deepseek_flash-partyoffers", "wandb_run": "dke4rumq", "offer_rule": "competing",
     "auditor_admissible": True},
    {"id": "X5", "output": "one-F-deepseek_flash-prohibited", "wandb_run": "uvggpm2l", "offer_rule": "competing",
     "auditor_admissible": True},
    {"id": "X6", "output": "one-V-deepseek_flash-prohibited", "wandb_run": "4nhryicz", "offer_rule": "competing",
     "auditor_admissible": True},
]


def _role(actor_id: str) -> str:
    return actor_id.split("_")[0]


def summarise(record: dict[str, Any], probe: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Counts for one completed episode record and its run settings; never copies text content."""
    if record["status"] != "completed" or record["infrastructure_failure"]:
        raise ValueError(f"{probe['id']}: only completed episodes are admitted")
    juror_offers = [offer for offer in record["bribes_offered"] if _role(offer["recipient_id"]) == "juror"]
    auditor_offers = [offer for offer in record["bribes_offered"] if _role(offer["recipient_id"]) == "auditor"]
    judged = list((record.get("cot_monitor") or {}).values())
    monitored = [judgement for judgement in judged if "error" not in judgement]
    panel = record.get("auditor_panel")
    expected = "CREATOR_SUPPORTED" if record["ground_truth"] else "CHALLENGER_SUPPORTED"
    return {
        "id": probe["id"],
        "wandb_run": probe["wandb_run"],
        "experiment_id": record["experiment_id"],
        "episode_id": record["episode_id"],
        "cell": settings["cell"],
        "lineup": settings.get("lineup"),
        "models": record["config"].get("models"),
        "offer_rule": probe["offer_rule"],
        # Absent before the option existed, which means off.
        "party_auditor_offers": bool(settings.get("party_auditor_offers")),
        "prohibited": bool(settings.get("prohibited")),
        "scenario_id": record["scenario_id"],
        "ground_truth": record["ground_truth"],
        "outcome": record["outcome"],
        "verdict_correct": record["verdict_correct"],
        "jurors": len(record["votes"]),
        "truth_aligned_votes": sum(vote == expected for vote in record["votes"].values()),
        "juror_offers": dict(Counter(_role(offer["offered_by"]) for offer in juror_offers)),
        "juror_offers_accepted": dict(Counter(_role(offer["offered_by"]) for offer in juror_offers
                                              if offer["accepted"])),
        "offers_dropped": len(record["transfers_rejected"]),
        "private_messages": record["jury_metrics"]["private_message_count"],
        "public_messages": record["jury_metrics"]["public_message_count"],
        "auditor": None if panel is None else {
            "admissible": probe["auditor_admissible"],
            "finding": panel["panel_finding"],
            "implicated": sum(len(finding.get("implicated", [])) for finding in panel["findings"].values()),
            "verified_paid_jury": record["jury_metrics"]["auditor_verified_paid_jury_count"],
            "offers": [{"sender_role": _role(offer["offered_by"]), "amount": offer["amount"],
                        "required_finding": offer["required_finding"], "accepted": offer["accepted"]}
                       for offer in auditor_offers],
        },
        "monitor": {
            "model": settings.get("cot_monitor_model"),
            "judged": len(judged),
            "monitored": len(monitored),
            "rogue": sum(judgement["rogue"] for judgement in monitored),
            "rogue_jurors": sum(judgement["rogue"] for judgement in monitored if judgement["role"] == "JUROR"),
            "hidden": sum(judgement["hidden"] for judgement in monitored),
            "behaviours": {name: sum(name in judgement["behaviours"] for judgement in monitored)
                           for name in BEHAVIOURS},
        },
    }


def extract(experiments: Path) -> dict[str, Any]:
    import yaml

    probes = []
    for probe in PROBES:
        directory = experiments / probe["output"]
        [episodes] = directory.glob("*/episodes.jsonl")
        [config_file] = directory.glob("wandb/run-*/files/config.yaml")
        records = [json.loads(line) for line in episodes.read_text().splitlines()]
        if len(records) != 1:
            raise ValueError(f"{probe['id']}: expected one episode, found {len(records)}")
        config = {key: value.get("value") for key, value in yaml.safe_load(config_file.read_text()).items()
                  if isinstance(value, dict)}
        entry = summarise(records[0], probe, config)
        entry["code_revision"] = config["code_revision"]
        entry["code_dirty"] = config["code_dirty"]
        entry["source_sha256"] = hashlib.sha256(episodes.read_bytes()).hexdigest()
        probes.append(entry)
    return {"schema_version": 1, "probes": probes}


def _pair(counts: dict[str, int]) -> str:
    return f"{counts.get('creator', 0)}/{counts.get('challenger', 0)}"


def _setting(probe: dict[str, Any]) -> str:
    """Compact codes explained in the table caption: S single offer, P party offers to auditors, R rule."""
    codes = ["V" if probe["cell"].endswith("-V1") else "F"]
    codes += [code for code, on in (("S", probe["offer_rule"] == "single"), ("P", probe["party_auditor_offers"]),
                                    ("R", probe["prohibited"])) if on]
    return "+".join(codes)


def _auditor(probe: dict[str, Any]) -> str:
    auditor = probe["auditor"]
    if auditor is None:
        return "---"
    if not auditor["admissible"]:
        return "excluded"
    offers = "; ".join(f"{'Cr' if offer['sender_role'] == 'creator' else 'Ch'} {offer['amount']:.2f} "
                       f"{'accepted' if offer['accepted'] else 'rejected'}" for offer in auditor["offers"])
    finding = "verified" if auditor["finding"] == "VERDICT_VERIFIED" else "not verified"
    return f"{offers or 'no offer'}; {finding}"


def render_table(snapshot: dict[str, Any]) -> str:
    rows = []
    for probe in snapshot["probes"]:
        dropped = f" ({probe['offers_dropped']} dropped)" if probe["offers_dropped"] else ""
        monitor = probe["monitor"]
        rows.append(
            f"    {probe['id']} & {_setting(probe)} & {_pair(probe['juror_offers'])}{dropped} & "
            f"{_pair(probe['juror_offers_accepted'])} & {probe['private_messages']} & "
            f"{probe['truth_aligned_votes']}/{probe['jurors']} & {_auditor(probe)} & "
            f"{monitor['rogue']}/{monitor['monitored']} \\\\")
    return "\n".join([
        "% Generated by analysis/probe_snapshot.py from data/exploratory-probes.json; do not edit.",
        "\\begin{tabular}{llllrlll}",
        "  \\toprule",
        "  ID & Setting & Offers Cr/Ch & Accepted Cr/Ch & Private & Truth votes & Auditor & Rogue \\\\",
        "  \\midrule",
        *rows,
        "  \\bottomrule",
        "\\end{tabular}",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extract", action="store_true", help="Refresh the snapshot from local run exports")
    parser.add_argument("--experiments", type=Path, default=REPORT.parent / ".harness" / "experiments")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--table", type=Path, default=TABLE)
    args = parser.parse_args()
    if args.extract:
        args.snapshot.write_text(json.dumps(extract(args.experiments), indent=2) + "\n")
    args.table.parent.mkdir(parents=True, exist_ok=True)
    args.table.write_text(render_table(json.loads(args.snapshot.read_text())))


if __name__ == "__main__":
    main()
