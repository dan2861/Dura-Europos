import copy
import csv
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.sample_backup import jsoncodec as codec, transform, validation
from scripts.sample_backup.schema import ENDPOINT
from scripts.sample_backup.storage import RunStore, utc_now
from test_sample_backup_transform import entity, snak, statement


def attempt(directory, sources=None):
    if sources is None:
        ref = {"hash": "shared-source", "snaks": {"P304": [snak("P304", "001")]}, "snaks-order": ["P304"]}
        other = copy.deepcopy(ref)
        other["snaks"]["P304"][0]["datavalue"]["value"] = "002"
        a = statement("Q42$One", qualifiers={"P195": [snak("P195", "A"), snak("P195", "A")]},
                      references=[ref], **{"qualifiers-order": ["P195"]})
        b = statement("Q42$Two", main=snak(value="other"), qualifiers={"P195": [snak("P195", "B")]},
                      references=[other], **{"qualifiers-order": ["P195"]})
        tag = statement("Q42$Tag", main={"property": "P5008", "snaktype": "value", "datatype": "wikibase-item",
                                        "datavalue": {"value": {"id": "Q114241199", "entity-type": "item", "numeric-id": 114241199},
                                                      "type": "wikibase-entityid"}})
        sources = [entity(claims={"P217": [a, b], "P5008": [tag]})]
    store = RunStore.create(Path(directory), [e["id"] for e in sources], "synthetic-fixture")
    for entry, source in zip(store.manifest["items"], sources):
        qid = source["id"]
        path = store.save_original(qid, codec.dumps({"entities": {qid: source}}).encode("utf-8"))
        entry.update(returned_qid=qid, retrieval_status="succeeded", retrieved_at=utc_now(),
                     source_json=path, lastrevid=source["lastrevid"], modified=source["modified"],
                     http_trace=[{"url": ENDPOINT.format(qid=qid), "status_code": 200, "location": None}])
    result = transform.project(sources)
    for table, rows in result.tables.items():
        store.write_table(table, rows)
    store.manifest["finished_at"] = utc_now()
    store.checkpoint()
    return store, result.tables


def checks(report):
    return {c["check_id"]: c for c in report["checks"]}


