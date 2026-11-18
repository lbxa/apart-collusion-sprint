"""Package complete recorded experiment data without publishing or truncating it."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import dotenv_values

from .analysis import RunRecord


def export_raw(campaign: Path, output: Path, *, secret_values: tuple[str, ...] = ()) -> Path:
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    experiments = output / "experiments"
    experiments.mkdir(exist_ok=True, mode=0o700)
    entries = []
    originals = []
    needles = [value.encode() for value in secret_values if value]
    reviews_path = Path(__file__).resolve().parents[2] / "research/reviews.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else []
    for manifest_path in sorted(campaign.glob("*/run.json")):
        raw_manifest = json.loads(manifest_path.read_bytes())
        run = RunRecord.model_validate(raw_manifest)
        if run.run_id != manifest_path.parent.name:
            raise ValueError("Run manifest and directory must identify the same experiment")
        sources = sorted(path for path in manifest_path.parent.rglob("*") if path.is_file())
        hashes = {}
        for path in sources:
            digest = hashlib.sha256()
            overlap = b""
            with path.open("rb") as source:
                while chunk := source.read(1_048_576):
                    block = overlap + chunk
                    if any(needle in block for needle in needles):
                        raise ValueError("Credential material detected; raw export stopped")
                    digest.update(chunk)
                    overlap = block[-max((len(needle) for needle in needles), default=1) :]
            hashes[str(path.relative_to(manifest_path.parent))] = digest.hexdigest()
            originals.append(path)
        destination = experiments / f"{run.run_id}.json"
        annotations = [review for review in reviews if review["run_id"] == run.run_id]
        with destination.open("w", encoding="utf-8") as target:
            target.write('{"run_id":')
            json.dump(run.run_id, target)
            target.write(',"manifest":')
            json.dump(raw_manifest, target)
            target.write(',"annotations":')
            json.dump(annotations, target)
            target.write(',"source_sha256":')
            json.dump(hashes, target)
            target.write(',"recorded_json":{')
            first_file = True
            for path in sources:
                if path.suffix not in {".json", ".jsonl"}:
                    continue
                if not first_file:
                    target.write(",")
                first_file = False
                json.dump(str(path.relative_to(manifest_path.parent)), target)
                target.write(":")
                if path.suffix == ".json":
                    json.dump(json.loads(path.read_bytes()), target, separators=(",", ":"))
                else:
                    target.write("[")
                    first_row = True
                    with path.open(encoding="utf-8") as source:
                        for line in source:
                            if not line.strip():
                                continue
                            row = json.loads(line)
                            if not first_row:
                                target.write(",")
                            first_row = False
                            json.dump(row, target, separators=(",", ":"))
                    target.write("]")
            target.write('},"recorded_text":')
            text_files = {
                str(path.relative_to(manifest_path.parent)): path.read_text(encoding="utf-8")
                for path in sources
                if path.suffix in {".md", ".txt", ".py"}
            }
            json.dump(text_files, target, ensure_ascii=True)
            target.write("}\n")
        entries.append(
            {
                "run_id": run.run_id,
                "experiment": run.config.name,
                "model": run.config.model.name,
                "seed": run.config.seed,
                "treatment": run.config.treatment.model_dump(),
                "status": run.status,
                "assigned_episodes": run.config.episodes,
                "terminal_episodes": len(run.episodes),
                "episodes": [episode.model_dump() for episode in run.episodes],
                "annotations": annotations,
                "json_file": str(destination.relative_to(output)),
                "json_bytes": destination.stat().st_size,
            }
        )
    index = output / "campaign-index.json"
    index.write_text(json.dumps({"experiments": entries}, indent=2) + "\n")
    archive = output / "raw-data.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.write(index, index.name)
        for entry in entries:
            path = output / entry["json_file"]
            bundle.write(path, entry["json_file"])
        for path in originals:
            bundle.write(path, "originals/" + str(path.relative_to(campaign)))
        if (campaign / "spending.sqlite").exists():
            bundle.write(campaign / "spending.sqlite", "originals/spending.sqlite")
        if (campaign / "analysis.json").exists():
            bundle.write(campaign / "analysis.json", "analysis.json")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dotenv", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    values = {**(dotenv_values(args.dotenv) if args.dotenv else {}), **os.environ}
    secrets = tuple(
        values[name]
        for name in ("OPENROUTER_API_KEY", "OPENROUTER_BACKUP_API_KEY", "CLOUDFLARE_API_TOKEN")
        if values.get(name)
    )
    print(export_raw(args.campaign.resolve(), args.output.resolve(), secret_values=secrets))


if __name__ == "__main__":
    main()
