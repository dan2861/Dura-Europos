"""Independent, invented discovery bundles; no producer or network is called."""
import hashlib
import copy
import gzip
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.selection_verify import verify_selection


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
ENDPOINTS = ["https://query.wikidata.org/sparql", "https://query-scholarly.wikidata.org/sparql"]
SETTINGS = {"minimum_gap_seconds": 1, "response_deadline_seconds": 60,
            "max_attempts_per_graph": 3, "retry_backoff_seconds": [5, 10],
            "supported_content_encodings": ["identity", "gzip"], "http_redirect_policy": "reject"}
TIME = "2026-11-03T12:00:00.000000Z"


def result(qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + q}}
        for q in qids]}}).encode()


def store(root, name, body, **extra):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return dict(path=name, size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), **extra)


def write_metadata(root, metadata):
    (root / "selection.json").write_text(json.dumps(metadata) + "\n")


def fixture(root, main=("Q10", "Q2", "Q2"), scholarly=("Q2", "Q1")):
    root.mkdir()
    metadata = {"format": "idea-json-backup", "format_version": "1.0.0", "kind": "synthetic",
                "criterion": {"property_id": "P5008", "value_id": "Q114241199", "ranks": ["normal", "preferred"]},
                "query": store(root, "query.rq", QUERY.encode()), "discovery_settings": dict(SETTINGS),
                "sources": [], "qid_list": None, "selected_count": None,
                "frozen_at": TIME, "parent_selection": None}
    for graph, endpoint, qids in zip(("main", "scholarly"), ENDPOINTS, (main, scholarly)):
        attempt = {"attempt_id": graph + "-1", "request": {"method": "GET", "url": endpoint,
                   "parameters": {"query": QUERY, "format": "json"},
                   "headers": {"Accept": "application/sparql-results+json", "Accept-Encoding": "gzip, identity",
                               "User-Agent": "Invented-Test/1 (https://example.org/contact)"}},
                   "started_at": None, "headers_received_at": None, "headers_observed": None,
                   "response_received_at": None, "response_elapsed_ms": None, "receipt_complete": None,
                   "finished_at": None, "status_code": None, "headers": {}, "encoded": None,
                   "decoded": store(root, "sources/" + graph + ".json", result(qids), complete=True),
                   "next_dispatch_at": None, "outcome": "succeeded", "error": None}
        metadata["sources"].append({"graph": graph, "endpoint": endpoint, "started_at": None,
                                    "finished_at": None, "outcome": "succeeded", "attempts": [attempt]})
    qids = sorted(set(main) | set(scholarly), key=lambda q: int(q[1:]))
    metadata["qid_list"] = store(root, "qids.txt", ("\n".join(qids) + "\n").encode())
    metadata["selected_count"] = len(qids)
    write_metadata(root, metadata)
    return metadata


