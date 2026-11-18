"""Amend only a stopped campaign's authorized cap and its tracking identity.

Run with PYTHONPATH selecting the original frozen harness. This operator helper
never dispatches assignments, edits ledger rows, or recovers running worlds.
Backups and the journal audit retain both identities for independent review.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from veracity_harness.campaign import CampaignJournal, CampaignLock, FrozenCampaign, freeze_plan


def authorized_ledger(path: Path, old_cap: Decimal, new_cap: Decimal, authorization: str):
    """Read the existing cap authorization and aggregate holds without changing them."""
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        campaign = db.execute("SELECT limit_usd,halted FROM campaign").fetchall()
        if len(campaign) != 1 or Decimal(campaign[0][0]) != new_cap:
            raise ValueError("Ledger must already have the newly authorized cap")
        if campaign[0][1]:
            raise ValueError("A halted ledger cannot be amended")
        try:
            amendments = db.execute(
                "SELECT rowid,created_at,previous_limit_usd,new_limit_usd,authorization "
                "FROM cap_amendments ORDER BY rowid"
            ).fetchall()
        except sqlite3.OperationalError as error:
            raise ValueError("Ledger cap authorization is missing") from error
        matching = [
            row
            for row in amendments
            if (
                Decimal(row[2]) == old_cap
                and Decimal(row[3]) == new_cap
                and row[4] == authorization
            )
        ]
        if not matching:
            raise ValueError("Matching ledger cap authorization is missing")
        requests = db.execute("SELECT accounted_usd,status FROM requests").fetchall()
    snapshot = {
        "limit_usd": str(new_cap),
        "accounted_usd": str(sum((Decimal(row[0]) for row in requests), Decimal(0))),
        "charged_usd": str(
            sum((Decimal(cost) for cost, status in requests if status == "charged"), Decimal(0))
        ),
        "usage_bounded_usd": str(
            sum(
                (Decimal(cost) for cost, status in requests if status == "usage_bounded"),
                Decimal(0),
            )
        ),
        "usage_bounded_requests": sum(status == "usage_bounded" for _, status in requests),
        "requests": len(requests),
        "unresolved_requests": sum(status == "reserved" for _, status in requests),
    }
    return matching[-1], snapshot


def amend(
    output: Path,
    plan: Path,
    old_cap: Decimal,
    new_cap: Decimal,
    authorization: str,
    backup_directory: Path,
):
    if (
        not old_cap.is_finite()
        or old_cap <= 0
        or not new_cap.is_finite()
        or new_cap <= old_cap
        or not authorization.strip()
    ):
        raise ValueError("A finite cap increase and explicit authorization are required")
    output = output.resolve(strict=True)
    journal_path = output / "campaign.sqlite"
    if not journal_path.is_file():
        raise ValueError("Existing campaign journal is required")
    with CampaignLock(output), sqlite3.connect(journal_path, timeout=30) as db:
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
        jobs = db.execute("SELECT * FROM jobs ORDER BY position").fetchall()
        if db.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0]:
            raise ValueError("Campaign has running jobs; no automatic recovery is permitted")
        previous = FrozenCampaign.model_validate_json(metadata["frozen"])
        old = freeze_plan(plan, old_cap)
        if old != previous or metadata["fingerprint"] != old.fingerprint:
            raise ValueError("Original frozen campaign differs from the journal")
        new = freeze_plan(plan, new_cap)
        if (
            old.model_dump(exclude={"budget_usd", "fingerprint"})
            != new.model_dump(exclude={"budget_usd", "fingerprint"})
            or old.fingerprint == new.fingerprint
        ):
            raise ValueError("A cap amendment may change only budget and campaign fingerprint")
        old_id = old.name + "-" + old.fingerprint[:16]
        new_id = new.name + "-" + new.fingerprint[:16]
        if metadata["campaign_id"] != old_id:
            raise ValueError("Original campaign tracking identity differs from frozen inputs")
        ledger = Path(metadata["ledger"]).resolve(strict=True)
        receipt, spending = authorized_ledger(ledger, old_cap, new_cap, authorization)
        marker = output / "campaign-tracking.json"
        retained_files = {}
        for name in ("progress.json", "campaign-tracking.json", "tracking/progress.json"):
            path = output / name
            if path.is_file():
                retained_files[name] = path.read_bytes()
        if marker.is_file():
            tracking = json.loads(retained_files["campaign-tracking.json"])
            if tracking.get("campaign_id") != old_id or tracking.get("fingerprint") not in (
                None,
                old.fingerprint,
            ):
                raise ValueError("Existing tracking marker names another campaign")
        backup = backup_directory.resolve()
        backup.mkdir(parents=True, mode=0o700, exist_ok=False)
        with sqlite3.connect(backup / "campaign.sqlite") as recovery:
            db.backup(recovery)
            if recovery.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Journal recovery backup failed integrity verification")
            if (
                dict(recovery.execute("SELECT key,value FROM metadata")) != metadata
                or recovery.execute("SELECT * FROM jobs ORDER BY position").fetchall() != jobs
            ):
                raise ValueError("Journal recovery backup differs from inspected rows")
        (backup / "campaign.sqlite").chmod(0o600)
        hashes = {
            "campaign.sqlite": hashlib.sha256((backup / "campaign.sqlite").read_bytes()).hexdigest()
        }
        for name, data in retained_files.items():
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open("xb") as file:
                file.write(data)
            if target.read_bytes() != data:
                raise ValueError("Recovery file backup verification failed")
            hashes[name] = hashlib.sha256(data).hexdigest()
        backup_manifest = {
            "created_utc": datetime.now(UTC).isoformat(),
            "files_sha256": hashes,
            "previous_campaign_id": old_id,
            "new_campaign_id": new_id,
            "previous_fingerprint": old.fingerprint,
            "new_fingerprint": new.fingerprint,
            "authorization": authorization,
            "ledger_cap_amendment": receipt,
        }
        with (backup / "backup-manifest.json").open("x") as file:
            json.dump(backup_manifest, file, sort_keys=True)
            file.write("\n")
        new_frozen = new.model_dump_json()
        expected = {
            **metadata,
            "fingerprint": new.fingerprint,
            "frozen": new_frozen,
            "campaign_id": new_id,
        }
        db.execute("BEGIN IMMEDIATE")
        if (
            dict(db.execute("SELECT key,value FROM metadata")) != metadata
            or db.execute("SELECT * FROM jobs ORDER BY position").fetchall() != jobs
        ):
            raise ValueError("Journal changed after backup; no amendment applied")
        db.execute(
            "CREATE TABLE IF NOT EXISTS operator_cap_amendments ("
            "created_utc TEXT NOT NULL,previous_cap_usd TEXT NOT NULL,new_cap_usd TEXT NOT NULL,"
            "authorization TEXT NOT NULL,ledger_receipt TEXT NOT NULL,"
            "previous_campaign_id TEXT NOT NULL,new_campaign_id TEXT NOT NULL,"
            "previous_fingerprint TEXT NOT NULL,new_fingerprint TEXT NOT NULL,"
            "previous_frozen TEXT NOT NULL,new_frozen TEXT NOT NULL,backup_directory TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO operator_cap_amendments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.now(UTC).isoformat(),
                str(old_cap),
                str(new_cap),
                authorization,
                json.dumps(receipt),
                old_id,
                new_id,
                old.fingerprint,
                new.fingerprint,
                metadata["frozen"],
                new_frozen,
                str(backup),
            ),
        )
        db.executemany(
            "UPDATE metadata SET value=? WHERE key=?",
            [
                (new.fingerprint, "fingerprint"),
                (new_frozen, "frozen"),
                (new_id, "campaign_id"),
            ],
        )
        if (
            dict(db.execute("SELECT key,value FROM metadata")) != expected
            or db.execute("SELECT * FROM jobs ORDER BY position").fetchall() != jobs
        ):
            raise ValueError("Cap amendment changed protected journal rows")
        db.commit()
        if "campaign-tracking.json" in retained_files:
            data = retained_files["campaign-tracking.json"]
            if (
                marker.read_bytes() != data
                or (backup / "campaign-tracking.json").read_bytes() != data
            ):
                raise ValueError("Tracking marker changed; stop for manual recovery")
            marker.unlink()
        snapshot = CampaignJournal(journal_path).snapshot()
        snapshot.update(spending=spending, tracking_status="awaiting_restart")
        with tempfile.NamedTemporaryFile(
            mode="w", dir=output, prefix=".cap-progress-", delete=False
        ) as file:
            json.dump(snapshot, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        Path(file.name).replace(output / "progress.json")
        return backup_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--old-cap-usd", type=Decimal, required=True)
    parser.add_argument("--new-cap-usd", type=Decimal, required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--backup-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        result = amend(
            args.campaign,
            args.plan,
            args.old_cap_usd,
            args.new_cap_usd,
            args.authorization,
            args.backup_directory,
        )
        print(json.dumps({"event": "campaign_cap_amended", **result}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as error:
        parser.error(f"Cap amendment failed ({type(error).__name__}); inspect recovery evidence")


if __name__ == "__main__":
    raise SystemExit(main())
