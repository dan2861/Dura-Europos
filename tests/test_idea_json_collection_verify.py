"""Independent invented public collection records; no store or collector used."""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.sample_backup.jsoncodec import Number, dumps, loads
from test_idea_json_selection_verify import fixture as selection_fixture

TIME = "2026-11-03T12:00:00.000000Z"
HEADERS = {"Accept": "application/json", "Accept-Encoding": "gzip, identity",
           "User-Agent": "Invented-Test/1 (https://example.org/contact)"}
PARAMETERS = {"action": "wbgetentities", "format": "json", "formatversion": "2",
              "redirects": "no", "maxlag": "5"}
ENTITY = (b'{"id":"Q1","type":"item","lastrevid":7,"modified":"2026-11-03T11:00:00Z",'
          b'"unknown":{"identifier":"0007","number":1.2300000000000000000001,"flag":true},'
          b'"claims":{"P5008":[{"rank":"normal","mainsnak":{"snaktype":"value",'
          b'"datavalue":{"type":"wikibase-entityid","value":{"entity-type":"item","id":"Q114241199"}}}}]}}')


def store(root, name, body, **extra):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return dict(path=name, size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), **extra)


def write_json(root, name, value):
    return store(root, name, (dumps(value) + "\n").encode())


def rewrite(root, manifest, inventory, attempts):
    for name, records in (("inventory", inventory), ("attempts", attempts)):
        descriptor = store(root, name + ".jsonl", b"".join((dumps(row) + "\n").encode() for row in records))
        manifest["public_records"][name]["file"] = descriptor
    write_json(root, "manifest.json", manifest)


def fixture(root):
    root.mkdir()
    selection_fixture(root / "selection", main=("Q1",), scholarly=())
    selection = {"metadata": store(root, "selection/selection.json", (root / "selection/selection.json").read_bytes()),
                 "qid_list": store(root, "selection/qids.txt", b"Q1\n"), "selected_count": 1}
    source = b'{"success":1,"entities":{"Q1":' + ENTITY + b'}}'
    source_descriptor = store(root, "responses/A000001.json", source, complete=True)
    attempt = {"attempt_id": "A000001", "requested_qids": ["Q1"], "reserved_at": TIME,
               "dispatch_started_at": "2026-11-03T12:00:01.000000Z",
               "headers_received_at": "2026-11-03T12:00:02.000000Z", "headers_observed": True,
               "response_received_at": "2026-11-03T12:00:02.000000Z", "response_elapsed_ms": 1000,
               "receipt_complete": True, "finished_at": "2026-11-03T12:00:03.000000Z", "recovered_at": None,
               "request": {"method": "GET", "url": "https://www.wikidata.org/w/api.php",
                           "parameters": dict(PARAMETERS, ids="Q1"), "headers": dict(HEADERS)},
               "http": {"status_code": 200, "headers": {"content-encoding": ["identity"],
                        "content-length": [str(len(source))]}},
               "encoded": source_descriptor, "decoded": dict(source_descriptor), "diagnostics": [],
               "api_error": None, "warnings": None, "outcome": "succeeded",
               "item_results": [{"qid": "Q1", "outcome": "accepted", "returned_qid": "Q1", "error": None}],
               "next_eligible_at": None, "error": None}
    inventory = [{"requested_qid": "Q1", "returned_qid": "Q1", "status": "accepted", "lastrevid": 7,
                  "modified": "2026-11-03T11:00:00Z", "retrieved_at": attempt["response_received_at"],
                  "item": store(root, "items/Q1.json", ENTITY), "source_response_id": "A000001",
                  "source_entity_key": "Q1", "attempt_ids": ["A000001"], "membership_at_retrieval": "matches",
                  "next_eligible_at": None, "error": None}]
    manifest = {"format": "idea-json-backup", "format_version": "1.0.0",
                "run_id": "20261103T120000.000000Z-invented", "run_kind": "synthetic", "exporter_version": "0.1.0",
                "runtime": {"python": "3.12.0", "sqlite": "3.43.2", "platform": "Invented"},
                "selection": selection, "created_at": TIME, "started_at": attempt["dispatch_started_at"],
                "finished_at": attempt["finished_at"], "request_settings": {
                    "endpoint": "https://www.wikidata.org/w/api.php", "action_parameters": dict(PARAMETERS),
                    "headers": dict(HEADERS), "batch_size": 50, "concurrency": 1, "minimum_gap_seconds": 1,
                    "response_deadline_seconds": 60, "max_attempts_per_item": 3, "retry_backoff_seconds": [5, 10],
                    "supported_content_encodings": ["identity", "gzip"], "http_redirect_policy": "reject"},
                "next_dispatch_at": "2026-11-03T12:00:04.000000Z", "phase": "collected", "state_sequence": 5,
                "public_records": {name: {"file": None, "state_sequence": 5} for name in ("inventory", "attempts")},
                "counts": {"selected": 1, "accepted": 1, "pending": 0, "unresolved": 0},
                "collection_status": "not_checked", "verification_path": None,
                "limitations": ["Collection period; no media, full history or recursive linked-entity retrieval"]}
    rewrite(root, manifest, inventory, [attempt])
    return manifest, inventory, [attempt]


class CollectionVerifierTests(unittest.TestCase):
    def test_independent_complete_public_fixture_passes_without_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            fixture(root)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            report = verify_collection(root)
            self.assertEqual(report["status"], "passed", report)
            self.assertEqual(report["findings"], [])
            self.assertEqual([row["check_id"] for row in report["checks"]],
                             ["scope", "source_content", "provenance", "files"])
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_changed_content_and_number_tokens_fail_after_checksum_refresh(self):
        for update in (lambda e: e["unknown"].update(number=Number("1.23")),
                       lambda e: e["unknown"].update(flag=Number("1")),
                       lambda e: e["unknown"].update(identifier="7")):
            with self.subTest(update=update), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                manifest, inventory, attempts = fixture(root)
                entity = loads(ENTITY)
                update(entity)
                inventory[0]["item"] = store(root, "items/Q1.json", dumps(entity).encode())
                rewrite(root, manifest, inventory, attempts)
                self.assertEqual(verify_collection(root)["status"], "failed")

    def test_stale_view_is_unfinished_but_corruption_still_dominates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = fixture(root)
            manifest["state_sequence"] = 6
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "not_checked")
            (root / "items/Q1.json").write_bytes(b'{}')
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_scope_and_unaccounted_artifacts_fail(self):
        for mode in ("count", "duplicate", "extra"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                manifest, inventory, attempts = fixture(root)
                if mode == "count":
                    manifest["counts"]["selected"] = 2
                elif mode == "duplicate":
                    inventory.append(copy.deepcopy(inventory[0]))
                else:
                    (root / "unaccounted.body").write_bytes(b"unknown")
                rewrite(root, manifest, inventory, attempts)
                self.assertEqual(verify_collection(root)["status"], "failed")