def at(seconds):
    return (datetime(2026, 11, 3, 12, tzinfo=timezone.utc) + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")


def production_fixture(root, *, compressed=False, kind="production"):
    metadata = fixture(root)
    metadata.update(kind=kind, frozen_at=at(20))
    for source, start in zip(metadata["sources"], (6, 9)):
        source.update(started_at=at(start), finished_at=at(start + 2))
        attempt = source["attempts"][0]
        raw = (root / attempt["decoded"]["path"]).read_bytes()
        encoded = gzip.compress(raw, mtime=0) if compressed else raw
        attempt.update(started_at=at(start), headers_received_at=at(start + 1), headers_observed=True,
                       response_received_at=at(start + 1), response_elapsed_ms=1000,
                       receipt_complete=True, finished_at=at(start + 2), status_code=200,
                       headers={"content-encoding": ["gzip" if compressed else "identity"],
                                "content-length": [str(len(encoded))]},
                       encoded=store(root, "sources/" + source["graph"] + ".encoded", encoded, complete=True),
                       next_dispatch_at=at(start + 3))
    write_metadata(root, metadata)
    return metadata


class SelectionVerifierTests(unittest.TestCase):
    def test_hardlinked_public_evidence_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            fixture(root)
            os.link(root / "sources/main.json", Path(directory) / "outside-link.json")
            self.assertEqual(verify_selection(root)["status"], "failed")

    def test_production_receipts_and_synthetic_injected_receipts_pass(self):
        for compressed, kind in ((False, "production"), (True, "production"), (True, "synthetic")):
            with self.subTest(compressed=compressed, kind=kind), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                production_fixture(root, compressed=compressed, kind=kind)
                self.assertEqual(verify_selection(root), {"status": "passed", "findings": []})

    def test_corrupt_production_receipt_fails_closed(self):
        changes = [lambda m: m["sources"][0]["attempts"][0].update(status_code=True),
                   lambda m: m["sources"][0]["attempts"][0].update(headers_observed=False),
                   lambda m: m["sources"][0]["attempts"][0].update(response_elapsed_ms=True),
                   lambda m: m["sources"][0]["attempts"][0].update(receipt_complete=False),
                   lambda m: m["sources"][0]["attempts"][0].update(response_received_at=at(4)),
                   lambda m: m["sources"][0]["attempts"][0].update(next_dispatch_at=at(7)),
                   lambda m: m["sources"][0].update(finished_at=at(5)),
                   lambda m: m.update(frozen_at=at(10)),
                   lambda m: m["sources"][0]["attempts"][0]["headers"].update(**{"content-length": ["9999"]}),
                   lambda m: m["sources"][0]["attempts"][0]["headers"].update(**{"content-encoding": ["gzip", "identity"]}),
                   lambda m: m["sources"][0]["attempts"][0]["request"]["parameters"].update(format="xml")]
        for change in changes:
            with self.subTest(change=change), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                metadata = production_fixture(root)
                change(metadata)
                write_metadata(root, metadata)
                self.assertEqual(verify_selection(root)["status"], "failed")

    def test_changed_encoded_body_fails_even_after_refreshed_descriptor(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            metadata = production_fixture(root, compressed=True)
            attempt = metadata["sources"][0]["attempts"][0]
            encoded = gzip.compress(result(["Q99"]), mtime=0)
            attempt["encoded"] = store(root, attempt["encoded"]["path"], encoded, complete=True)
            attempt["headers"]["content-length"] = [str(len(encoded))]
            write_metadata(root, metadata)
            self.assertEqual(verify_selection(root)["status"], "failed")

    def test_retained_transient_history_is_checked_without_parsing_error_body_as_results(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            metadata = production_fixture(root)
            source = metadata["sources"][0]
            failed = copy.deepcopy(source["attempts"][0])
            failed.update(attempt_id="main-failed", started_at=at(0), headers_received_at=at(0.1),
                          response_received_at=at(0.2), response_elapsed_ms=200,
                          finished_at=at(0.3), status_code=503, next_dispatch_at=at(5.3),
                          headers={"content-length": ["4"], "retry-after": ["5"]},
                          encoded=store(root, "sources/main-failed.body", b"busy", complete=True),
                          decoded=store(root, "sources/main-failed.decoded", b"busy", complete=True),
                          outcome="transient_failure", error={"stage": "transport", "code": "http_status",
                                                               "message": "HTTP 503", "retryable": True})
            source.update(started_at=at(0), attempts=[failed, source["attempts"][0]])
            write_metadata(root, metadata)
            self.assertEqual(verify_selection(root)["status"], "passed")
            failed["error"]["retryable"] = False
            write_metadata(root, metadata)
            self.assertEqual(verify_selection(root)["status"], "failed")

    def test_independent_fixture_passes_without_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            fixture(root)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(verify_selection(root), {"status": "passed", "findings": []})
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_empty_scholarly_and_more_than_fifty_items_pass(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            fixture(root, main=tuple(f"Q{i}" for i in range(60, 0, -1)), scholarly=())
            self.assertEqual(verify_selection(root)["status"], "passed")

    def test_changed_union_fails_after_recomputed_descriptor(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            metadata = fixture(root)
            metadata["qid_list"] = store(root, "qids.txt", b"Q1\nQ10\n")
            metadata["selected_count"] = 2
            write_metadata(root, metadata)
            self.assertEqual(verify_selection(root)["status"], "failed")

    def test_metadata_and_query_contract_fail_closed(self):
        changes = [lambda m: m.update(selected_count=True), lambda m: m.update(frozen_at=None),
                   lambda m: m.update(kind="production"), lambda m: m["criterion"].update(ranks=["preferred"]),
                   lambda m: m["sources"].reverse(), lambda m: m["sources"][0].update(outcome="failed"),
                   lambda m: m["sources"][0].update(endpoint="https://example.org/sparql"),
                   lambda m: m["sources"][0]["attempts"][0]["decoded"].update(complete=False),
                   lambda m: m.update(unapproved_field="x")]
        for change in changes:
            with self.subTest(change=change), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                metadata = fixture(root)
                change(metadata)
                write_metadata(root, metadata)
                self.assertEqual(verify_selection(root)["status"], "failed")
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            metadata = fixture(root)
            metadata["query"] = store(root, "query.rq", (QUERY + "LIMIT 1\n").encode())
            write_metadata(root, metadata)
            self.assertEqual(verify_selection(root)["status"], "failed")

    def test_invalid_source_fails_after_recomputed_descriptor(self):
        for body in (b'{}', result(["Q01"]), result(["Q1"]).replace(b'"uri"', b'"literal"')):
            with self.subTest(body=body), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                metadata = fixture(root)
                metadata["sources"][0]["attempts"][0]["decoded"] = store(
                    root, "sources/main.json", body, complete=True)
                write_metadata(root, metadata)
                self.assertEqual(verify_selection(root)["status"], "failed")

    def test_paths_extra_files_and_symlinks_fail(self):
        for mode in ("escape", "extra", "symlink", "manifest_symlink"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                metadata = fixture(root)
                if mode == "escape":
                    metadata["sources"][0]["attempts"][0]["decoded"]["path"] = "../outside.json"
                    write_metadata(root, metadata)
                elif mode == "extra":
                    (root / "unexpected.json").write_text("{}")
                elif mode == "symlink":
                    path = root / "sources/main.json"
                    original = path.read_bytes()
                    path.unlink()
                    outside = Path(directory) / "outside.json"
                    outside.write_bytes(original)
                    path.symlink_to(outside)
                else:
                    outside = Path(directory) / "metadata.json"
                    (root / "selection.json").rename(outside)
                    (root / "selection.json").symlink_to(outside)
                self.assertEqual(verify_selection(root)["status"], "failed")

    def test_internal_state_is_excluded_but_not_symlinked(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            fixture(root)
            (root / ".state").mkdir()
            (root / ".state/receipt.json").write_text("internal recovery record")
            self.assertEqual(verify_selection(root)["status"], "passed")
            (root / ".state/receipt.json").unlink()
            (root / ".state").rmdir()
            (root / ".state").symlink_to(Path(directory), target_is_directory=True)
            self.assertEqual(verify_selection(root)["status"], "failed")
