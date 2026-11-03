"""Synthetic production runs: real journal/files, invented captures, no live calls."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from scripts.idea_json_backup.client import FetchResult
from scripts.idea_json_backup.production import collect, resume
from scripts.idea_json_backup.state import RunState
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.idea_json_backup.finalize import finalize


def graph(*qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + q}} for q in qids]}}).encode()


def item(qid):
    return {"id": qid, "type": "item", "lastrevid": 7, "modified": "2026-11-03T12:00:00Z", "claims": {}}


class Clock:
    def __init__(self):
        self.seconds = 0
        self.elapsed = 0

    def utc(self):
        return (datetime(2026, 11, 3, 12, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ")

    def sleep(self, duration):
        self.seconds += duration
        self.elapsed += duration

    def monotonic(self):
        return self.elapsed

    def result(self, body, *, status=200, headers=None, error=None):
        return FetchResult(body, body, status, headers or {}, self.utc(), self.utc(), True,
                           self.utc(), 0, True, error)


class ProductionTests(unittest.TestCase):
    def test_resume_completes_prepared_finalization_before_any_other_work(self):
        clock, calls = Clock(), []
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "run"
            collect(self.selection(base, ["Q1"]), root, fetcher=self.fetcher(clock, calls),
                    sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)

            def interrupt(step):
                if step == "afterreport":
                    raise KeyboardInterrupt("invented finalization interruption")

            with self.assertRaises(KeyboardInterrupt):
                finalize(root, hook=interrupt)
            original_report = (root / "verification.json").read_bytes()
            no_fetch = Mock(side_effect=AssertionError("finalization recovery cannot fetch"))
            metadata = resume(root, fetcher=no_fetch, sleep=clock.sleep, now_fn=clock.utc,
                              monotonic=clock.monotonic)
            no_fetch.assert_not_called()
            self.assertEqual(metadata["phase"], "finalized")
            self.assertEqual((root / "verification.json").read_bytes(), original_report)
            self.assertEqual(verify_collection(root)["status"], "passed")

    def test_live_monotonic_wait_survives_wall_clock_jump(self):
        clock, calls = Clock(), []
        response = self.fetcher(clock, [])
        from scripts.idea_json_backup import production
        original = production._retain_wait
        jumped = []

        def jump(store, until):
            original(store, until)
            if not jumped:
                jumped.append(True)
                clock.seconds += 1000

        def server(*args, **kwargs):
            calls.append(clock.elapsed)
            value = response(*args, **kwargs)
            value.headers = {"retry-after": ["20"]}
            return value

        with TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.object(production, "_retain_wait", side_effect=jump):
                collect(self.selection(base, [f"Q{i}" for i in range(1, 52)]), base / "run",
                        fetcher=server, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            self.assertEqual(calls, [0, 20])

    def test_retry_eligibility_is_anchored_to_recorded_local_finish(self):
        class TickingClock(Clock):
            def __init__(self):
                super().__init__()
                self.ticks = 0

            def utc(self):
                self.ticks += 1
                return (datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
                        + timedelta(seconds=self.seconds, microseconds=self.ticks * 1000)).strftime(
                            "%Y-%m-%dT%H:%M:%S.%fZ")

        clock = TickingClock()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "run"
            collect(self.selection(base, ["Q1"]), root,
                    fetcher=lambda *a, **k: clock.result(b'{"error":{"code":"maxlag","info":"busy"}}'),
                    sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic, max_batches=1)
            with RunState.open(root, now_fn=clock.utc) as store:
                attempt = store.attempts()[0]
                finished = datetime.fromisoformat(attempt["finished_at"].replace('Z', '+00:00'))
                eligible = datetime.fromisoformat(attempt["next_eligible_at"].replace('Z', '+00:00'))
                self.assertGreaterEqual((eligible - finished).total_seconds(), 5)
                self.assertEqual(store.get_item("Q1")["next_eligible_at"], attempt["next_eligible_at"])

    def test_bounded_pause_is_immediate_and_quota_survives_restarts(self):
        clock, calls = Clock(), []

        def failing(request, directory, **options):
            calls.append(clock.seconds)
            return clock.result(b'{"error":{"code":"maxlag","info":"busy"}}')

        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "run"
            collect(self.selection(base, ["Q1"]), root, fetcher=failing, sleep=clock.sleep,
                    now_fn=clock.utc, monotonic=clock.monotonic, max_batches=1)
            self.assertEqual(clock.seconds, 0)
            resume(root, fetcher=failing, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic, max_batches=1)
            resume(root, fetcher=failing, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic, max_batches=1)
            resume(root, fetcher=failing, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            self.assertEqual(calls, [0, 5, 15])
            with RunState.open(root, now_fn=clock.utc) as store:
                self.assertEqual(len(store.get_item("Q1")["attempt_ids"]), 3)
                self.assertEqual(store.manifest["counts"]["accepted"], 0)

    def test_resume_recovers_strongest_mixed_server_wait_before_fresh_qids(self):
        clock, calls = Clock(), []
        response = self.fetcher(clock, calls)

        def server(request, directory, **kwargs):
            value = response(request, directory, **kwargs)
            value.headers = {"retry-after": ["20", "Tue, 03 Nov 2026 12:00:30 GMT"]}
            return value

        with TemporaryDirectory() as directory:
            base = Path(directory)
            selected = self.selection(base, [f"Q{i}" for i in range(1, 52)])
            root = base / "run"
            with patch("scripts.idea_json_backup.production._retain_wait", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                collect(selected, root, fetcher=server, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            resume(root, fetcher=response, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            self.assertEqual([stamp for stamp, qids in calls], [0, 30])

    def selection(self, base, qids):
        root = base / "selection"
        freeze_fixture_responses(graph(*qids), graph(), root)
        return root

    def fetcher(self, clock, calls):
        def response(request, directory, **kwargs):
            qids = request["parameters"]["ids"].split("|")
            calls.append((clock.seconds, qids))
            return clock.result(json.dumps({"success": 1, "entities": {q: item(q) for q in reversed(qids)}}).encode())
        return response

    def test_batches_all_frozen_items_without_per_item_public_snapshots(self):
        clock, calls = Clock(), []
        snapshots = []
        original = RunState.snapshot

        def snapshot(store):
            snapshots.append(True)
            return original(store)

        with TemporaryDirectory() as directory, patch.object(RunState, "snapshot", snapshot):
            base = Path(directory)
            selected = self.selection(base, [f"Q{i}" for i in range(1, 56)])
            root = base / "run"
            collect(selected, root, fetcher=self.fetcher(clock, calls), sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            self.assertEqual([len(qids) for stamp, qids in calls], [50, 5])
            self.assertEqual([stamp for stamp, qids in calls], [0, 1])
            self.assertEqual(len(snapshots), 2)
            self.assertEqual(verify_collection(root)["status"], "passed")

    def test_complete_committed_source_recovers_locally_without_refetch(self):
        clock, calls = Clock(), []
        original = RunState.accept

        def interrupt_second(store, qid, attempt_id, entity, membership):
            if qid == "Q2":
                raise KeyboardInterrupt("invented interruption after source commit")
            return original(store, qid, attempt_id, entity, membership)

        with TemporaryDirectory() as directory:
            base = Path(directory)
            selected = self.selection(base, ["Q1", "Q2"])
            root = base / "run"
            with patch.object(RunState, "accept", interrupt_second), self.assertRaises(KeyboardInterrupt):
                collect(selected, root, fetcher=self.fetcher(clock, calls), sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            no_fetch = Mock(side_effect=AssertionError("committed source must recover locally"))
            resume(root, fetcher=no_fetch, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            no_fetch.assert_not_called()
            self.assertEqual(verify_collection(root)["status"], "passed")

    def test_uncertain_lost_headers_hold_the_entire_resume(self):
        clock = Clock()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            selected = self.selection(base, ["Q1", "Q2"])
            root = base / "run"
            with RunState.create(selected, root, now_fn=clock.utc) as store:
                settings = store.manifest["request_settings"]
                request = {"method": "GET", "url": settings["endpoint"], "headers": settings["headers"],
                           "parameters": dict(settings["action_parameters"], ids="Q1")}
                attempt = store.reserve(["Q1"], request)
                store.dispatch(attempt["attempt_id"])
            no_fetch = Mock(side_effect=AssertionError("lost header wait must hold fresh QIDs too"))
            with self.assertRaisesRegex(ValueError, "server_wait_unknown"):
                resume(root, fetcher=no_fetch, sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            no_fetch.assert_not_called()
