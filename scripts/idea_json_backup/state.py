"""Durable production journal and explicitly generated public snapshots.

SQLite owns progress and attempt quota. Public JSONL is a projection, never a
source from which a missing or damaged journal can be reconstructed.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import re
import sqlite3
import stat
import sys
from urllib.parse import quote
import uuid

from scripts.sample_backup import jsoncodec as codec

from .contract import valid_utc
from .files import describe, write_bytes, _sync
from .selection_verify import verify_selection
from .transport import DEFAULT_USER_AGENT

MANIFEST_KEYS = {"format", "format_version", "run_id", "run_kind", "exporter_version", "runtime",
                 "selection", "created_at", "started_at", "finished_at", "request_settings",
                 "next_dispatch_at", "phase", "state_sequence", "public_records", "counts",
                 "collection_status", "verification_path", "limitations"}
ATTEMPT_KEYS = {"attempt_id", "requested_qids", "reserved_at", "dispatch_started_at", "headers_received_at",
                "headers_observed", "response_received_at", "response_elapsed_ms", "receipt_complete",
                "finished_at", "recovered_at", "request", "http", "encoded", "decoded", "diagnostics",
                "api_error", "warnings", "outcome", "item_results", "next_eligible_at", "error"}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _encode(value):
    return codec.dumps(value)


def _decode(body):
    """Native schema counters; opaque API values retain all numeric tokens."""
    def native(value):
        if isinstance(value, codec.Number):
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value.token):
                raise ValueError("Non-integer in journal metadata")
            return int(value.token)
        if isinstance(value, list):
            return [native(row) for row in value]
        if isinstance(value, dict):
            return {key: val if key in ("warnings", "api_error") else native(val)
                    for key, val in value.items()}
        return value
    return native(codec.loads(body))


def request_settings(user_agent=DEFAULT_USER_AGENT):
    if (not isinstance(user_agent, str) or not user_agent.strip()
            or any(c in user_agent for c in "\r\n")):
        raise ValueError("Invalid identifying User-Agent")
    return {"endpoint": "https://www.wikidata.org/w/api.php",
            "action_parameters": {"action": "wbgetentities", "format": "json", "formatversion": "2",
                                  "redirects": "no", "maxlag": "5"},
            "headers": {"Accept": "application/json", "Accept-Encoding": "gzip, identity", "User-Agent": user_agent},
            "batch_size": 50, "concurrency": 1, "minimum_gap_seconds": 1, "response_deadline_seconds": 60,
            "max_attempts_per_item": 3, "retry_backoff_seconds": [5, 10],
            "supported_content_encodings": ["identity", "gzip"], "http_redirect_policy": "reject"}


class RunState:
    def __init__(self, root, *, now_fn=utc_now):
        self.root = Path(root)
        self.now = now_fn
        self.db = None
        self._lock = None
        self._source_cache = None

    @classmethod
    def create(cls, selection_dir, run_dir, *, user_agent=DEFAULT_USER_AGENT, now_fn=utc_now):
        selection = Path(selection_dir)
        settings = request_settings(user_agent)
        report = verify_selection(selection)
        if report["status"] != "passed":
            raise ValueError("Selection did not pass independent verification: " + "; ".join(report["findings"]))
        selected = _decode((selection / "selection.json").read_bytes())
        qids = (selection / "qids.txt").read_text(encoding="utf-8").splitlines()
        obj = cls(run_dir, now_fn=now_fn)
        obj.root.mkdir(parents=True)
        _sync(obj.root.parent)
        (obj.root / ".state").mkdir()
        for name in ("selection", "items", "responses", "diagnostics"):
            (obj.root / name).mkdir()
        try:
            obj._acquire()
            obj._copy_selection(selection)
            if verify_selection(obj.root / "selection")["status"] != "passed":
                raise ValueError("Copied selection changed during initialization")
            obj._connect(create=True)
            obj.db.executescript("""
                CREATE TABLE run (id INTEGER PRIMARY KEY CHECK(id=1), record TEXT NOT NULL);
                CREATE TABLE items (qid TEXT PRIMARY KEY, ordinal INTEGER NOT NULL UNIQUE,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT, record TEXT NOT NULL);
                CREATE INDEX item_eligibility ON items(state,next_at,ordinal);
                CREATE TABLE attempts (sequence INTEGER PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE, record TEXT NOT NULL);
                CREATE TABLE attempt_items (attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    qid TEXT NOT NULL REFERENCES items(qid), ordinal INTEGER NOT NULL,
                    PRIMARY KEY(attempt_id,qid));
                CREATE INDEX attempt_qid ON attempt_items(qid);
            """)
            created = obj.now()
            if not valid_utc(created):
                raise ValueError("Invalid run creation timestamp")
            run_id = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%Y%m%dT%H%M%S.%fZ")
            run_id += "-" + uuid.uuid4().hex[:12]
            metadata_body = (obj.root / "selection/selection.json").read_bytes()
            qid_body = (obj.root / "selection/qids.txt").read_bytes()
            manifest = {
                "format": "idea-json-backup", "format_version": "1.0.0", "run_id": run_id,
                "run_kind": selected["kind"], "exporter_version": "0.1.0",
                "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                            "platform": platform.system()},
                "selection": {"metadata": describe("selection/selection.json", metadata_body),
                              "qid_list": describe("selection/qids.txt", qid_body), "selected_count": len(qids)},
                "created_at": created, "started_at": None, "finished_at": None,
                "request_settings": settings, "next_dispatch_at": None, "phase": "initialized",
                "state_sequence": 0, "public_records": {},
                "counts": {"selected": len(qids), "pending": len(qids), "accepted": 0, "unresolved": 0},
                "collection_status": "not_checked", "verification_path": None,
                "limitations": ["Items are preserved over a collection period, not one historical instant",
                                "Media bytes, full revision history and recursive linked entities are excluded"],
            }
            with obj._transaction():
                obj.db.execute("INSERT INTO run VALUES(1,?)", (_encode(manifest),))
                obj.db.executemany("INSERT INTO items(qid,ordinal,state,record) VALUES(?,?,?,?)", [
                    (qid, ordinal, "pending", _encode({
                        "requested_qid": qid, "returned_qid": None, "status": "pending", "lastrevid": None,
                        "modified": None, "retrieved_at": None, "item": None, "source_response_id": None,
                        "source_entity_key": None, "attempt_ids": [], "membership_at_retrieval": "not_checked",
                        "next_eligible_at": None, "error": None})) for ordinal, qid in enumerate(qids)])
            _sync(obj.root / ".state")
            obj.snapshot()
            return obj
        except BaseException:
            obj.close()
            raise

    @classmethod
    def open(cls, run_dir, *, now_fn=utc_now):
        obj = cls(run_dir, now_fn=now_fn)
        try:
            if not obj.root.is_dir() or obj.root.is_symlink():
                raise ValueError("Invalid run directory")
            obj._acquire()
            obj._connect(create=False)
            obj._audit_journal()
            obj._audit_selection()
            obj._audit_accepted()
            return obj
        except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
            obj.close()
            raise ValueError(f"Cannot reopen authoritative journal: {exc}") from exc

    def _acquire(self):
        directory = self.root / ".state"
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("Missing or unsafe local state directory")
        lock_path = directory / "lock"
        if lock_path.is_symlink():
            raise ValueError("Unsafe run lock")
        self._lock = lock_path.open("a+b")
        fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _connect(self, *, create):
        path = self.root / ".state/state.sqlite"
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
            raise ValueError("Unsafe journal path")
        if create:
            if path.exists():
                raise FileExistsError("Journal already exists")
            self.db = sqlite3.connect(path, isolation_level=None)
        else:
            if not path.is_file():
                raise ValueError("Authoritative journal is missing")
            self.db = sqlite3.connect("file:" + quote(str(path.resolve())) + "?mode=rw", uri=True,
                                      isolation_level=None)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=EXTRA")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA fullfsync=ON")
        if (self.db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete"
                or self.db.execute("PRAGMA synchronous").fetchone()[0] != 3
                or self.db.execute("PRAGMA foreign_keys").fetchone()[0] != 1):
            raise ValueError("Required SQLite durability settings unavailable")
        if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Journal integrity check failed")

    def _copy_selection(self, selection):
        for path in selection.rglob("*"):
            relative = path.relative_to(selection)
            if relative.parts[0] == ".state":
                continue
            if path.is_symlink():
                raise ValueError("Symlink in selection payload")
            destination = self.root / "selection" / relative
            if path.is_dir():
                destination.mkdir(exist_ok=True)
            else:
                if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1:
                    raise ValueError("Nonregular selection payload")
                write_bytes(destination, path.read_bytes())

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    @property
    def manifest(self):
        row = self.db.execute("SELECT record FROM run WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Missing authoritative run metadata")
        return _decode(row[0])

    def _put_manifest(self, value):
        self.db.execute("UPDATE run SET record=? WHERE id=1", (_encode(value),))

    def _advance(self):
        manifest = self.manifest
        manifest["state_sequence"] += 1
        self._put_manifest(manifest)

    def _mutable(self):
        if self.manifest["phase"] == "finalized":
            raise ValueError("Finalized collection is immutable")

    def set_run(self, **fields):
        self._mutable()
        if set(fields) - MANIFEST_KEYS:
            raise ValueError("Unknown public run fields")
        immutable = {"format", "format_version", "run_id", "run_kind", "exporter_version", "runtime",
                     "selection", "created_at", "request_settings", "state_sequence", "counts", "public_records"}
        if set(fields) & immutable:
            raise ValueError("Immutable journal settings cannot change")
        with self._transaction():
            manifest = self.manifest
            manifest.update(fields)
            self._put_manifest(manifest)

    def items(self):
        return [_decode(row[0]) for row in self.db.execute("SELECT record FROM items ORDER BY ordinal")]

    def get_item(self, qid):
        row = self.db.execute("SELECT record FROM items WHERE qid=?", (qid,)).fetchone()
        if row is None:
            raise ValueError("QID outside the frozen selection")
        return _decode(row[0])

    def attempts(self):
        return [_decode(row[0]) for row in self.db.execute("SELECT record FROM attempts ORDER BY sequence")]

    def get_attempt(self, attempt_id):
        row = self.db.execute("SELECT record FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown attempt")
        return _decode(row[0])

    def _put_item(self, value):
        self.db.execute("UPDATE items SET state=?,next_at=?,record=? WHERE qid=?",
                        (value["status"], value["next_eligible_at"], _encode(value), value["requested_qid"]))

    def eligible(self, now):
        if not valid_utc(now):
            raise ValueError("Invalid eligibility timestamp")
        if self.manifest["phase"] == "finalized":
            return []
        qids = []
        for row in self.db.execute("SELECT qid,record FROM items WHERE state!='accepted' AND attempts<3 "
                                   "AND (next_at IS NULL OR next_at<=?) ORDER BY ordinal", (now,)):
            item = _decode(row[1])
            if item["status"] == "unresolved" and not (item["error"] or {}).get("retryable", False):
                continue
            active = self.db.execute("SELECT a.record FROM attempts a JOIN attempt_items l USING(attempt_id) "
                                     "WHERE l.qid=? ORDER BY a.sequence DESC LIMIT 1", (row[0],)).fetchone()
            if active is not None and _decode(active[0])["outcome"] == "reserved":
                continue
            qids.append(row[0])
            if len(qids) == 50:
                break
        return qids

    def reserve(self, qids, request):
        self._mutable()
        if (not isinstance(qids, (list, tuple)) or not 1 <= len(qids) <= 50
                or len(set(qids)) != len(qids)):
            raise ValueError("Expected distinct eligible QIDs")
        qids = list(qids)
        eligible = self.eligible(self.now())
        if any(qid not in eligible for qid in qids) or qids != [qid for qid in eligible if qid in qids]:
            raise ValueError("Attempt contains ineligible QID, wrong order or exhausted quota")
        settings = self.manifest["request_settings"]
        expected = {"method": "GET", "url": settings["endpoint"], "headers": settings["headers"],
                    "parameters": dict(settings["action_parameters"], ids="|".join(qids))}
        if request != expected:
            raise ValueError("Request differs from frozen run settings")
        with self._transaction():
            number = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM attempts").fetchone()[0]
            attempt_id = f"A{number:06d}"
            record = {"attempt_id": attempt_id, "requested_qids": qids, "reserved_at": self.now(),
                      "dispatch_started_at": None, "headers_received_at": None, "headers_observed": None,
                      "response_received_at": None, "response_elapsed_ms": None, "receipt_complete": None,
                      "finished_at": None, "recovered_at": None, "request": request, "http": None,
                      "encoded": None, "decoded": None, "diagnostics": [], "api_error": None, "warnings": None,
                      "outcome": "reserved", "item_results": [
                          {"qid": qid, "outcome": "unknown", "returned_qid": None, "error": None} for qid in qids],
                      "next_eligible_at": None, "error": None}
            self.db.execute("INSERT INTO attempts VALUES(?,?,?)", (number, attempt_id, _encode(record)))
            for ordinal, qid in enumerate(qids):
                self.db.execute("INSERT INTO attempt_items VALUES(?,?,?)", (attempt_id, qid, ordinal))
                self.db.execute("UPDATE items SET attempts=attempts+1 WHERE qid=?", (qid,))
                item = self.get_item(qid)
                item["attempt_ids"].append(attempt_id)
                self._put_item(item)
            self._advance()
        return self.get_attempt(attempt_id)

    def dispatch(self, attempt_id):
        self._mutable()
        record = self.get_attempt(attempt_id)
        if record["outcome"] != "reserved" or record["dispatch_started_at"] is not None:
            raise ValueError("Attempt was already dispatched or completed")
        with self._transaction():
            stamp = self.now()
            record["dispatch_started_at"] = stamp
            self.db.execute("UPDATE attempts SET record=? WHERE attempt_id=?", (_encode(record), attempt_id))
            manifest = self.manifest
            manifest.update(phase="collecting", started_at=manifest["started_at"] or stamp, finished_at=None)
            self._put_manifest(manifest)
            self._advance()

    def record_attempt(self, attempt_id, record):
        self._mutable()
        previous = self.get_attempt(attempt_id)
        if not isinstance(record, dict) or set(record) != ATTEMPT_KEYS:
            raise ValueError("Invalid attempt record shape")
        for field in ("attempt_id", "requested_qids", "reserved_at", "request", "dispatch_started_at"):
            if not codec.equal(record[field], previous[field]):
                raise ValueError("Attempt reservation/request identity cannot change")
        if record["outcome"] not in {"reserved", "succeeded", "mixed", "transient_failure", "review_required",
                                     "interrupted", "saving_failure"}:
            raise ValueError("Invalid attempt outcome")
        with self._transaction():
            self.db.execute("UPDATE attempts SET record=? WHERE attempt_id=?", (_encode(record), attempt_id))
            self._advance()

    def unresolve(self, qid, error, *, returned_qid=None, next_eligible_at=None):
        self._mutable()
        if (not isinstance(error, dict) or set(error) != {"stage", "code", "message", "retryable"}
                or type(error["retryable"]) is not bool):
            raise ValueError("Invalid unresolved error")
        if next_eligible_at is not None and not valid_utc(next_eligible_at):
            raise ValueError("Invalid retry eligibility time")
        with self._transaction():
            item = self.get_item(qid)
            if item["status"] == "accepted":
                raise ValueError("Accepted item is immutable")
            manifest = self.manifest
            old_state = item["status"]
            item.update(status="unresolved", returned_qid=returned_qid,
                        next_eligible_at=next_eligible_at, error=error)
            self._put_item(item)
            if old_state != "unresolved":
                manifest["counts"][old_state] -= 1
                manifest["counts"]["unresolved"] += 1
            self._put_manifest(manifest)
            self._advance()

    def path(self, relative, *, parents=False):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("Unsafe artifact path")
        value = PurePosixPath(relative)
        if value.is_absolute() or ".." in value.parts or str(value) != relative or relative == ".":
            raise ValueError("Unsafe artifact path")
        cursor = self.root
        for part in value.parts:
            cursor /= part
            if cursor.is_symlink() or (cursor.exists() and cursor.is_file() and cursor.stat().st_nlink != 1):
                raise ValueError("Linked artifact path")
        if parents:
            cursor.parent.mkdir(parents=True, exist_ok=True)
        return cursor

    def publish(self, relative, body, complete=None):
        self._mutable()
        path = self.path(relative, parents=True)
        write_bytes(path, body)
        descriptor = describe(relative, body)
        if complete is not None:
            descriptor["complete"] = complete
        return descriptor

    def snapshot(self):
        self._mutable()
        manifest = self.manifest
        records = {}
        for name, rows in (("inventory", self.items()), ("attempts", self.attempts())):
            body = b"".join((_encode(row) + "\n").encode("utf-8") for row in rows)
            relative = name + ".jsonl"
            write_bytes(self.root / relative, body, replace=True)
            records[name] = {"file": describe(relative, body), "state_sequence": manifest["state_sequence"]}
        manifest["public_records"] = records
        write_bytes(self.root / "manifest.json", (_encode(manifest) + "\n").encode("utf-8"), replace=True)
        with self._transaction():
            self._put_manifest(manifest)
        return manifest

    def pause(self):
        self.set_run(phase="paused", finished_at=None)
        return self.snapshot()

    def collected(self):
        self.set_run(phase="collected", finished_at=self.now())
        return self.snapshot()

    def _audit_journal(self):
        manifest = self.manifest
        if set(manifest) != MANIFEST_KEYS or manifest["format"] != "idea-json-backup" or manifest["format_version"] != "1.0.0":
            raise ValueError("Invalid journal metadata contract")
        if manifest["request_settings"] != request_settings(manifest["request_settings"]["headers"]["User-Agent"]):
            raise ValueError("Journal request settings changed")
        foreign = self.db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            raise ValueError("Broken attempt/item links")
        items = self.items()
        qids = [item["requested_qid"] for item in items]
        if qids != (self.root / "selection/qids.txt").read_text(encoding="utf-8").splitlines():
            raise ValueError("Journal scope differs from frozen selection")
        counts = {"selected": len(items), "pending": 0, "accepted": 0, "unresolved": 0}
        for item in items:
            if item["status"] not in ("pending", "accepted", "unresolved"):
                raise ValueError("Invalid item state")
            counts[item["status"]] += 1
            links = [row[0] for row in self.db.execute(
                "SELECT l.attempt_id FROM attempt_items l JOIN attempts a USING(attempt_id) WHERE l.qid=? ORDER BY a.sequence",
                (item["requested_qid"],))]
            stored = self.db.execute("SELECT attempts FROM items WHERE qid=?", (item["requested_qid"],)).fetchone()[0]
            if links != item["attempt_ids"] or stored != len(links) or len(links) > 3:
                raise ValueError("Attempt quota/link mismatch")
        if manifest["counts"] != counts:
            raise ValueError("Journal counts disagree")

    def _read_descriptor(self, descriptor):
        path = self.path(descriptor["path"])
        if not path.is_file():
            raise ValueError("Accepted artifact is missing")
        body = path.read_bytes()
        if len(body) != descriptor["size_bytes"] or hashlib.sha256(body).hexdigest() != descriptor["sha256"]:
            raise ValueError("Immutable artifact checksum mismatch")
        return body

    def _audit_selection(self):
        manifest = self.manifest
        for field in ("metadata", "qid_list"):
            self._read_descriptor(manifest["selection"][field])
        report = verify_selection(self.root / "selection")
        if report["status"] != "passed":
            raise ValueError("Copied frozen selection is corrupt")

    def _audit_accepted(self):
        # Acceptance/source proof is added in the next separately reviewed increment.
        if any(item["status"] == "accepted" for item in self.items()):
            raise ValueError("Accepted-item audit not yet implemented")

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self._lock is not None:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
            self._lock.close()
            self._lock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
