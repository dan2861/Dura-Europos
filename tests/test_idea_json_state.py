"""Durable production run journal tests using invented selection evidence only."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
