"""Invented discovery responses and a fake clock; no external requests."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.client import FetchResult
from scripts.idea_json_backup.discovery import discover


def body(*qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + qid}} for qid in qids]}}).encode()


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
