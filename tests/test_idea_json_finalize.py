"""Finalization and recovery over invented local runs; never live retrieval."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
