"""Immutable selection evidence and numeric union, separate from item collection."""
from datetime import datetime, timezone
from pathlib import Path
import re

from scripts.sample_backup.jsoncodec import dumps, loads

from .files import describe, write_bytes
from .transport import DEFAULT_USER_AGENT

ENDPOINTS = {"main": "https://query.wikidata.org/sparql",
             "scholarly": "https://query-scholarly.wikidata.org/sparql"}
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
SETTINGS = {"minimum_gap_seconds": 1, "response_deadline_seconds": 60,
            "max_attempts_per_graph": 3, "retry_backoff_seconds": [5, 10],
            "supported_content_encodings": ["identity", "gzip"], "http_redirect_policy": "reject"}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def query_request(graph, user_agent=DEFAULT_USER_AGENT):
    return {"method": "GET", "url": ENDPOINTS[graph],
            "parameters": {"query": QUERY, "format": "json"},
            "headers": {"Accept": "application/sparql-results+json", "Accept-Encoding": "gzip, identity",
                        "User-Agent": user_agent}}


def checkpoint(directory, metadata):
    write_bytes(Path(directory) / "selection.json", (dumps(metadata) + "\n").encode(), replace=True)


def new_selection(directory, *, kind="synthetic"):
    if kind not in ("synthetic", "production"):
        raise ValueError("Expected synthetic or production discovery")
    root = Path(directory)
    root.mkdir(parents=True)
    (root / "sources").mkdir()
    (root / ".state").mkdir()
    body = QUERY.encode()
    write_bytes(root / "query.rq", body)
    metadata = {"format": "idea-json-backup", "format_version": "1.0.0", "kind": kind,
                "criterion": {"property_id": "P5008", "value_id": "Q114241199", "ranks": ["normal", "preferred"]},
                "query": describe("query.rq", body), "discovery_settings": dict(SETTINGS),
                "sources": [{"graph": graph, "endpoint": endpoint, "started_at": None,
                             "finished_at": None, "outcome": "pending", "attempts": []}
                            for graph, endpoint in ENDPOINTS.items()],
                "qid_list": None, "selected_count": None, "frozen_at": None, "parent_selection": None}
    checkpoint(root, metadata)
    return metadata


def parse_results(body):
    value = loads(body)
    if (not isinstance(value, dict) or set(value) != {"head", "results"}
            or not isinstance(value["head"], dict) or value["head"].get("vars") != ["item"]
            or not isinstance(value["results"], dict) or set(value["results"]) != {"bindings"}
            or not isinstance(value["results"]["bindings"], list)):
        raise ValueError("Malformed SPARQL result structure")
    qids = []
    for row in value["results"]["bindings"]:
        if (not isinstance(row, dict) or set(row) != {"item"} or not isinstance(row["item"], dict)
                or set(row["item"]) != {"type", "value"} or row["item"]["type"] != "uri"
                or not isinstance(row["item"]["value"], str)
                or not re.fullmatch(r"http://www.wikidata.org/entity/Q[1-9][0-9]*", row["item"]["value"])):
            raise ValueError("Expected a canonical item URI binding")
        qids.append(row["item"]["value"].rsplit("/", 1)[1])
    return qids


def freeze_selection(directory, metadata, *, utcnow=now):
    root = Path(directory)
    if metadata["qid_list"] is not None:
        raise ValueError("Selection is already frozen")
    qids = set()
    for source in metadata["sources"]:
        if source["outcome"] != "succeeded":
            raise ValueError("Both discovery graphs must succeed before freezing")
        attempt = source["attempts"][-1]
        try:
            qids.update(parse_results((root / attempt["decoded"]["path"]).read_bytes()))
        except ValueError as exc:
            source["outcome"] = "failed"
            attempt.update(outcome="review_required", error={"stage": "selection", "code": "invalid_results",
                           "message": str(exc), "retryable": False})
            checkpoint(root, metadata)
            raise
    if not qids:
        raise ValueError("Empty combined selection requires review")
    body = ("\n".join(sorted(qids, key=lambda qid: int(qid[1:]))) + "\n").encode()
    write_bytes(root / "qids.txt", body)
    metadata.update(qid_list=describe("qids.txt", body), selected_count=len(qids), frozen_at=utcnow())
    checkpoint(root, metadata)
    return metadata


def freeze_fixture_responses(main_body, scholarly_body, directory):
    """Build a clearly synthetic bundle; no request/receipt times are invented."""
    root = Path(directory)
    metadata = new_selection(root, kind="synthetic")
    for source, body in zip(metadata["sources"], (main_body, scholarly_body)):
        relative = f"sources/{source['graph']}.json"
        write_bytes(root / relative, body)
        source["attempts"].append({
            "attempt_id": f"{source['graph']}-1", "request": query_request(source["graph"]),
            "started_at": None, "headers_received_at": None, "headers_observed": None,
            "response_received_at": None, "response_elapsed_ms": None, "receipt_complete": None,
            "finished_at": None, "status_code": None, "headers": {}, "encoded": None,
            "decoded": dict(describe(relative, body), complete=True), "next_dispatch_at": None,
            "outcome": "succeeded", "error": None})
        source["outcome"] = "succeeded"
        checkpoint(root, metadata)
    return freeze_selection(root, metadata)
