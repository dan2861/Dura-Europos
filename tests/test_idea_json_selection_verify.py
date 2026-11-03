"""Independent, invented discovery bundles; no producer or network is called."""
import hashlib
import json
import unittest
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


class SelectionVerifierTests(unittest.TestCase):
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
