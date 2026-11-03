"""Finalization and recovery over invented local runs; never live retrieval."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.sample_backup import jsoncodec as codec
from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.idea_json_backup.finalize import finalize, resume_finalization
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.state import RunState

TIME = "2026-11-03T12:00:00.000000Z"


def selection_response():
    return b'{"head":{"vars":["item"]},"results":{"bindings":[{"item":{"type":"uri","value":"http://www.wikidata.org/entity/Q1"}}]}}'


def fixture(directory, *, accepted=True):
    base = Path(directory)
    selection, root = base / "selection", base / "run"
    freeze_fixture_responses(selection_response(), b'{"head":{"vars":["item"]},"results":{"bindings":[]}}', selection)
    with RunState.create(selection, root, now_fn=lambda: TIME) as store:
        settings = store.manifest["request_settings"]
        request = {"method": "GET", "url": settings["endpoint"],
                   "parameters": dict(settings["action_parameters"], ids="Q1"), "headers": settings["headers"]}
        attempt = store.reserve(["Q1"], request)
        store.dispatch(attempt["attempt_id"])
        attempt = store.get_attempt(attempt["attempt_id"])
        if accepted:
            entity = {"id": "Q1", "type": "item", "lastrevid": codec.Number("7"),
                      "modified": "2026-11-03T11:00:00Z", "claims": {},
                      "unknown": {"identifier": "0007", "number": codec.Number("1.23000000000000000001")}}
            body = codec.dumps({"success": 1, "entities": {"Q1": entity}}).encode()
            descriptor = store.publish("responses/A000001.json", body, complete=True)
            attempt.update(headers_received_at=TIME, headers_observed=True, response_received_at=TIME,
                           response_elapsed_ms=0, receipt_complete=True,
                           http={"status_code": 200, "headers": {"content-encoding": ["identity"], "content-length": [str(len(body))]}},
                           encoded=descriptor, decoded=descriptor, outcome="succeeded",
                           item_results=[{"qid": "Q1", "outcome": "accepted", "returned_qid": "Q1", "error": None}])
            store.record_attempt(attempt["attempt_id"], attempt)
            store.accept("Q1", attempt["attempt_id"], entity, "changed")
            store.record_attempt(attempt["attempt_id"], dict(attempt, finished_at=TIME))
        else:
            error = {"stage": "identity", "code": "missing", "message": "Invented missing item", "retryable": False}
            attempt.update(outcome="review_required", finished_at=TIME,
                           headers_observed=False, error=error,
                           item_results=[{"qid": "Q1", "outcome": "review_required", "returned_qid": None, "error": error}])
            store.record_attempt(attempt["attempt_id"], attempt)
            store.unresolve("Q1", error)
        store.set_run(next_dispatch_at="2026-11-03T12:00:01.000000Z")
        store.collected()
    return root


class FinalizeTests(unittest.TestCase):
    def interrupt(self, root, at):
        def crash(phase):
            if phase == at:
                raise RuntimeError("Invented finalization crash at " + phase)
        with self.assertRaises(RuntimeError):
            finalize(root, hook=crash)

    def test_audit_then_changed_input_cannot_be_finalized_as_passed(self):
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            original = verify_collection

            def audit_then_damage(path):
                report = original(path)
                self.assertEqual(report["status"], "passed")
                (root / "items/Q1.json").write_bytes(b"{}")
                return report

            with patch("scripts.idea_json_backup.finalize.verify_collection", side_effect=audit_then_damage):
                with self.assertRaisesRegex(ValueError, "changed"):
                    finalize(root)
            self.assertEqual(json.loads((root / "manifest.json").read_bytes())["phase"], "collected")
            self.assertFalse((root / "verification.json").exists())

    def test_linked_private_finalization_folder_never_writes_outside(self):
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            outside = Path(directory) / "outside"
            outside.mkdir()
            (root / ".state/finalization").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                finalize(root)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((root / "verification.json").exists())

    def test_interrupted_publication_retains_owned_private_staging(self):
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            original_replace = os.replace

            def crash_before_report(source, destination):
                if Path(destination) == root / "verification.json":
                    raise KeyboardInterrupt("Invented publication interruption")
                return original_replace(source, destination)

            with patch("os.replace", side_effect=crash_before_report), self.assertRaises(KeyboardInterrupt):
                finalize(root)
            self.assertTrue(list((root / ".state/finalization").glob("*.publish.*")))
            self.assertEqual(list(root.glob(".pending-*")), [])
            with RunState.open(root) as store:
                with patch("scripts.idea_json_backup.finalize.verify_collection", side_effect=AssertionError("No repeated audit")):
                    self.assertEqual(resume_finalization(store)["status"], "passed")

    def test_all_crash_boundaries_resume_the_exact_prepared_bytes_without_new_audit(self):
        for boundary in ("afterprepare", "afterreport", "aftermanifest", "beforejournal"):
            with self.subTest(boundary=boundary), TemporaryDirectory() as directory:
                root = fixture(directory)
                self.interrupt(root, boundary)
                with RunState.open(root) as store:
                    intent = store.get_internal("finalization")
                    report = (root / intent["report"]["path"]).read_bytes()
                    manifest = (root / intent["manifest"]["path"]).read_bytes()
                    with patch("scripts.idea_json_backup.finalize.verify_collection", side_effect=AssertionError("No repeated audit")):
                        self.assertEqual(resume_finalization(store)["status"], "passed")
                    self.assertEqual(store.manifest["phase"], "finalized")
                    self.assertIsNone(store.get_internal("finalization"))
                self.assertEqual((root / "verification.json").read_bytes(), report)
                self.assertEqual((root / "manifest.json").read_bytes(), manifest)

    def test_changed_inputs_or_prepared_bytes_hold_recovery_without_publication(self):
        for damage in ("item", "extra", "prepared"):
            with self.subTest(damage=damage), TemporaryDirectory() as directory:
                root = fixture(directory)
                self.interrupt(root, "afterprepare")
                if damage == "item":
                    (root / "items/Q1.json").write_bytes(b"{}")
                elif damage == "extra":
                    (root / "unexpected.bin").write_bytes(b"unexpected")
                else:
                    with RunState.open(root) as store:
                        prepared = store.get_internal("finalization")["report"]["path"]
                    (root / prepared).write_bytes(b"changed")
                with patch("scripts.idea_json_backup.finalize.verify_collection", side_effect=AssertionError("No repeated audit")):
                    with self.assertRaises(ValueError):
                        with RunState.open(root) as store:
                            resume_finalization(store)
                self.assertFalse((root / "verification.json").exists())

    def test_published_manifest_with_changed_report_is_held_not_repaired(self):
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.interrupt(root, "aftermanifest")
            (root / "verification.json").write_bytes(b"{}")
            with RunState.open(root) as store:
                with self.assertRaises(ValueError):
                    resume_finalization(store)
                self.assertIsNotNone(store.get_internal("finalization"))
            self.assertEqual((root / "verification.json").read_bytes(), b"{}")

    def test_passed_finalization_publishes_report_then_manifest_and_freezes_payload(self):
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            before = json.loads((root / "manifest.json").read_bytes())
            events = []
            report = finalize(root, hook=lambda phase: events.append(phase))
            self.assertEqual(report["status"], "passed")
            saved = json.loads((root / "manifest.json").read_bytes())
            self.assertEqual(saved["phase"], "finalized")
            self.assertEqual(saved["collection_status"], "passed")
            self.assertEqual(saved["verification_path"], "verification.json")
            self.assertEqual(saved["state_sequence"], before["state_sequence"])
            self.assertEqual(events, ["afterprepare", "afterreport", "aftermanifest", "beforejournal"])
            self.assertEqual(verify_collection(root)["status"], "passed")
            with RunState.open(root) as store:
                self.assertIsNone(store.get_internal("finalization"))
                with self.assertRaises(ValueError):
                    store.snapshot()
            with self.assertRaises(ValueError):
                finalize(root)

    def test_failed_audit_is_recorded_without_finalizing(self):
        with TemporaryDirectory() as directory:
            root = fixture(directory, accepted=False)
            report = finalize(root)
            self.assertEqual(report["status"], "failed")
            saved = json.loads((root / "manifest.json").read_bytes())
            self.assertEqual(saved["phase"], "collected")
            self.assertEqual(saved["collection_status"], "failed")
            self.assertEqual(saved["verification_path"], "verification.json")
            with RunState.open(root) as store:
                self.assertIsNone(store.get_internal("finalization"))
