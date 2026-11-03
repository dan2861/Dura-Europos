"""Offline pilot subsets retaining a byte-identical complete production parent."""
from datetime import datetime, timezone
from pathlib import Path
import re
import stat

from scripts.sample_backup.jsoncodec import dumps, loads

from .files import _sync, describe, write_bytes
from .selection_verify import verify_selection


def _copy_public(source, destination, *, omit=()):
    for top in source.iterdir():
        if top.name == ".state" or top.name in omit:
            continue
        if top.is_symlink():
            raise ValueError("Symlink appeared while copying parent")
        paths = top.rglob("*") if top.is_dir() else (top,)
        for path in paths:
            if path.is_symlink():
                raise ValueError("Symlink appeared while copying parent")
            if path.is_dir():
                continue
            status = path.stat()
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                raise ValueError("Parent public payload must be regular unlinked files")
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_bytes(target, path.read_bytes())


def create_pilot_selection(parent_dir, qids, output_dir):
    """Create a fresh labeled subset; never fetch data or modify the parent."""
    parent, output = Path(parent_dir), Path(output_dir)
    if (not isinstance(qids, (list, tuple)) or not qids
            or any(not isinstance(qid, str) or not re.fullmatch(r"Q[1-9][0-9]*", qid) for qid in qids)
            or len(set(qids)) != len(qids)):
        raise ValueError("Expected a nonempty distinct canonical QID subset")
    if output.resolve().is_relative_to(parent.resolve()):
        raise ValueError("Pilot output must not modify its immutable parent directory")
    if verify_selection(parent)["status"] != "passed":
        raise ValueError("Production parent must pass independent verification")
    metadata = loads((parent / "selection.json").read_bytes())
    if metadata["kind"] != "production":
        raise ValueError("Pilot parent must be a production selection")
    parent_qids = (parent / "qids.txt").read_bytes()
    if not set(qids) <= set(parent_qids.decode("ascii").splitlines()):
        raise ValueError("Requested pilot QID is outside the frozen parent")
    output.mkdir(parents=True)
    _sync(output.parent)
    copied_parent = output / "parent"
    copied_parent.mkdir()
    _copy_public(parent, copied_parent)
    if verify_selection(copied_parent)["status"] != "passed":
        raise ValueError("Copied parent differs from its verified evidence")
    _copy_public(copied_parent, output, omit=("selection.json", "qids.txt"))
    body = ("\n".join(sorted(qids, key=lambda qid: int(qid[1:]))) + "\n").encode("ascii")
    write_bytes(output / "qids.txt", body)
    metadata.update(kind="pilot", frozen_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    qid_list=describe("qids.txt", body), selected_count=len(qids), parent_selection={
                        "metadata": describe("parent/selection.json", (copied_parent / "selection.json").read_bytes()),
                        "qid_list": describe("parent/qids.txt", parent_qids),
                        "selected_count": metadata["selected_count"]})
    write_bytes(output / "selection.json", (dumps(metadata) + "\n").encode("utf-8"))
    if verify_selection(output)["status"] != "passed":
        raise ValueError("Pilot subset failed independent verification")
    return metadata
