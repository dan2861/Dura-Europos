"""Read-only verification of the MVP's public files, independent of extraction."""
import hashlib
import gzip
import re
import stat
import zlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlsplit

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


def _protocol_receipts(qids, provenance, evidence, source_body):
    required = {"request.json", "transport.json", "encoded.body"}
    protocol_present = bool({"request.json", "transport.json"} & evidence.keys())
    if not protocol_present and provenance["kind"] != "live":
        return
    _require(required <= evidence.keys(), "transport protocol evidence is missing")
    request = loads(evidence["request.json"])
    receipt = loads(evidence["transport.json"])
    _require(isinstance(request, dict) and isinstance(receipt, dict),
             "invalid request/transport receipt")
    _require(request.get("method") == "GET", "request must use GET")
    url = request.get("url")
    _require(isinstance(url, str), "request URL is missing")
    parsed = urlsplit(url)
    _require((parsed.scheme, parsed.netloc, parsed.path, parsed.fragment) ==
             ("https", "www.wikidata.org", "/w/api.php", ""), "wrong request endpoint")
    parameters = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    expected = {"action": "wbgetentities", "ids": "|".join(qids), "format": "json",
                "formatversion": "2", "redirects": "no", "maxlag": "5"}
    _require(len(parameters) == len(expected) and dict(parameters) == expected,
             "request parameters differ from the frozen batch contract")
    headers = request.get("headers")
    _require(isinstance(headers, dict) and set(headers) ==
             {"Accept", "Accept-Encoding", "User-Agent"}
             and headers["Accept"] == "application/json"
             and headers["Accept-Encoding"] == "gzip, identity"
             and isinstance(headers["User-Agent"], str) and headers["User-Agent"].strip()
             and not any(c in headers["User-Agent"] for c in "\r\n"),
             "invalid request identification/headers")
    timeout = request.get("timeout_seconds")
    _require(isinstance(timeout, Number), "request deadline must be numeric")
    timeout = Decimal(timeout.token)
    _require(timeout.is_finite() and 0 < timeout <= 60, "invalid request deadline")
    _require(_same(receipt.get("status"), Number("200"))
             and receipt.get("complete") is True and receipt.get("error") is None
             and receipt.get("interrupted") is False
             and receipt.get("encoded_path") == "encoded.body", "unsuccessful transport receipt")
    times = [receipt.get(name) for name in
             ("started_at", "headers_received_at", "received_at")]
    _require(all(_utc(value) for value in times), "invalid transport timestamps")
    started, headers_at, received = [datetime.fromisoformat(value.replace("Z", "+00:00"))
                                    for value in times]
    _require(started <= headers_at <= received, "transport timestamps are out of order")
    if provenance["kind"] == "live":
        _require(provenance["retrieved_at"] == times[2], "live retrieval time differs from receipt")
    headers = receipt.get("headers")
    allowed = {"content-length", "content-type", "content-encoding", "retry-after", "location"}
    _require(isinstance(headers, dict) and set(headers) <= allowed
             and all(isinstance(value, str) for value in headers.values()),
             "invalid received headers")
    encoded = evidence["encoded.body"]
    length = headers.get("content-length")
    _require(length is None or (re.fullmatch(r"[0-9]+", length)
                               and int(length) == len(encoded)), "transport framing length mismatch")
    encoding = headers.get("content-encoding", "identity").strip().lower()
    _require(encoding in ("identity", "gzip"), "unsupported transport content encoding")
    try:
        decoded = gzip.decompress(encoded) if encoding == "gzip" else encoded
    except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise ValueError(f"undecodable gzip transport evidence: {exc}") from exc
    _require(decoded == source_body, "encoded transport body differs from decoded source")


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

    source_body = file_bytes(manifest.get("source"), "source.json")
    source = loads(source_body)
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
    evidence_bodies = {descriptor.get("path"): file_bytes(descriptor)
                       for descriptor in evidence if isinstance(descriptor, dict)}
    _require(len(evidence_bodies) == len(evidence), "invalid evidence descriptors")
    _protocol_receipts(qids, provenance, evidence_bodies, source_body)

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
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ArithmeticError) as exc:
        return {"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}
    return {"status": "passed", "findings": []}
