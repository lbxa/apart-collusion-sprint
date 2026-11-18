"""Render pilot mechanics after checking ingestion and terminal archive pins."""

import argparse
import hashlib
import json
from pathlib import Path

from resistance_figures import FAMILIES, SLOTS


def read_verified_pilots(
    directory: Path, *, require_complete_cohort: bool = False
) -> tuple[dict, dict]:
    names = (
        "actor-mechanics.json",
        "assignment-register.json",
        "ingestion-receipt.json",
        "archive-receipt.json",
        "archive-manifest.json",
    )
    raw = {name: (directory / name).read_bytes() for name in names}
    data = {name: json.loads(content) for name, content in raw.items()}
    hashes = {
        name: hashlib.sha256(content).hexdigest() for name, content in raw.items()
    }
    ingestion = data["ingestion-receipt.json"]
    for name in ("actor-mechanics.json", "assignment-register.json"):
        if ingestion["outputs_sha256"][name] != hashes[name]:
            raise ValueError(f"Pilot ingestion pin differs for {name}")
    receipt, manifest = data["archive-receipt.json"], data["archive-manifest.json"]
    if (
        receipt["download_verified"] is not True
        or receipt["manifest_sha256"] != hashes["archive-manifest.json"]
    ):
        raise ValueError("The terminal archive lacks a matching download verification")
    if (
        require_complete_cohort
        and receipt.get("validation_schema") != "collusion-private-audit-v2"
    ):
        raise ValueError("A complete cohort requires the hardened archive receipt")
    if receipt["scope"] != {
        "entity": "lbxa-corp",
        "project": "apart-collusion-sprint",
        "base_url": "https://api.wandb.ai",
    }:
        raise ValueError("Unexpected pilot archive scope")
    frame = data["assignment-register.json"]
    if tuple(slot["model_slot"] for slot in frame["model_slots"]) != SLOTS:
        raise ValueError("The pilot frame must retain all five requested model slots")
    if require_complete_cohort:
        if (
            manifest["schema"] != "collusion-private-audit-v2"
            or manifest["source_gaps"]
        ):
            raise ValueError("The complete pilot cohort has unresolved source coverage")
        if ingestion.get("capability_evidence_gaps"):
            raise ValueError("The complete pilot readout has capability evidence gaps")
        archived_jobs = {job["assignment_id"]: job for job in manifest["assignments"]}
        for assignment in frame["assignments"]:
            archived = archived_jobs.get(assignment["job_id"])
            if archived is None or archived["status"] != "complete" or archived["gaps"]:
                raise ValueError(
                    "The complete pilot cohort has an unverified assignment"
                )
            phase = archived["phase"]
            if (
                manifest["phase_statuses"][phase] != "complete"
                or manifest["phase_gaps"][phase]
            ):
                raise ValueError("The selected pilot phase is not fully verified")
    runs = {row["run_id"]: row for row in manifest["runs"]}
    files = {row["path"]: row for row in manifest["files"]}
    mechanics = {}
    for row in data["actor-mechanics.json"]:
        run = runs.get(row["run_id"])
        if (
            run is None
            or run["status"] != "complete"
            or row["run_status"] != "complete"
        ):
            continue
        prefix = f"runs/{run['path']}/"
        if files[prefix + "run.json"]["original_sha256"] != row["run_manifest_sha256"]:
            raise ValueError("Pilot run-manifest pin differs from the verified archive")
        evidence = prefix + row["episode_id"] + "/evidence.json"
        if files[evidence]["original_sha256"] != row["evidence_sha256"]:
            raise ValueError("Pilot engine evidence differs from the verified archive")
        if not any(
            item["path"].startswith(prefix + "inputs/cases/")
            and item["original_sha256"] == row["source_sha256"]
            for item in manifest["files"]
        ):
            raise ValueError("Pilot source is absent from the verified archive")
        jurors = [
            actor
            for actor in row["actors"]
            if actor["control"] == "evaluated" and actor["role"] == "juror"
        ]
        count = row["evaluated_jurors"]
        if type(count) is not int or count <= 0 or count != len(jurors):
            raise ValueError("Pilot evaluated-juror denominator is inconsistent")
        if (
            sum(actor["committed"] is True for actor in jurors)
            != row["valid_commitments"]
        ):
            raise ValueError("Pilot commitment counts disagree")
        if sum(actor["revealed"] is True for actor in jurors) != row["valid_reveals"]:
            raise ValueError("Pilot reveal counts disagree")
        if not 0 <= row["valid_reveals"] <= row["valid_commitments"] <= count:
            raise ValueError("Pilot action counts are invalid")
        for name in (
            "model_calls",
            "credit_transfer_event_count",
            "input_tokens",
            "output_tokens",
        ):
            if type(row[name]) is not int or row[name] < 0:
                raise ValueError(f"Invalid pilot diagnostic count: {name}")
        eligible = row["valid_reveals"] if row["reference_applicable"] is True else 0
        correct = None
        if eligible:
            wrong = row["wrong_votes"]
            if type(wrong) is not int or not 0 <= wrong <= eligible:
                raise ValueError("Pilot wrong-vote count is invalid")
            correct = eligible - wrong
        mechanics[row["job_id"]] = {
            **row,
            "correct_eligible": correct,
            "eligible_verdicts": eligible,
        }
    if require_complete_cohort and not {
        job["job_id"] for job in frame["assignments"]
    } <= set(mechanics):
        raise ValueError("A complete pilot cohort cannot omit unverified assignments")
    provenance = {
        "input_sha256": hashes,
        "artifact": receipt["artifact"],
        "manifest_sha256": receipt["manifest_sha256"],
        "semantic_labels": "not_reviewed",
        "complete_cohort_required": require_complete_cohort,
    }
    return {"frame": frame, "mechanics": mechanics}, provenance


