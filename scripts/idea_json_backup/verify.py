"""Read-only verification of the MVP's public files, independent of extraction."""
import hashlib
import re
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath

from scripts.sample_backup.jsoncodec import Number, loads


QID = re.compile(r"Q[1-9][0-9]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, *, positive=False):
    return isinstance(value, Number) and bool(re.fullmatch(
        r"[1-9][0-9]*" if positive else r"(?:0|[1-9][0-9]*)", value.token))


def _utc(value):
    if not isinstance(value, str) or not UTC.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _same(left, right):
    """Object order may differ; types, arrays and number tokens may not."""
    if type(left) is not type(right):
        return False
    if isinstance(left, Number):
        return left.token == right.token
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right))
    return left == right


def _regular_path(root, name):
    _require(isinstance(name, str) and name and "\\" not in name,
             "unsafe artifact path")
    relative = PurePosixPath(name)
    _require(not relative.is_absolute() and ".." not in relative.parts
             and str(relative) == name and name != ".", "unsafe artifact path")
    path = root
    for part in relative.parts:
        path = path / part
        _require(not path.is_symlink(), f"symlink artifact: {name}")
    _require(stat.S_ISREG(path.stat().st_mode), f"not a regular file: {name}")
    return path


def _verify(root):
    _require(root.is_dir() and not root.is_symlink(), "invalid run directory")
    manifest = loads(_regular_path(root, "manifest.json").read_bytes())
    _require(isinstance(manifest, dict), "manifest must be an object")
    _require(manifest.get("format") == "idea-json-backup-mvp"
             and _same(manifest.get("version"), Number("1")), "wrong MVP format/version")
    _require(manifest.get("status") == "collected" and manifest.get("error") is None,
             "run is incomplete or has an error")
    qids = manifest.get("requested_qids")
    _require(isinstance(qids, list) and 1 <= len(qids) <= 50
             and all(isinstance(q, str) and QID.fullmatch(q) for q in qids)
             and len(set(qids)) == len(qids), "invalid requested scope")
    provenance = manifest.get("provenance")
    _require(isinstance(provenance, dict)
             and provenance.get("kind") in ("synthetic", "saved", "live")
             and isinstance(provenance.get("description"), str)
             and provenance["description"].strip(), "invalid provenance")
    if provenance["kind"] == "live":
        _require(_utc(provenance.get("retrieved_at")), "live retrieval time missing/invalid")
    else:
        _require(provenance.get("retrieved_at") is None,
                 "fixture/saved provenance cannot invent a retrieval time")

    accounted = {"manifest.json"}

    def file_bytes(descriptor, expected=None):
        _require(isinstance(descriptor, dict), "missing file descriptor")
        name = descriptor.get("path")
        _require(expected is None or name == expected, "unexpected descriptor path")
        path = _regular_path(root, name)
        _require(name not in accounted, f"duplicate artifact descriptor: {name}")
        accounted.add(name)
        body = path.read_bytes()
        size, digest = descriptor.get("size_bytes"), descriptor.get("sha256")
        _require(_integer(size) and int(size.token) == len(body), f"size mismatch: {name}")
        _require(isinstance(digest, str) and SHA256.fullmatch(digest)
                 and hashlib.sha256(body).hexdigest() == digest, f"checksum mismatch: {name}")
        return body

    source = loads(file_bytes(manifest.get("source"), "source.json"))
    _require(isinstance(source, dict) and _same(source.get("success"), Number("1"))
             and not any(key in source for key in ("error", "warnings", "redirects")),
             "source response is not usable")
    entities = source.get("entities")
    _require(isinstance(entities, dict) and set(entities) == set(qids),
             "source entity scope differs from requested scope")
    items = manifest.get("items")
    _require(isinstance(items, list) and len(items) == len(qids)
             and all(isinstance(entry, dict) for entry in items)
             and [entry.get("qid") for entry in items] == qids,
             "manifest item scope/order differs from requested scope")
    for qid, entry in zip(qids, items):
        _require(entry.get("status") == "saved" and entry.get("error") is None,
                 f"item is unresolved: {qid}")
        entity = entities[qid]
        _require(isinstance(entity, dict) and entity.get("id") == qid
                 and entity.get("type") == "item"
                 and not any(key in entity for key in ("missing", "redirect", "redirects", "error")),
                 f"invalid source item: {qid}")
        _require(_integer(entity.get("lastrevid"), positive=True)
                 and _utc(entity.get("modified")), f"invalid revision metadata: {qid}")
        _require(_same(entry.get("revision"), entity["lastrevid"])
                 and entry.get("modified") == entity["modified"],
                 f"manifest revision metadata differs: {qid}")
        saved = loads(file_bytes(entry.get("file"), f"items/{qid}.json"))
        _require(_same(saved, entity), f"item content differs from original source: {qid}")

    evidence = manifest.get("evidence")
    _require(isinstance(evidence, list), "invalid evidence inventory")
    for descriptor in evidence:
        file_bytes(descriptor)
    if provenance["kind"] == "live":
        _require(bool(evidence), "live provenance lacks transport evidence")

    actual = set()
    for path in root.rglob("*"):
        _require(not path.is_symlink(), "symlink in run payload")
        if path.is_dir():
            continue
        _require(stat.S_ISREG(path.stat().st_mode), "non-regular run artifact")
        actual.add(path.relative_to(root).as_posix())
    _require(actual == accounted, "unexpected or unaccounted run artifacts")


def verify_run(directory):
    """Return findings without fetching, repairing, or changing any file."""
    try:
        _verify(Path(directory))
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        return {"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}
    return {"status": "passed", "findings": []}
