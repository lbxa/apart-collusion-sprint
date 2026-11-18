import io
import json
import tarfile

from veracity_harness.runner import retain_shared


def archive(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, kind, payload in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.SYMTYPE:
                info.linkname = payload
                tar.addfile(info)
            elif kind == tarfile.REGTYPE:
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            else:
                tar.addfile(info)
    return buffer.getvalue()


def test_snapshot_keeps_only_regular_files_and_records_what_it_skipped(tmp_path):
    data = archive(
        [
            ("./cases", tarfile.DIRTYPE, None),
            ("./cases/case-1.md", tarfile.REGTYPE, b"Case record"),
            ("./notes.txt", tarfile.REGTYPE, b"agent note"),
            ("./outside", tarfile.SYMTYPE, "/etc/passwd"),
            ("./pipe", tarfile.FIFOTYPE, None),
            ("../escape.txt", tarfile.REGTYPE, b"escape"),
        ]
    )
    target = tmp_path / "round-001"
    digest = retain_shared(data, target, previous=None)
    assert digest
    assert (target / "cases/case-1.md").read_bytes() == b"Case record"
    assert (target / "notes.txt").read_bytes() == b"agent note"
    assert not (target / "outside").exists() and not (target / "outside").is_symlink()
    assert not (target / "pipe").exists()
    assert not (tmp_path / "escape.txt").exists()
    skipped = json.loads((tmp_path / "round-001.skipped.json").read_text())
    assert {item["name"] for item in skipped} == {"./outside", "./pipe", "../escape.txt"}


def test_unchanged_cache_writes_no_new_snapshot(tmp_path):
    data = archive([("./cases/case-1.md", tarfile.REGTYPE, b"Case record")])
    first = retain_shared(data, tmp_path / "round-001", previous=None)
    assert retain_shared(data, tmp_path / "round-002", previous=first) == first
    assert not (tmp_path / "round-002").exists()
