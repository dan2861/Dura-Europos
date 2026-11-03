"""Durable production run journal tests using invented selection evidence only."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.sample_backup import jsoncodec as codec
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.state import RunState


def results(*qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + q}} for q in qids]}}).encode()


def request(store, qids):
    settings = store.manifest["request_settings"]
    return {"method": "GET", "url": settings["endpoint"],
            "parameters": dict(settings["action_parameters"], ids="|".join(qids)),
            "headers": settings["headers"]}


def temporary_failure(record):
    record.update(outcome="transient_failure", finished_at=record["reserved_at"],
                  error={"stage": "transport", "code": "invented_timeout",
                         "message": "Invented timeout", "retryable": True})
    return record


class StateTests(unittest.TestCase):
    def test_committed_unaccepted_source_requires_local_recovery_before_refetch(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1"])
                store.record_attempt(attempt["attempt_id"], attempt)
                self.assertNotIn("Q1", store.eligible(store.now()))
                with self.assertRaises(ValueError):
                    store.reserve(["Q1"], request(store, ["Q1"]))

    def test_completed_attempt_allows_append_only_recovery_diagnostics(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1"])
                store.record_attempt(attempt["attempt_id"], attempt)
                store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                descriptor = store.publish(f"diagnostics/{attempt['attempt_id']}.fragment", b"fragment", complete=None)
                diagnosis = {"role": "recovered_fragment", "file": descriptor, "explanation": "Invented retained staging fragment"}
                appended = dict(attempt, diagnostics=[diagnosis])
                store.record_attempt(attempt["attempt_id"], appended)
                self.assertEqual(store.get_attempt(attempt["attempt_id"])["diagnostics"], [diagnosis])
                with self.assertRaises(ValueError):
                    store.record_attempt(attempt["attempt_id"], dict(appended, diagnostics=[]))

    def test_opaque_api_warning_numbers_survive_journal_roundtrip(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            warning = {"unknown": {"precision": codec.Number("1.23000000000000000001"),
                                   "negative_zero": codec.Number("-0")}}
            with RunState.create(selection, root) as store:
                attempt = store.reserve(["Q1"], request(store, ["Q1"]))
                attempt.update(outcome="review_required", warnings=warning)
                store.record_attempt(attempt["attempt_id"], attempt)
            with RunState.open(root) as store:
                self.assertEqual(codec.dumps(store.get_attempt(attempt["attempt_id"])["warnings"]), codec.dumps(warning))

    def test_finished_stamp_can_complete_once_after_acceptance_without_other_changes(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1"])
                attempt["finished_at"] = None
                store.record_attempt(attempt["attempt_id"], attempt)
                store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                finished = dict(attempt, finished_at=store.now())
                store.record_attempt(attempt["attempt_id"], finished)
                self.assertEqual(store.get_attempt(attempt["attempt_id"])["finished_at"], finished["finished_at"])
                with self.assertRaises(ValueError):
                    store.record_attempt(attempt["attempt_id"], dict(finished, finished_at="2030-01-01T00:00:00.000000Z"))

    def test_unknown_completeness_is_distinct_from_a_plain_file_descriptor(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                file = store.publish("README.md", b"scope")
                body = store.publish("diagnostics/unowned.body", b"partial", complete=None)
                self.assertNotIn("complete", file)
                self.assertIn("complete", body)
                self.assertIsNone(body["complete"])

    def source(self, store, qids):
        attempt = store.reserve(qids, request(store, qids))
        store.dispatch(attempt["attempt_id"])
        attempt = store.get_attempt(attempt["attempt_id"])
        entities = {qid: {"id": qid, "type": "item", "lastrevid": codec.Number("7"),
                          "modified": "2026-11-03T12:00:00Z", "claims": {},
                          "unknown": {"id": "0007", "number": codec.Number("1.23000000000000000001")}}
                    for qid in qids}
        body = codec.dumps({"success": 1, "entities": entities}).encode()
        descriptor = store.publish(f"responses/{attempt['attempt_id']}.json", body, complete=True)
        attempt.update(http={"status_code": 200, "headers": {"content-encoding": ["identity"]}},
                       headers_received_at=store.now(), headers_observed=True,
                       response_received_at=store.now(), response_elapsed_ms=1, receipt_complete=True,
                       finished_at=store.now(), encoded=descriptor, decoded=descriptor, outcome="succeeded",
                       item_results=[{"qid": qid, "outcome": "accepted", "returned_qid": qid, "error": None}
                                     for qid in qids])
        return attempt, entities

    def test_accept_requires_committed_complete_source_and_preserves_full_entity(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1"])
                with self.assertRaisesRegex(ValueError, "complete|committed"):
                    store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                self.assertFalse((root / "items/Q1.json").exists())
                store.record_attempt(attempt["attempt_id"], attempt)
                changed = dict(entities["Q1"], unknown={"id": "7"})
                with self.assertRaises(ValueError):
                    store.accept("Q1", attempt["attempt_id"], changed, "changed")
                item = store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                self.assertEqual(item["status"], "accepted")
                self.assertEqual(item["retrieved_at"], attempt["response_received_at"])
                self.assertEqual(item["source_response_id"], attempt["attempt_id"])
                self.assertIn(b'1.23000000000000000001', (root / "items/Q1.json").read_bytes())
                self.assertTrue(codec.equal(codec.loads((root / "items/Q1.json").read_bytes()), entities["Q1"]))
                self.assertEqual(store.manifest["counts"]["accepted"], 1)
                self.assertNotIn("Q1", store.eligible(store.now()))
                store.pause()
            with RunState.open(root) as store:
                self.assertEqual(store.get_item("Q1")["status"], "accepted")

    def test_one_source_parse_per_batch_and_no_rehash_of_prior_item_on_append(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1", "Q2"])
                store.record_attempt(attempt["attempt_id"], attempt)
                with patch.object(store, "_read_descriptor", wraps=store._read_descriptor) as read:
                    store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                    store.accept("Q2", attempt["attempt_id"], entities["Q2"], "changed")
                self.assertEqual([call.args[0]["path"] for call in read.call_args_list],
                                 [attempt["decoded"]["path"]])
                next_attempt, next_entities = self.source(store, ["Q10"])
                store.record_attempt(next_attempt["attempt_id"], next_attempt)
                with patch.object(store, "_read_descriptor", wraps=store._read_descriptor) as read:
                    store.accept("Q10", next_attempt["attempt_id"], next_entities["Q10"], "changed")
                self.assertNotIn("items/Q1.json", [call.args[0]["path"] for call in read.call_args_list])

    def test_published_item_before_acceptance_commit_is_compared_not_replaced(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1"])
                store.record_attempt(attempt["attempt_id"], attempt)
                with patch.object(store, "_put_item", side_effect=OSError("acceptance commit interrupted")):
                    with self.assertRaises(OSError):
                        store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                orphan = root / "items/Q1.json"
                self.assertTrue(orphan.is_file())
                before_inode = orphan.stat().st_ino
                self.assertEqual(store.get_item("Q1")["status"], "pending")
                store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                self.assertEqual(orphan.stat().st_ino, before_inode)

    def test_accepted_file_or_source_corruption_stops_reopen(self):
        for relative in ("items/Q1.json", "source"):
            with self.subTest(relative=relative), TemporaryDirectory() as directory:
                selection, root = self.fixture(directory)
                with RunState.create(selection, root) as store:
                    attempt, entities = self.source(store, ["Q1"])
                    store.record_attempt(attempt["attempt_id"], attempt)
                    store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                    store.pause()
                path = root / (attempt["decoded"]["path"] if relative == "source" else relative)
                path.write_bytes(b"{}")
                with self.assertRaises(ValueError):
                    RunState.open(root)

    def test_completed_source_record_is_immutable_and_internal_intent_is_private(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1"])
                store.record_attempt(attempt["attempt_id"], attempt)
                changed = dict(attempt, response_received_at="2026-11-04T00:00:00.000000Z")
                with self.assertRaises(ValueError):
                    store.record_attempt(attempt["attempt_id"], changed)
                sequence = store.manifest["state_sequence"]
                store.set_internal("finalization", {"report_sha256": "a" * 64})
                self.assertEqual(store.manifest["state_sequence"], sequence)
                self.assertNotIn("finalization", store.manifest)
            with RunState.open(root) as store:
                self.assertEqual(store.get_internal("finalization"), {"report_sha256": "a" * 64})
                store.set_internal("finalization", None)
                self.assertIsNone(store.get_internal("finalization"))

    def test_interrupted_payload_staging_retains_attempt_owner_and_bytes(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                attempt, entities = self.source(store, ["Q1"])
                store.record_attempt(attempt["attempt_id"], attempt)
                with patch("scripts.idea_json_backup.state.os.link", side_effect=KeyboardInterrupt("before publication")):
                    with self.assertRaises(KeyboardInterrupt):
                        store.accept("Q1", attempt["attempt_id"], entities["Q1"], "changed")
                intents = store.internal_items("payload:")
                self.assertEqual(len(intents), 1)
                intent = next(iter(intents.values()))
                self.assertEqual(intent["attempt_id"], attempt["attempt_id"])
                self.assertIn(attempt["attempt_id"], intent["staging_path"])
                self.assertTrue((root / intent["staging_path"]).read_bytes())
                self.assertFalse((root / "items/Q1.json").exists())

    def fixture(self, directory):
        selection = Path(directory) / "selection"
        freeze_fixture_responses(results("Q10", "Q2"), results("Q1"), selection)
        return selection, Path(directory) / "run"

    def test_create_snapshots_frozen_scope_and_verified_sqlite_settings(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            before = (selection / "selection.json").read_bytes()
            with RunState.create(selection, root) as store:
                self.assertEqual(store.manifest["phase"], "initialized")
                self.assertEqual(store.manifest["counts"], {"selected": 3, "pending": 3, "accepted": 0, "unresolved": 0})
                self.assertEqual([row["requested_qid"] for row in store.items()], ["Q1", "Q2", "Q10"])
                self.assertEqual(store.db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete")
                self.assertEqual(store.db.execute("PRAGMA synchronous").fetchone()[0], 3)
                self.assertEqual(store.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual((root / "selection/selection.json").read_bytes(), before)
                self.assertFalse((root / "selection/.state").exists())
                rows = [json.loads(line) for line in (root / "inventory.jsonl").read_text().splitlines()]
                self.assertEqual([row["status"] for row in rows], ["pending"] * 3)
                self.assertEqual((root / "attempts.jsonl").read_bytes(), b"")
            self.assertEqual((selection / "selection.json").read_bytes(), before)

    def test_exclusive_lock_and_existing_run_refuse_reuse(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root):
                with self.assertRaises((BlockingIOError, ValueError)):
                    RunState.open(root)
                with self.assertRaises(FileExistsError):
                    RunState.create(selection, root)
            with RunState.open(root) as store:
                self.assertEqual(store.manifest["counts"]["selected"], 3)

    def test_reservations_consume_quota_across_reopen_and_public_views_are_explicit(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                initial = (root / "inventory.jsonl").read_bytes()
                reserved = store.reserve(["Q1"], request(store, ["Q1"]))
                store.dispatch(reserved["attempt_id"])
                self.assertIsNotNone(store.get_attempt(reserved["attempt_id"])["dispatch_started_at"])
                store.record_attempt(reserved["attempt_id"], temporary_failure(store.get_attempt(reserved["attempt_id"])))
                store.unresolve("Q1", reserved["error"] or {"stage": "transport", "code": "timeout",
                                "message": "Invented timeout", "retryable": True})
                self.assertEqual((root / "inventory.jsonl").read_bytes(), initial)
                store.pause()
                self.assertEqual(len(json.loads((root / "inventory.jsonl").read_text().splitlines()[0])["attempt_ids"]), 1)
            for expected in (2, 3):
                with RunState.open(root) as store:
                    attempt = store.reserve(["Q1"], request(store, ["Q1"]))
                    self.assertEqual(attempt["attempt_id"], f"A{expected:06d}")
                    store.record_attempt(attempt["attempt_id"], temporary_failure(attempt))
                    store.unresolve("Q1", attempt["error"])
                    self.assertEqual(len(store.get_item("Q1")["attempt_ids"]), expected)
            with RunState.open(root) as store:
                with self.assertRaisesRegex(ValueError, "quota|eligible"):
                    store.reserve(["Q1"], request(store, ["Q1"]))
                self.assertNotIn("Q1", store.eligible("9999-01-01T00:00:00.000000Z"))

    def test_unknown_scope_order_and_changed_request_cannot_be_reserved(self):
        with TemporaryDirectory() as directory:
            selection, root = self.fixture(directory)
            with RunState.create(selection, root) as store:
                for qids in (["Q99"], ["Q2", "Q1"], ["Q1", "Q1"]):
                    with self.subTest(qids=qids), self.assertRaises(ValueError):
                        store.reserve(qids, request(store, qids))
                changed = request(store, ["Q1"])
                changed["parameters"]["redirects"] = "yes"
                with self.assertRaises(ValueError):
                    store.reserve(["Q1"], changed)
                self.assertEqual(store.attempts(), [])

    def test_missing_or_corrupt_journal_is_never_rebuilt(self):
        for damage in ("missing", "corrupt"):
            with self.subTest(damage=damage), TemporaryDirectory() as directory:
                selection, root = self.fixture(directory)
                with RunState.create(selection, root):
                    pass
                journal = root / ".state/state.sqlite"
                if damage == "missing":
                    journal.unlink()
                else:
                    journal.write_bytes(b"not sqlite")
                with self.assertRaises((OSError, ValueError)):
                    RunState.open(root)
                if damage == "missing":
                    self.assertFalse(journal.exists())
