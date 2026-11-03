"""Independent read-only verification of public discovery selection evidence."""
import re
import stat
import gzip
import zlib
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from hashlib import sha256

from scripts.sample_backup.jsoncodec import Number, dumps, loads


QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT DISTINCT ?item WHERE {
  ?item p:P5008 ?statement .
  ?statement ps:P5008 wd:Q114241199 ;
             wikibase:rank ?rank .
  VALUES ?rank { wikibase:NormalRank wikibase:PreferredRank }
}
ORDER BY ?item
"""
ENDPOINTS = {"main": "https://query.wikidata.org/sparql",
             "scholarly": "https://query-scholarly.wikidata.org/sparql"}
SETTINGS = {"minimum_gap_seconds": 1, "response_deadline_seconds": 60,
            "max_attempts_per_graph": 3, "retry_backoff_seconds": [5, 10],
            "supported_content_encodings": ["identity", "gzip"], "http_redirect_policy": "reject"}
SELECTION_KEYS = {"format", "format_version", "kind", "criterion", "query", "discovery_settings",
                  "sources", "qid_list", "selected_count", "frozen_at", "parent_selection"}
SOURCE_KEYS = {"graph", "endpoint", "started_at", "finished_at", "outcome", "attempts"}
ATTEMPT_KEYS = {"attempt_id", "request", "started_at", "headers_received_at", "headers_observed",
                "response_received_at", "response_elapsed_ms", "receipt_complete", "finished_at",
                "status_code", "headers", "encoded", "decoded", "next_dispatch_at", "outcome", "error"}
FIXTURE_NULL_FIELDS = {"started_at", "headers_received_at", "headers_observed", "response_received_at",
                       "response_elapsed_ms", "receipt_complete", "finished_at", "status_code", "next_dispatch_at"}
HEADER_NAMES = {"content-type", "content-encoding", "content-length", "retry-after", "date", "etag",
                "last-modified", "location", "x-database-lag"}
ERROR_STAGES = {"selection", "transport", "api", "decoding", "identity", "extraction", "saving", "recovery"}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _keys(value, keys, label):
    _require(isinstance(value, dict) and set(value) == keys, f"invalid {label} keys")


def _integer(value, *, positive=False):
    return isinstance(value, Number) and re.fullmatch(
        r"[1-9][0-9]*" if positive else r"(?:0|[1-9][0-9]*)", value.token)


def _utc(value):
    _require(isinstance(value, str) and re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value),
        "expected UTC timestamp with six fractional digits")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _path(root, name):
    _require(isinstance(name, str) and name and "\\" not in name, "unsafe artifact path")
    relative = PurePosixPath(name)
    _require(not relative.is_absolute() and ".." not in relative.parts and str(relative) == name
             and name != "." and relative.parts[0] != ".state", "unsafe artifact path")
    path = root
    for part in relative.parts:
        path = path / part
        _require(not path.is_symlink(), "symlink in artifact path")
    status = path.stat()
    _require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1,
             "artifact must be a regular file without hard links")
    return path


def _bindings(body):
    value = loads(body)
    _keys(value, {"head", "results"}, "SPARQL response")
    _require(isinstance(value["head"], dict) and value["head"].get("vars") == ["item"],
             "wrong SPARQL variables")
    _keys(value["results"], {"bindings"}, "SPARQL results")
    rows = value["results"]["bindings"]
    _require(isinstance(rows, list), "SPARQL bindings must be an array")
    result = []
    for row in rows:
        _keys(row, {"item"}, "SPARQL binding")
        binding = row["item"]
        _keys(binding, {"type", "value"}, "item binding")
        _require(binding["type"] == "uri" and isinstance(binding["value"], str)
                 and re.fullmatch(r"http://www.wikidata.org/entity/Q[1-9][0-9]*", binding["value"]),
                 "invalid canonical item URI")
        result.append(binding["value"].rsplit("/", 1)[-1])
    return result


def _request(value, endpoint):
    _keys(value, {"method", "url", "parameters", "headers"}, "request")
    _require(value["method"] == "GET" and value["url"] == endpoint,
             "unexpected discovery method/endpoint")
    _require(value["parameters"] == {"query": QUERY, "format": "json"}, "wrong discovery parameters")
    headers = value["headers"]
    _keys(headers, {"Accept", "Accept-Encoding", "User-Agent"}, "request headers")
    _require(headers["Accept"] == "application/sparql-results+json"
             and headers["Accept-Encoding"] == "gzip, identity"
             and isinstance(headers["User-Agent"], str) and headers["User-Agent"].strip()
             and not any(c in headers["User-Agent"] for c in "\r\n"), "invalid discovery identification")


def _observed_attempt(attempt, read_file, owner, *, succeeded, ordinal):
    started, finished = _utc(attempt["started_at"]), _utc(attempt["finished_at"])
    _require(started <= finished, "attempt finishes before it starts")
    _require(type(attempt["headers_observed"]) is bool, "uncertain header receipt prevents freezing")
    headers = attempt["headers"]
    _require(isinstance(headers, dict) and set(headers) <= HEADER_NAMES
             and all(isinstance(values, list) and values
                     and all(isinstance(value, str) for value in values) for values in headers.values()),
             "invalid received header lists")
    receipt_complete = attempt["receipt_complete"]
    _require(receipt_complete is None or type(receipt_complete) is bool, "invalid receipt completeness")
    if attempt["headers_observed"]:
        _require(_integer(attempt["status_code"]) and 100 <= int(attempt["status_code"].token) <= 599,
                 "invalid HTTP status code")
        headers_at = _utc(attempt["headers_received_at"])
        _require(started <= headers_at <= finished, "header time is outside the attempt")
    else:
        _require(attempt["status_code"] is None and headers == {}
                 and attempt["headers_received_at"] is None, "pre-header failure claims received headers")
        headers_at = None
    if receipt_complete is True:
        received = _utc(attempt["response_received_at"])
        _require(headers_at is not None and headers_at <= received <= finished
                 and _integer(attempt["response_elapsed_ms"]), "invalid complete response timing")
        _require(int(attempt["response_elapsed_ms"].token) <= 60000, "response exceeds the total deadline")
    else:
        _require(attempt["response_received_at"] is None and attempt["response_elapsed_ms"] is None,
                 "incomplete receipt claims clean completion")
    encoded = b""
    if attempt["encoded"] is not None:
        encoded = read_file(attempt["encoded"], body=True, owner=owner)
        _require(encoded and attempt["encoded"]["complete"] is receipt_complete,
                 "encoded evidence completeness differs from receipt")
    decoded = None
    if attempt["decoded"] is not None:
        decoded = read_file(attempt["decoded"], body=True, owner=owner)
        _require(decoded, "empty decoded body must not invent an artifact")
    if receipt_complete is True:
        lengths = headers.get("content-length", [])
        _require(not lengths or (len(lengths) == 1 and re.fullmatch(r"[0-9]+", lengths[0])
                                and int(lengths[0]) == len(encoded)), "encoded framing mismatch")
    if decoded is not None and attempt["decoded"]["complete"] is True:
        _require(receipt_complete is True, "complete decoded body lacks complete receipt")
        encodings = headers.get("content-encoding", ["identity"])
        _require(len(encodings) == 1 and encodings[0].strip().lower() in ("identity", "gzip"),
                 "unsupported/ambiguous content encoding")
        try:
            original = gzip.decompress(encoded) if encodings[0].strip().lower() == "gzip" else encoded
        except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
            raise ValueError(f"undecodable encoded discovery evidence: {exc}") from exc
        _require(original == decoded, "encoded body does not decode to preserved result")
    if succeeded:
        _require(attempt["status_code"] == Number("200") and receipt_complete is True
                 and decoded is not None and attempt["decoded"]["complete"] is True
                 and attempt["error"] is None, "successful discovery lacks usable receipt evidence")
        floor = 1
    else:
        error = attempt["error"]
        _keys(error, {"stage", "code", "message", "retryable"}, "discovery error")
        _require(error["stage"] in ERROR_STAGES and isinstance(error["code"], str) and error["code"]
                 and isinstance(error["message"], str) and error["message"]
                 and error["retryable"] is True and attempt["outcome"] == "transient_failure",
                 "history contains a held or untyped retry")
        status = int(attempt["status_code"].token) if isinstance(attempt["status_code"], Number) else None
        _require(status in (429, 500, 502, 503, 504)
                 or (error["stage"] == "transport" and receipt_complete is not True),
                 "history retries a non-transient failure")
        floor = 5 if ordinal == 0 else 10
    next_at = _utc(attempt["next_dispatch_at"])
    _require(next_at >= finished + timedelta(seconds=floor), "discovery cooldown is shorter than policy")
    malformed_wait = False
    for value in headers.get("retry-after", []):
        try:
            if re.fullmatch(r"[0-9]+", value):
                _require(next_at >= finished + timedelta(seconds=int(value)), "Retry-After delay shortened")
            else:
                server_time = parsedate_to_datetime(value)
                if server_time.tzinfo is None:
                    raise ValueError("Retry-After lacks timezone")
                _require(next_at >= server_time, "Retry-After date shortened")
        except (TypeError, OverflowError):
            malformed_wait = True
        except ValueError as exc:
            if str(exc).startswith("Retry-After") and str(exc) != "Retry-After lacks timezone":
                raise
            malformed_wait = True
    if malformed_wait:
        _require(not succeeded and attempt["error"]["code"] == "invalid_retry_after",
                 "malformed Retry-After not explicitly recorded")
    return decoded, started, finished, next_at


def _inventory(root, accounted):
    actual_paths = set()
    for path in root.iterdir():
        _require(not path.is_symlink(), "symlink in selection directory")
        if path.name == ".state":
            _require(path.is_dir(), "internal state must be a directory")
            continue
        candidates = path.rglob("*") if path.is_dir() else (path,)
        for candidate in candidates:
            _require(not candidate.is_symlink(), "symlink in selection payload")
            if candidate.is_dir():
                continue
            _require(stat.S_ISREG(candidate.stat().st_mode), "non-regular selection payload")
            actual_paths.add(candidate.relative_to(root).as_posix())
    _require(actual_paths == set(accounted), "unexpected or unaccounted selection artifacts")


def _verify(root):
    _require(root.is_dir() and not root.is_symlink(), "invalid selection directory")
    metadata = loads(_path(root, "selection.json").read_text(encoding="utf-8"))
    _keys(metadata, SELECTION_KEYS, "selection")
    _require(metadata["format"] == "idea-json-backup" and metadata["format_version"] == "1.0.0",
             "wrong selection format/version")
    _require(metadata["kind"] in ("synthetic", "production"), "unsupported selection kind")
    _require(metadata["parent_selection"] is None, "unexpected parent selection")
    _require(metadata["criterion"] == {"property_id": "P5008", "value_id": "Q114241199",
                                      "ranks": ["normal", "preferred"]}, "wrong selection criterion")
    _require(metadata["discovery_settings"] == loads(dumps(SETTINGS)), "wrong discovery settings")
    accounted = {"selection.json": "metadata"}

    def read_file(descriptor, *, body=False, owner, expected=None):
        _keys(descriptor, {"path", "size_bytes", "sha256", "complete"} if body else
              {"path", "size_bytes", "sha256"}, "file descriptor")
        name = descriptor["path"]
        _require(expected is None or name == expected, "unexpected artifact path")
        path = _path(root, name)
        _require(name not in accounted or accounted[name] == owner, "artifact has multiple owners")
        accounted[name] = owner
        value = path.read_bytes()
        _require(_integer(descriptor["size_bytes"]) and int(descriptor["size_bytes"].token) == len(value),
                 "artifact size mismatch")
        digest = descriptor["sha256"]
        _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                 and sha256(value).hexdigest() == digest, "artifact checksum mismatch")
        if body:
            _require(descriptor["complete"] in (None, True, False)
                     and (descriptor["complete"] is None or type(descriptor["complete"]) is bool),
                     "invalid body completeness type")
        return value

    _require(read_file(metadata["query"], owner="query", expected="query.rq") == QUERY.encode(),
             "query differs from approved explicit-rank query")
    sources = metadata["sources"]
    _require(isinstance(sources, list) and len(sources) == 2, "both graph sources are required")
    if (metadata["frozen_at"] is None and metadata["qid_list"] is None
            and metadata["selected_count"] is None):
        for source, (graph, endpoint) in zip(sources, ENDPOINTS.items()):
            _keys(source, SOURCE_KEYS, "graph source")
            _require(source["graph"] == graph and source["endpoint"] == endpoint
                     and source["outcome"] == "pending" and source["attempts"] == []
                     and source["started_at"] is None and source["finished_at"] is None,
                     "initialized selection has inconsistent or unvalidated graph evidence")
        _inventory(root, accounted)
        return False
    frozen_at = _utc(metadata["frozen_at"])
    union = set()
    attempts_seen = set()
    previous_dispatch_gate = None
    for source, (graph, endpoint) in zip(sources, ENDPOINTS.items()):
        _keys(source, SOURCE_KEYS, "graph source")
        _require(source["graph"] == graph and source["endpoint"] == endpoint
                 and source["outcome"] == "succeeded", "graph source is incomplete or out of order")
        attempts = source["attempts"]
        _require(isinstance(attempts, list) and 1 <= len(attempts) <= 3, "invalid discovery attempt count")
        fixture_mode = (metadata["kind"] == "synthetic" and source["started_at"] is None
                        and source["finished_at"] is None)
        if fixture_mode:
            _require(len(attempts) == 1, "synthetic supplied response has retry history")
            source_started = source_finished = None
        else:
            source_started, source_finished = _utc(source["started_at"]), _utc(source["finished_at"])
            _require(source_started <= source_finished <= frozen_at, "source timing/freeze is out of order")
            _require(previous_dispatch_gate is None or source_started >= previous_dispatch_gate,
                     "graph dispatch evades previous cooldown")
        decoded = None
        for ordinal, attempt in enumerate(attempts):
            _keys(attempt, ATTEMPT_KEYS, "discovery attempt")
            attempt_id = attempt["attempt_id"]
            _require(isinstance(attempt_id, str) and attempt_id and attempt_id not in attempts_seen,
                     "invalid/duplicate discovery attempt ID")
            attempts_seen.add(attempt_id)
            _request(attempt["request"], endpoint)
            last = ordinal == len(attempts) - 1
            _require(attempt["outcome"] == ("succeeded" if last else "transient_failure"),
                     "only final discovery attempt may succeed")
            if fixture_mode:
                _require(all(attempt[field] is None for field in FIXTURE_NULL_FIELDS)
                         and attempt["encoded"] is None and attempt["headers"] == {}
                         and attempt["error"] is None, "synthetic fixture invents HTTP receipt evidence")
                decoded = read_file(attempt["decoded"], body=True, owner=attempt_id)
                _require(attempt["decoded"]["complete"] is True, "incomplete decoded graph result")
            else:
                decoded, started, finished, gate = _observed_attempt(
                    attempt, read_file, attempt_id, succeeded=last, ordinal=ordinal)
                _require(source_started <= started <= finished <= source_finished,
                         "attempt timing falls outside source interval")
                _require(previous_dispatch_gate is None or started >= previous_dispatch_gate,
                         "retry dispatch evades cooldown")
                previous_dispatch_gate = gate
        union.update(_bindings(decoded))
    _require(union, "empty combined selection")
    expected = ("\n".join(sorted(union, key=lambda q: int(q[1:]))) + "\n").encode()
    actual = read_file(metadata["qid_list"], owner="qid-list", expected="qids.txt")
    _require(actual == expected, "frozen QID list differs from numeric source union")
    _require(_integer(metadata["selected_count"], positive=True)
             and int(metadata["selected_count"].token) == len(union), "wrong selected count")
    _inventory(root, accounted)
    return True


def verify_selection(directory):
    """Verify existing evidence without downloading, repairing or rewriting it."""
    try:
        complete = _verify(Path(directory))
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ArithmeticError) as exc:
        return {"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}
    if not complete:
        return {"status": "not_checked", "findings": ["Selection is initialized; both graph queries remain pending"]}
    return {"status": "passed", "findings": []}
