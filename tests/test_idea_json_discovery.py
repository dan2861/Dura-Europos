"""Invented discovery responses and a fake clock; no external requests."""
import json
import gzip
from functools import partial
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.idea_json_backup.client import FetchResult, fetch, network_worker
from scripts.idea_json_backup.discovery import discover
from scripts.idea_json_backup.selection_verify import verify_selection


def body(*qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + qid}} for qid in qids]}}).encode()


def fixture_worker(request, timeout_seconds, directory):
    """Real capture worker with invented streaming gzip and no live opener."""
    class Response:
        status = 200

        def __init__(self):
            value = body("Q10", "Q2") if request["url"] == "https://query.wikidata.org/sparql" else body("Q2", "Q1")
            self.value = gzip.compress(value, mtime=0)
            self.headers = {"Content-Length": str(len(self.value)), "Content-Encoding": "gzip"}

        def read(self, size):
            value, self.value = self.value[:11], self.value[11:]
            return value

        def close(self):
            pass

    class Transport:
        def open(self, url, headers, timeout):
            return Response()

    with patch("scripts.idea_json_backup.client.HTTPTransport", return_value=Transport()), patch(
            "socket.socket.connect", side_effect=AssertionError("External network forbidden in fixture")):
        network_worker(request, timeout_seconds, directory)


class Clock:
    def __init__(self):
        self.seconds = 0
        self.calls = []

    def monotonic(self):
        return self.seconds

    def sleep(self, duration):
        self.seconds += duration

    def utc(self):
        return (datetime(2026, 11, 3, 12, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ")

    def result(self, payload, *, status=200, headers=None, complete=True, error=None, stage="transport"):
        return FetchResult(payload, payload if complete else None, status, headers or {}, self.utc(),
                           self.utc(), True, self.utc() if complete else None, 0 if complete else None,
                           complete, error, stage=stage)


class DiscoveryTests(unittest.TestCase):
    def test_spawned_streaming_capture_to_independent_selection_audit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            discover(root, kind="synthetic", fetcher=partial(fetch, worker=fixture_worker))
            self.assertEqual((root / "qids.txt").read_bytes(), b"Q1\nQ2\nQ10\n")
            self.assertEqual(verify_selection(root), {"status": "passed", "findings": []})

    def test_selection_parent_sync_failure_prevents_any_dispatch(self):
        from scripts.idea_json_backup import files
        original = files._sync
        clock = Clock()
        calls = []
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"

            def sync(path):
                if Path(path) == root.parent:
                    raise OSError("selection parent sync failed")
                return original(path)

            def fetcher(*args, **kwargs):
                calls.append(True)
                return clock.result(body("Q1"))

            with patch.object(files, "_sync", side_effect=sync), self.assertRaises(OSError):
                self.invoke(root, clock, fetcher)
            self.assertEqual(calls, [])

    def test_saving_failure_stops_with_explicit_saving_outcome(self):
        clock = Clock()
        calls = []

        def fetcher(*args, **options):
            calls.append(clock.seconds)
            return clock.result(b"partial", status=503, complete=False,
                                error="durable capture write failed", stage="saving")

        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            with self.assertRaises(OSError):
                self.invoke(root, clock, fetcher)
            metadata = json.loads((root / "selection.json").read_bytes())
            self.assertEqual(calls, [0])
            self.assertEqual(metadata["sources"][0]["attempts"][0]["outcome"], "saving_failure")
            self.assertEqual(metadata["sources"][0]["attempts"][0]["error"]["retryable"], False)
            self.assertIsNone(metadata["qid_list"])

    def test_cooldown_is_measured_from_recorded_attempt_completion(self):
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
            metadata = self.invoke(Path(directory) / "selection", clock,
                                   lambda *args, **kwargs: clock.result(body("Q1")))
            for source in metadata["sources"]:
                attempt = source["attempts"][0]
                start = datetime.fromisoformat(attempt["finished_at"].replace('Z', '+00:00'))
                end = datetime.fromisoformat(attempt["next_dispatch_at"].replace('Z', '+00:00'))
                self.assertGreaterEqual((end - start).total_seconds(), 1)

    def invoke(self, root, clock, fetcher):
        return discover(root, kind="synthetic", fetcher=fetcher, sleep=clock.sleep,
                        monotonic=clock.monotonic, utcnow=clock.utc)

    def test_queries_both_graphs_serially_and_freezes_numeric_union(self):
        clock = Clock()
        calls = []

        def fetcher(request, capture_directory, **options):
            calls.append((request, clock.seconds))
            return clock.result(body("Q10", "Q2") if len(calls) == 1 else body("Q2", "Q1"))

        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            metadata = self.invoke(root, clock, fetcher)
            self.assertEqual((root / "qids.txt").read_bytes(), b"Q1\nQ2\nQ10\n")
            self.assertEqual([when for request, when in calls], [0, 1])
            self.assertIn('query.wikidata.org', calls[0][0]["url"])
            self.assertIn('query-scholarly.wikidata.org', calls[1][0]["url"])
            self.assertEqual(metadata["sources"][0]["attempts"][0]["receipt_complete"], True)
            self.assertEqual(metadata["frozen_at"], clock.utc())
            self.assertEqual(verify_selection(root), {"status": "passed", "findings": []})

    def test_retry_after_and_backoff_apply_before_retry_and_next_graph(self):
        clock = Clock()
        calls = []

        def fetcher(request, capture_directory, **options):
            calls.append(clock.seconds)
            if len(calls) == 1:
                return clock.result(b"busy", status=503, headers={"retry-after": ["2", "20"]}, error="HTTP 503")
            if len(calls) == 2:
                return clock.result(b"busy", status=429, headers={"retry-after": ["Tue, 03 Nov 2026 12:00:30 GMT"]}, error="HTTP 429")
            return clock.result(body("Q1"))

        with TemporaryDirectory() as directory:
            metadata = self.invoke(Path(directory) / "selection", clock, fetcher)
            self.assertEqual(calls, [0, 20, 30, 31])
            self.assertEqual(len(metadata["sources"][0]["attempts"]), 3)

    def test_failed_graph_retains_all_attempts_without_freezing(self):
        clock = Clock()
        calls = []

        def fetcher(request, capture_directory, **options):
            calls.append(clock.seconds)
            return clock.result(body("Q1"), complete=False, error="incomplete framing")

        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            with self.assertRaises(ValueError):
                self.invoke(root, clock, fetcher)
            metadata = json.loads((root / "selection.json").read_bytes())
            self.assertEqual(calls, [0, 5, 15])
            self.assertEqual(metadata["sources"][0]["outcome"], "failed")
            self.assertEqual(metadata["sources"][1]["outcome"], "pending")
            self.assertIsNone(metadata["qid_list"])
            self.assertFalse((root / "qids.txt").exists())
            self.assertEqual(len(list((root / "sources").glob("*.encoded"))), 3)