def render_table(verified: dict, *, expected_seed: int = 700) -> str:
    assignments = verified["frame"]["assignments"]
    rows = []
    outcomes = {
        "ABORTED": "Aborted",
        "SETTLED_CHALLENGER": "Challenger settled",
        "SETTLED_CREATOR": "Creator settled",
    }
    for slot, family in zip(SLOTS, FAMILIES, strict=True):
        selected = [job for job in assignments if job["model_slot"] == slot]
        if (
            len(selected) != 1
            or selected[0]["arm"] != "honest-false"
            or selected[0]["phase"] != "exploratory"
            or selected[0]["seed"] != expected_seed
            or selected[0]["sourcecases"] != ["finance_return"]
        ):
            raise ValueError("Expected one no-offer exploratory pilot per model")
        assignment = selected[0]
        case = verified["mechanics"].get(assignment["job_id"])
        if case is None:
            stage = {
                "running": "Running at snapshot",
                "pending": "Pending at snapshot",
                "complete": "Archive verification pending",
                "failed": "Failed at snapshot",
                "interrupted": "Interrupted at snapshot",
            }.get(assignment["status"], "Status unresolved")
            cells = [
                family,
                f"\\shortstack[l]{{Unadmitted\\\\{stage}}}",
                "---",
                "---",
                "---",
                "---",
            ]
        else:
            case_name = outcomes.get(case["phase"])
            if case_name is None:
                raise ValueError("Unexpected terminal pilot case outcome")
            accuracy = (
                "---"
                if case["correct_eligible"] is None
                else f"{case['correct_eligible']} / {case['eligible_verdicts']}"
            )
            cells = [
                family,
                f"\\shortstack[l]{{Job complete\\\\{case_name}}}",
                f"{case['valid_commitments']} / {case['valid_reveals']}",
                accuracy,
                str(case["model_calls"]),
                str(case["credit_transfer_event_count"]),
            ]
        rows.append(" & ".join(cells) + r"\\")
    return "\n".join(
        [
            r"% Generated from hash-checked pilot mechanics; semantic labels remain unreviewed.",
            r"\begin{tabular}{llllrr}",
            r"\toprule",
            r"Family & Job / case & \shortstack[l]{Commits /\\reveals} & \shortstack[l]{Correct /\\eligible votes} & \shortstack[r]{Recorded\\calls} & Transfers\\",
            r"\midrule",
            *rows,
            r"\bottomrule",
            r"\end{tabular}",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-seed", type=int, default=700)
    parser.add_argument("--require-complete-cohort", action="store_true")
    args = parser.parse_args()
    verified, provenance = read_verified_pilots(
        args.data_dir, require_complete_cohort=args.require_complete_cohort
    )
    table = render_table(verified, expected_seed=args.expected_seed)
    provenance["expected_seed"] = args.expected_seed
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(table)
    args.output.with_suffix(".provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
