"""Invented HTTP responses only; this suite never contacts a public endpoint."""
import time
import unittest

from scripts.sample_backup import retrieval
from scripts.sample_backup.schema import request_options


class Response:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.offset = 0

    def read(self, size):
        result = self.body[self.offset:self.offset + size]
        self.offset += len(result)
        return result

    def close(self):
        pass


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class RetrievalTests(unittest.TestCase):
    def test_relative_redirect_and_final_bytes_have_exact_trace(self):
        transport = Transport([Response(302, headers={"Location": "/final.json"}),
                               Response(200, b'{ "entities":{} }\r\n')])
        trace, chunks = [], []
        outcome = retrieval.collect_http("https://example.invalid/start", request_options(),
                                         transport, trace.append, chunks.append)
        self.assertIsNone(outcome["error"])
        self.assertTrue(outcome["complete"])
        self.assertEqual(b"".join(chunks), b'{ "entities":{} }\r\n')
        self.assertEqual(trace, [
            {"url": "https://example.invalid/start", "status_code": 302, "location": "/final.json"},
            {"url": "https://example.invalid/final.json", "status_code": 200, "location": None}])
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0][1]["Accept"], "application/json")
        self.assertLessEqual(transport.calls[1][2], transport.calls[0][2])

    def test_redirect_bounds_errors_and_partial_bytes(self):
        from http.client import IncompleteRead
        class Broken(Response):
            def read(self, size):
                raise IncompleteRead(b"partial\x00bytes", 50)
        cases = [
            ([Response(302, headers={"Location": f"/r{i}"}) for i in range(6)], 6, "sixth", b""),
            ([Response(302, headers={"Location": "/start"})], 1, "loop", b""),
            ([Response(302, b"redirect failure")], 1, "Location", b"redirect failure"),
            ([Response(429, b"rate limit")], 1, "429", b"rate limit"),
            ([OSError("DNS failure")], 1, "DNS", b""),
            ([Broken(200)], 1, "IncompleteRead", b"partial\x00bytes"),
        ]
        for responses, calls, error, body in cases:
            with self.subTest(error=error):
                transport = Transport(responses)
                trace, chunks = [], []
                result = retrieval.collect_http("https://example.invalid/start", request_options(),
                                                transport, trace.append, chunks.append)
                self.assertIn(error, result["error"])
                self.assertEqual(len(transport.calls), calls)
                self.assertEqual(b"".join(chunks), body)
                if error == "DNS":
                    self.assertEqual(trace, [])
                if error == "IncompleteRead":
                    self.assertFalse(result["complete"])

    def test_hard_deadline_retains_received_trace_and_partial_bytes(self):
        before = time.monotonic()
        result = retrieval.retrieve("Q42", timeout_seconds=0.6, worker=slow_worker)
        self.assertLess(time.monotonic() - before, 2.0)
        self.assertIn("deadline", result.error)
        self.assertEqual(result.body, b"already received")
        self.assertEqual(result.trace[0]["status_code"], 200)
        self.assertFalse(result.complete)

    def test_usability_is_not_claim_representability(self):
        from scripts.sample_backup.jsoncodec import dumps
        from test_sample_backup_transform import entity
        source = entity()
        del source["claims"]["P217"][0]["id"]
        self.assertEqual(retrieval.usable_entity(dumps({"entities": {"Q42": source}}))["id"], "Q42")
        for body in (b"not JSON", b'{"error":{}}', b'{"entities":{}}',
                     b'{"entities":{"a":{},"b":{}}}', b'{"entities":{"Q42":{"id":"Q42","missing":""}}}',
                     b'{"entities":{"Q42":{"id":"Q42","type":"item","x":1,"x":2}}}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                retrieval.usable_entity(body)

    def test_five_redirects_succeed_and_received_http_errors_are_retained(self):
        responses = [Response(301, headers={"Location": f"/step{i}"}) for i in range(5)]
        responses.append(Response(200, b"final"))
        transport = Transport(responses)
        trace, chunks = [], []
        result = retrieval.collect_http("https://example.invalid/start", request_options(),
                                        transport, trace.append, chunks.append)
        self.assertIsNone(result["error"])
        self.assertEqual(len(trace), 6)
        self.assertEqual(b"".join(chunks), b"final")
        for code in (404, 429, 500):
            trace, chunks = [], []
            result = retrieval.collect_http("https://example.invalid/error", request_options(),
                                            Transport([Response(code, b"failure\x00body")]), trace.append, chunks.append)
            self.assertEqual(len(trace), 1)
            self.assertTrue(result["complete"])
            self.assertIn(str(code), result["error"])
            self.assertEqual(b"".join(chunks), b"failure\x00body")

    def test_orchestration_retains_failure_bytes_and_continues_without_retry(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from scripts import export_sample_backup as app
        from scripts.sample_backup.storage import RunStore
        from scripts.sample_backup.jsoncodec import dumps
        from test_sample_backup_transform import entity
        calls = []
        def fetch(qid):
            calls.append(qid)
            if qid == "Q42":
                return retrieval.Result(b"\x00failure bytes", [], True, "HTTP 500")
            source = entity("Q1", {})
            return retrieval.Result(dumps({"entities": {"Q1": source}}).encode(), [], True,
                                    None, "2026-01-01T00:00:00Z", source)
        with TemporaryDirectory() as directory:
            store = RunStore.create(Path(directory), ["Q42", "Q1"], "synthetic")
            app.collect_requests(store, fetch=fetch)
            self.assertEqual(calls, ["Q42", "Q1"])
            first, second = store.manifest["items"]
            self.assertEqual(first["retrieval_status"], "failed")
            self.assertEqual(set(first["error"]), {"stage", "message", "body_path", "body_complete"})
            self.assertEqual((store.root / first["error"]["body_path"]).read_bytes(), b"\x00failure bytes")
            self.assertTrue(first["error"]["body_complete"])
            self.assertEqual(second["source_json"], "original/Q1.json")
            self.assertEqual(second["retrieval_status"], "succeeded")

    def test_saving_failure_or_interruption_stops_and_leaves_unattempted_pending(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from scripts import export_sample_backup as app
        from scripts.sample_backup.storage import RunStore
        from scripts.sample_backup.jsoncodec import dumps
        from test_sample_backup_transform import entity
        for mode in ("saving", "interrupt"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                store = RunStore.create(Path(directory), ["Q42", "Q1"], "synthetic")
                calls = []
                def fetch(qid):
                    calls.append(qid)
                    if mode == "interrupt":
                        raise KeyboardInterrupt()
                    source = entity()
                    return retrieval.Result(dumps({"entities": {qid: source}}).encode(), [], True,
                                            None, "2026-01-01T00:00:00Z", source)
                with patch.object(store, "save_original", side_effect=OSError("disk failure")):
                    app.collect_requests(store, fetch=fetch)
                self.assertEqual(calls, ["Q42"])
                self.assertEqual([e["retrieval_status"] for e in store.manifest["items"]], ["failed", "pending"])
                self.assertIsNone(store.manifest["items"][0]["source_json"])
                self.assertEqual(store.manifest["validation_summary"]["status"], "failed")

    def test_capture_writer_handles_short_writes_and_reports_storage_failure(self):
        import io
        class ShortWriter(io.BytesIO):
            def write(self, body):
                return super().write(body[:2])
        target = ShortWriter()
        retrieval.write_all(target, b"captured response")
        self.assertEqual(target.getvalue(), b"captured response")
        class FailedWriter:
            def write(self, body):
                return 0
        with self.assertRaises(OSError):
            retrieval.write_all(FailedWriter(), b"received")

    def test_deep_unusable_json_keeps_captured_body(self):
        result = retrieval.retrieve("Q42", timeout_seconds=2, worker=deep_worker)
        self.assertIsNotNone(result.error)
        self.assertIsNone(result.entity)
        self.assertGreater(len(result.body), 2000)

    def test_eof_arriving_after_total_deadline_is_failure(self):
        class SlowEOF(Response):
            def read(self, size):
                time.sleep(0.04)
                return b""
        options = request_options()
        options["timeout_seconds"] = 0.02
        result = retrieval.collect_http("https://example.invalid", options,
                                        Transport([SlowEOF(200)]), lambda x: None, lambda x: None)
        self.assertIsNotNone(result["error"])
        self.assertFalse(result["complete"])

    def test_http_client_uses_get_explicit_headers_and_disabled_automatic_redirects(self):
        from unittest.mock import patch
        options = request_options()
        with patch.object(retrieval, "build_opener") as builder:
            response = Response(200, b"invented")
            builder.return_value.open.return_value = response
            actual = retrieval.HTTPTransport().open("https://example.invalid/Q42.json", options["headers"], 12)
            request = builder.return_value.open.call_args.args[0]
            self.assertIs(actual, response)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, "https://example.invalid/Q42.json")
            self.assertEqual(request.get_header("Accept"), "application/json")
            self.assertIn("IDEA-sample-backup/", request.get_header("User-agent"))
            self.assertIsInstance(builder.call_args.args[0], retrieval.NoRedirect)
            self.assertIsNone(builder.call_args.args[0].redirect_request(None, None, 302, None, None, "/next"))


def slow_worker(url, options, folder):
    from pathlib import Path
    import json
    path = Path(folder)
    (path / "trace").write_text(json.dumps({"url": url, "status_code": 200, "location": None}) + "\n")
    (path / "body").write_bytes(b"already received")
    time.sleep(10)


def deep_worker(url, options, folder):
    from pathlib import Path
    import json
    path = Path(folder)
    (path / "body").write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
    (path / "trace").write_text(json.dumps({"url": url, "status_code": 200, "location": None}) + "\n")
    (path / "result").write_text(json.dumps({"error": None, "complete": True, "retrieved_at": "2026-01-01T00:00:00Z"}))
