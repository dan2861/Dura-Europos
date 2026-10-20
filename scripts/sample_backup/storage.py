"""Durable filesystem operations, isolated from retrieval."""
import csv
import hashlib
import io
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import EXPORTER_VERSION
from . import jsoncodec
from .schema import CHECK_IDS, ENDPOINT, HEADERS, ITEM_FIELDS, SCHEMA_VERSION, request_options


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class RunStore:
    def __init__(self, root, manifest):
        self.root = Path(root)
        self.manifest = manifest

    @classmethod
    def create(cls, parent, qids, input_path, *, started=None, suffix=None):
        # Validate again at this boundary: callers cannot bypass preflight.
        qids = list(qids)
        if len(qids) != len(set(qids)) or any(
            not isinstance(q, str) or not re.fullmatch(r"Q[1-9][0-9]*", q) for q in qids
        ):
            raise ValueError("Invalid or duplicate requested QIDs")
        started = started or datetime.now(timezone.utc)
        if started.tzinfo is None:
            raise ValueError("Start time must be timezone-aware")
        started = started.astimezone(timezone.utc)
        suffix = suffix or uuid.uuid4().hex[:12]
        if not re.fullmatch(r"[A-Za-z0-9-]+", suffix):
            raise ValueError("Invalid unique suffix")
        run_id = started.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + suffix
        parent = Path(parent)
        parent.mkdir(parents=True, exist_ok=True)
        root = parent / run_id
        root.mkdir()  # exclusive: never reuse another attempt
        _sync_directory(parent)
        (root / "original").mkdir()
        (root / "failures").mkdir()
        manifest = {
            "run_id": run_id, "schema_version": SCHEMA_VERSION,
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "finished_at": None,
            "scope": {"selection_method": "explicit convenience sample",
                      "input_path": str(input_path), "requested_qids": qids,
                      "requested_count": len(qids), "idea_criterion": "P5008 = Q114241199"},
            "retrieval_method": {"endpoint_template": ENDPOINT, "http_method": "GET",
                                 "request_options": request_options(),
                                 "exporter_version": EXPORTER_VERSION},
            "limitations": ["Convenience sample, not full IDEA coverage",
                            "No media, revision history, linked-entity or external-record retrieval",
                            "Full linked-entity readability and Dataverse readiness not established"],
            "items": [], "outputs": [],
            "validation_summary": {"status": "not_checked", "checks": [
                {"check_id": c, "status": "not_checked", "details": None} for c in CHECK_IDS]},
        }
        for qid in qids:
            entry = dict.fromkeys(ITEM_FIELDS)
            entry.update(requested_qid=qid, retrieval_status="pending",
                         validation_status="not_checked", source_url=ENDPOINT.format(qid=qid),
                         http_trace=[])
            manifest["items"].append(entry)
        store = cls(root, manifest)
        for table in HEADERS:
            store.write_table(table, [])
        store.checkpoint()
        return store

    def path(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("Path must be relative to the run")
        candidate = self.root / relative
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Path escapes run folder")
        cursor = self.root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Symlink in run artifact path")
        return candidate

    def _write(self, relative, body, *, replace=False):
        destination = self.path(relative)
        fd, staging = tempfile.mkstemp(prefix=".staging-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                if stream.write(body) != len(body):
                    raise OSError("Incomplete artifact write")
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                os.replace(staging, destination)
            else:
                os.link(staging, destination)  # atomic no-clobber publication
                os.unlink(staging)
            _sync_directory(destination.parent)
        except BaseException:
            # A crash may leave staging evidence; ordinary exceptions clean up our file.
            if os.path.exists(staging):
                os.unlink(staging)
            raise
        return relative

    def write_table(self, table, rows):
        fields = HEADERS[table]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            if set(row) != set(fields):
                raise ValueError(f"Wrong columns for {table}")
            writer.writerow(row)
        self._write(table + ".csv", stream.getvalue().encode("utf-8"), replace=True)

    def save_original(self, qid, body):
        self._require_requested(qid)
        return self._write(f"original/{qid}.json", body)

    def save_failure(self, qid, body):
        self._require_requested(qid)
        return self._write(f"failures/{qid}.body", body) if body else None

    def _require_requested(self, qid):
        if qid not in self.manifest["scope"]["requested_qids"]:
            raise ValueError("QID not in this attempt's scope")

    def inventory(self):
        outputs = []
        paths = [self.root / (t + ".csv") for t in HEADERS]
        paths += sorted((self.root / "original").glob("*.json"))
        paths += sorted((self.root / "failures").glob("*.body"))
        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            path = self.path(relative)
            if not path.exists():
                continue
            body = path.read_bytes()
            count = None
            if path.suffix == ".csv":
                records = list(csv.reader(io.StringIO(body.decode("utf-8"), newline="")))
                count = len(records) - 1
            outputs.append({"path": relative, "size_bytes": len(body),
                            "sha256": hashlib.sha256(body).hexdigest(), "row_count": count})
        return outputs

    def checkpoint(self):
        self.manifest["outputs"] = self.inventory()
        body = (jsoncodec.dumps(self.manifest) + "\n").encode("utf-8")
        self._write("manifest.json", body, replace=True)
