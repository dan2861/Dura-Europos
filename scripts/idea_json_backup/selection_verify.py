"""Independent read-only verification of public discovery selection evidence."""
import re
import stat
from datetime import datetime
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
    _require(stat.S_ISREG(path.stat().st_mode), "artifact is not a regular file")
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


def _verify(root):
    _require(root.is_dir() and not root.is_symlink(), "invalid selection directory")
    metadata = loads(_path(root, "selection.json").read_text(encoding="utf-8"))
    _keys(metadata, SELECTION_KEYS, "selection")
    _require(metadata["format"] == "idea-json-backup" and metadata["format_version"] == "1.0.0",
             "wrong selection format/version")
    _require(metadata["kind"] == "synthetic", "production selection requires observed receipt evidence")
    _require(metadata["parent_selection"] is None, "unexpected parent selection")
    _require(metadata["criterion"] == {"property_id": "P5008", "value_id": "Q114241199",
                                      "ranks": ["normal", "preferred"]}, "wrong selection criterion")
    _require(metadata["discovery_settings"] == loads(dumps(SETTINGS)), "wrong discovery settings")
    _utc(metadata["frozen_at"])
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
    union = set()
    attempts_seen = set()
    for source, (graph, endpoint) in zip(sources, ENDPOINTS.items()):
        _keys(source, SOURCE_KEYS, "graph source")
        _require(source["graph"] == graph and source["endpoint"] == endpoint
                 and source["outcome"] == "succeeded", "graph source is incomplete or out of order")
        _require(source["started_at"] is None and source["finished_at"] is None,
                 "synthetic fixture invents source timing")
        attempts = source["attempts"]
        _require(isinstance(attempts, list) and len(attempts) == 1, "synthetic fixture needs one supplied response")
        attempt = attempts[0]
        _keys(attempt, ATTEMPT_KEYS, "discovery attempt")
        attempt_id = attempt["attempt_id"]
        _require(isinstance(attempt_id, str) and attempt_id and attempt_id not in attempts_seen,
                 "invalid/duplicate discovery attempt ID")
        attempts_seen.add(attempt_id)
        _request(attempt["request"], endpoint)
        _require(all(attempt[field] is None for field in FIXTURE_NULL_FIELDS)
                 and attempt["encoded"] is None and attempt["headers"] == {},
                 "synthetic fixture invents HTTP receipt evidence")
        _require(attempt["outcome"] == "succeeded" and attempt["error"] is None,
                 "discovery attempt did not succeed")
        decoded = read_file(attempt["decoded"], body=True, owner=attempt_id)
        _require(attempt["decoded"]["complete"] is True, "incomplete decoded graph result")
        union.update(_bindings(decoded))
    _require(union, "empty combined selection")
    expected = ("\n".join(sorted(union, key=lambda q: int(q[1:]))) + "\n").encode()
    actual = read_file(metadata["qid_list"], owner="qid-list", expected="qids.txt")
    _require(actual == expected, "frozen QID list differs from numeric source union")
    _require(_integer(metadata["selected_count"], positive=True)
             and int(metadata["selected_count"].token) == len(union), "wrong selected count")
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


def verify_selection(directory):
    """Verify existing evidence without downloading, repairing or rewriting it."""
    try:
        _verify(Path(directory))
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ArithmeticError) as exc:
        return {"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}
    return {"status": "passed", "findings": []}