class ValidationTests(unittest.TestCase):
    def test_independently_detects_semantic_and_inventory_corruption(self):
        cases = ("clean", "item", "value", "parent", "references", "duplicate", "case", "file", "hash", "count")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as directory:
                store, tables = attempt(directory)
                target = "files"
                if case == "item":
                    tables["items"][0]["label_en"] = "changed"
                    target = "item_data"
                elif case == "value":
                    tables["statements"][0]["datavalue_json"] = '{"value":"changed","type":"string"}'
                    tables["statements"][0]["value_text"] = "changed"
                    target = "statements_qualifiers"
                elif case == "parent":
                    tables["qualifiers"][0]["statement_id"] = "Q42$Two"
                    target = "statements_qualifiers"
                elif case == "references":
                    tables["statement_references"][1]["reference_id"] = tables["statement_references"][0]["reference_id"]
                    target = "references"
                elif case == "duplicate":
                    tables["qualifiers"].pop(1)
                    target = "statements_qualifiers"
                elif case == "case":
                    tables["statements"][0]["statement_id"] = "q42$one"
                    target = "statements_qualifiers"
                if case in ("item", "value", "parent", "references", "duplicate", "case"):
                    for table, rows in tables.items():
                        store.write_table(table, rows)
                    store.checkpoint()  # correct hashes cannot conceal semantic corruption
                if case == "file":
                    (store.root / "qualifiers.csv").unlink()
                    store.checkpoint()  # missing from BOTH disk and produced-file inventory
                if case in ("hash", "count"):
                    store.manifest["outputs"][0]["sha256" if case == "hash" else "row_count"] = "wrong"
                    store._write("manifest.json", codec.dumps(store.manifest).encode(), replace=True)
                report = validation.verify(store.root)
                result = checks(report)
                if case == "clean":
                    self.assertEqual(report["status"], "not_checked")
                    self.assertEqual(result["manual_review"]["status"], "not_checked")
                    self.assertTrue(all(result[c]["status"] == "passed" for c in result if c != "manual_review"), result)
                else:
                    self.assertEqual(report["status"], "failed")
                    self.assertEqual(result[target]["status"], "failed", result)

    def test_manual_review_requires_two_actual_contrasting_saved_items(self):
        with TemporaryDirectory() as directory:
            initial, _ = attempt(Path(directory) / "initial")
            first = codec.loads((initial.root / "original/Q42.json").read_bytes())["entities"]["Q42"]
            second = copy.deepcopy(first)
            second["id"] = "Q1"
            second["claims"]["P217"].pop()
            for statements in second["claims"].values():
                for s in statements:
                    s["id"] = s["id"].replace("Q42$", "Q1$")
            store, _ = attempt(Path(directory) / "reviewed", [first, second])
            import hashlib
            evidence = {"reviewer": "Synthetic test reviewer", "reviewed_at": "2026-10-20",
                        "contrast": "Synthetic one versus two P217 statements", "status": "passed", "findings": [],
                        "items": [{"qid": source["id"], "lastrevid": source["lastrevid"],
                                   "source_sha256": hashlib.sha256((store.root / f'original/{source["id"]}.json').read_bytes()).hexdigest(),
                                   "comparisons": {table: "Synthetic source pointer and table-key comparison" for table in tables_names}}
                                  for source in (first, second)]}
            report = validation.verify(store.root, manual_evidence=evidence)
            self.assertEqual(report["status"], "passed", report)
            incomplete = copy.deepcopy(evidence)
            incomplete["items"].pop()
            self.assertEqual(validation.verify(store.root, manual_evidence=incomplete)["status"], "not_checked")
            failed = copy.deepcopy(evidence)
            failed["findings"] = ["Synthetic observed preservation difference"]
            self.assertEqual(validation.verify(store.root, manual_evidence=failed)["status"], "failed")

    def test_malformed_manifest_is_reported_and_never_crashes_or_passes(self):
        for replacement in (None, [], {"items": [None]}, {"retrieval_method": []}):
            with self.subTest(replacement=replacement), TemporaryDirectory() as directory:
                store, _ = attempt(directory)
                manifest = copy.deepcopy(store.manifest)
                if isinstance(replacement, dict):
                    manifest.update(replacement)
                else:
                    manifest = replacement
                store._write("manifest.json", codec.dumps(manifest).encode(), replace=True)
                report = validation.verify(store.root)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(checks(report)["files"]["status"], "failed")
                self.assertTrue(all(c["status"] != "passed" for c in report["checks"]
                                    if c["check_id"] != "files"), report)

    def test_item_validation_failure_is_attributed_to_affected_item(self):
        with TemporaryDirectory() as directory:
            initial, _ = attempt(Path(directory) / "initial")
            first = codec.loads((initial.root / "original/Q42.json").read_bytes())["entities"]["Q42"]
            second = copy.deepcopy(first)
            second["id"] = "Q1"
            for statements in second["claims"].values():
                for s in statements:
                    s["id"] = s["id"].replace("Q42$", "Q1$")
            store, tables = attempt(Path(directory) / "two", [first, second])
            tables["items"][0]["label_en"] = "corrupted"
            store.write_table("items", tables["items"])
            store.checkpoint()
            report = validation.verify(store.root, write=True)
            saved = codec.loads((store.root / "manifest.json").read_bytes())
            self.assertEqual(report["status"], "failed")
            self.assertEqual([e["validation_status"] for e in saved["items"]], ["failed", "not_checked"])

    def test_identity_holds_withhold_rows_and_checksums_are_not_rewritten(self):
        with TemporaryDirectory() as directory:
            store, tables = attempt(directory)
            body = (store.root / "items.csv").read_bytes()
            (store.root / "items.csv").write_bytes(body.replace(b"Photo", b"Other"))
            inventory = codec.dumps(store.manifest["outputs"])
            self.assertEqual(validation.verify(store.root, write=True)["status"], "failed")
            saved = codec.loads((store.root / "manifest.json").read_bytes())
            self.assertEqual(codec.dumps(saved["outputs"]), inventory)
            self.assertEqual(validation.verify(store.root)["status"], "failed")
        with TemporaryDirectory() as directory:
            store, _ = attempt(directory)
            source = codec.loads((store.root / "original/Q42.json").read_bytes())["entities"]["Q42"]
            source["id"] = "Q1"
            # Invented redirected-identity fixture: retain bytes under requested filename.
            store._write("original/Q42.json", codec.dumps({"entities": {"Q1": source}}).encode(), replace=True)
            store.manifest["items"][0]["returned_qid"] = "Q1"
            for table in tables_names:
                store.write_table(table, [])
            store.checkpoint()
            report = validation.verify(store.root)
            self.assertEqual(report["status"], "not_checked", report)
            self.assertEqual(checks(report)["request_coverage"]["status"], "not_checked")

    def test_contract_metadata_and_unassociated_evidence_cannot_pass(self):
        for case in ("scope", "time", "retrieval_time", "orphan", "reference_hash", "count_type", "http_type", "size_type"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                store, _ = attempt(directory)
                target = "files"
                if case == "scope":
                    store.manifest["scope"]["unexpected"] = True
                elif case == "time":
                    store.manifest["finished_at"] = "1900-01-01T00:00:00Z"
                elif case == "retrieval_time":
                    store.manifest["items"][0]["retrieved_at"] = None
                    target = "request_coverage"
                elif case == "orphan":
                    store.save_failure("Q42", b"unassociated saved body")
                    target = "request_coverage"
                elif case == "count_type":
                    store.manifest["scope"]["requested_count"] = "1"
                elif case == "http_type":
                    store.manifest["items"][0]["http_trace"][0]["status_code"] = "200"
                    target = "request_coverage"
                elif case == "size_type":
                    store.checkpoint()
                    store.manifest["outputs"][0]["size_bytes"] = str(store.manifest["outputs"][0]["size_bytes"])
                else:
                    path = store.root / "original/Q42.json"
                    source = codec.loads(path.read_bytes())["entities"]["Q42"]
                    source["claims"]["P217"][0]["references"][0]["hash"] = None
                    store._write("original/Q42.json", codec.dumps({"entities": {"Q42": source}}).encode(), replace=True)
                    for table, rows in transform.project([source]).tables.items():
                        store.write_table(table, rows)
                    target = "references"
                if case == "size_type":
                    store._write("manifest.json", codec.dumps(store.manifest).encode(), replace=True)
                else:
                    store.checkpoint()
                report = validation.verify(store.root)
                self.assertEqual(checks(report)[target]["status"], "failed", report)

    def test_csv_quotes_are_required(self):
        with TemporaryDirectory() as directory:
            store, _ = attempt(directory)
            source = codec.loads((store.root / "original/Q42.json").read_bytes())["entities"]["Q42"]
            source["labels"]["en"]["value"] = 'A""B'
            store._write("original/Q42.json", codec.dumps({"entities": {"Q42": source}}).encode(), replace=True)
            for table, rows in transform.project([source]).tables.items():
                store.write_table(table, rows)
            path = store.root / "items.csv"
            path.write_bytes(path.read_bytes().replace(b'"A""""B"', b'A""B', 1))
            store.checkpoint()
            self.assertEqual(checks(validation.verify(store.root))["files"]["status"], "failed")

    def test_precision_corruption_fails_even_after_reinventory(self):
        with TemporaryDirectory() as directory:
            store, _ = attempt(directory)
            source = codec.loads((store.root / "original/Q42.json").read_bytes())["entities"]["Q42"]
            main = source["claims"]["P217"][0]["mainsnak"]
            main["datavalue"] = codec.loads('{"value":{"latitude":12.1234567890123456789,"longitude":-1e-90},"type":"globecoordinate"}')
            store._write("original/Q42.json", codec.dumps({"entities": {"Q42": source}}).encode(), replace=True)
            tables = transform.project([source]).tables
            for table, rows in tables.items():
                store.write_table(table, rows)
            row = tables["statements"][0]
            row["datavalue_json"] = row["datavalue_json"].replace("12.1234567890123456789", "12.123456789")
            row["value_text"] = row["datavalue_json"]
            store.write_table("statements", tables["statements"])
            store.checkpoint()
            report = validation.verify(store.root)
            self.assertEqual(checks(report)["statements_qualifiers"]["status"], "failed")
            self.assertEqual(checks(report)["files"]["status"], "passed")

    def test_accounted_failure_still_overrides_unfinished_checks(self):
        from scripts import export_sample_backup as app
        from scripts.sample_backup.retrieval import Result
        with TemporaryDirectory() as directory:
            store = RunStore.create(Path(directory), ["Q42"], "synthetic")
            self.assertEqual(validation.verify(store.root)["status"], "not_checked")
            app.collect_requests(store, fetch=lambda qid: Result(b"partial\x00", [], False, "synthetic transfer failure"))
            store.manifest["finished_at"] = utc_now()
            store.checkpoint()
            report = validation.verify(store.root)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(checks(report)["request_coverage"]["status"], "passed")
            self.assertEqual(checks(report)["files"]["status"], "passed")
            self.assertEqual(checks(report)["manual_review"]["status"], "not_checked")

    def test_manifest_symlink_is_not_followed(self):
        with TemporaryDirectory() as directory:
            store, _ = attempt(directory)
            original = (store.root / "manifest.json").read_bytes()
            outside = Path(directory) / "outside-manifest.json"
            outside.write_bytes(original)
            (store.root / "manifest.json").unlink()
            (store.root / "manifest.json").symlink_to(outside)
            self.assertEqual(checks(validation.verify(store.root))["files"]["status"], "failed")

    def test_completed_automated_checks_are_checkpointed_before_manual_review(self):
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            store, _ = attempt(directory)
            inventory = codec.dumps(store.manifest["outputs"])
            with patch.object(validation.Audit, "manual", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    validation.verify(store.root, write=True)
            saved = codec.loads((store.root / "manifest.json").read_bytes())
            result = checks(saved["validation_summary"])
            self.assertTrue(all(result[c]["status"] == "passed" for c in result if c != "manual_review"))
            self.assertEqual(result["manual_review"]["status"], "not_checked")
            self.assertEqual(saved["validation_summary"]["status"], "not_checked")
            self.assertEqual(codec.dumps(saved["outputs"]), inventory)


tables_names = ("items", "statements", "qualifiers", "references", "statement_references")
