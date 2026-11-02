"""Small durable, no-clobber artifact store for one prototype run."""
import hashlib
import os
import tempfile
from pathlib import Path

from scripts.sample_backup.jsoncodec import dumps


def _sync(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_bytes(path, body, *, replace=False):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if stream.write(body) != len(body):
                raise OSError("Incomplete artifact write")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        _sync(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def describe(relative, body):
    return {"path": relative, "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


class Run:
    def __init__(self, directory, qids, provenance):
        self.root = Path(directory)
        self.root.mkdir(parents=True)  # exclusive: prior attempts are immutable
        (self.root / "items").mkdir()
        _sync(self.root.parent)
        self.manifest = {
            "format": "idea-json-backup-mvp", "version": 1, "status": "incomplete",
            "requested_qids": qids, "provenance": provenance, "source": None,
            "items": [{"qid": qid, "status": "unresolved", "revision": None,
                       "modified": None, "file": None, "error": "not_processed"} for qid in qids],
            "error": "preservation has not completed", "evidence": [],
        }
        self.checkpoint()

    def checkpoint(self):
        write_bytes(self.root / "manifest.json", (dumps(self.manifest) + "\n").encode(), replace=True)

    def artifact(self, relative, body):
        write_bytes(self.root / relative, body)
        return describe(relative, body)

    def source(self, body):
        self.manifest["source"] = self.artifact("source.json", body)
        self.checkpoint()

    def accept(self, entry, entity):
        entry["file"] = self.artifact(f"items/{entry['qid']}.json", dumps(entity).encode("utf-8"))
        entry.update(status="saved", revision=entity["lastrevid"], modified=entity["modified"], error=None)
        self.checkpoint()

    def fail(self, exc, entry=None):
        message = f"{type(exc).__name__}: {exc}"
        self.manifest.update(status="incomplete", error=message)
        if entry is not None and entry["status"] != "saved":
            entry["error"] = message
        self.checkpoint()

    def finish(self):
        self.manifest.update(status="collected", error=None)
        self.checkpoint()
        return self.manifest
