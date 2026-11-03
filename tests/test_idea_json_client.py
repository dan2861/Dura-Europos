"""Generic discovery capture uses invented HTTP responses only."""
import gzip
import io
import json
import multiprocessing
import os
import time
from http.client import HTTPResponse, IncompleteRead
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from scripts.idea_json_backup.client import collect_http, fetch, network_worker, request_url, write_all


def request(endpoint="https://query.wikidata.org/sparql"):
    return {"method": "GET", "url": endpoint,
            "parameters": {"query": "SELECT ?item WHERE {}", "format": "json"},
            "headers": {"Accept": "application/sparql-results+json", "Accept-Encoding": "gzip, identity",
                        "User-Agent": "IDEA-JSON-Backup/0.1.0 (https://github.com/dan2861/Dura-Europos)"}}


class Response:
    def __init__(self, body=b"{}", *, status=200, headers=None, error=None):
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.error = error

    def read(self, size):
        if self.body:
            value, self.body = self.body, b""
            return value
        if self.error:
            raise self.error
        return b""

    def close(self):
        pass


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.response


def raw_response(raw):
    class Socket:
        def makefile(self, mode):
            return io.BytesIO(raw)
    response = HTTPResponse(Socket())
    response.begin()
    return response


class ClientHTTPTests(unittest.TestCase):
    def test_exact_request_and_list_headers_without_secrets(self):
        transport = Transport(Response(headers={"Content-Length": "2", "Date": "invented-date",
                                                "X-Database-Lag": "0", "Set-Cookie": "secret"}))
        result = collect_http(request(), transport=transport)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(parse_qs(urlsplit(transport.calls[0][0]).query), request()["parameters"] | {
            "query": ["SELECT ?item WHERE {}"], "format": ["json"]})
        self.assertEqual(result.encoded, b"{}")
        self.assertEqual(result.decoded, b"{}")
        self.assertEqual(result.headers["content-length"], ["2"])
        self.assertEqual(result.headers["date"], ["invented-date"])
        self.assertNotIn("set-cookie", result.headers)
        self.assertTrue(result.headers_observed)
        self.assertTrue(result.receipt_complete)
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.response_received_at)
        self.assertIsInstance(result.response_elapsed_ms, int)

    def test_invalid_request_never_opens_transport(self):
        values = [dict(request(), url="https://example.org/sparql"), dict(request(), method="POST"),
                  dict(request(), headers={}), dict(request(), parameters={"query": None})]
        for value in values:
            with self.subTest(value=value):
                transport = Transport(Response())
                with self.assertRaises(ValueError):
                    collect_http(value, transport=transport)
                self.assertEqual(transport.calls, [])
        for value in (0, -1, True, float("inf"), 61):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                collect_http(request(), timeout_seconds=value, transport=Transport(Response()))

    def test_gzip_preserves_encoded_and_decoded_bytes(self):
        encoded = gzip.compress(b'{"invented":true}', mtime=0)
        result = collect_http(request(), transport=Transport(Response(encoded, headers={
            "Content-Encoding": "gzip", "Content-Length": str(len(encoded))})))
        self.assertEqual(result.encoded, encoded)
        self.assertEqual(result.decoded, b'{"invented":true}')
        self.assertTrue(result.receipt_complete)

    def test_decoder_failure_does_not_erase_clean_encoded_receipt(self):
        encoded = gzip.compress(b"{}")[0:-4]
        for body, encoding in ((encoded, "gzip"), (b"{}", "br")):
            with self.subTest(encoding=encoding):
                result = collect_http(request(), transport=Transport(Response(body, headers={
                    "Content-Encoding": encoding, "Content-Length": str(len(body))})))
                self.assertEqual(result.encoded, body)
                self.assertIsNone(result.decoded)
                self.assertTrue(result.receipt_complete)
                self.assertIsNotNone(result.response_received_at)
                self.assertEqual(result.stage, "decoding")
                self.assertIsNotNone(result.error)

    def test_duplicate_framing_and_encoding_values_are_retained_and_rejected(self):
        for extra in (b"Content-Length: 102\r\nContent-Length: 2\r\n",
                      b"Content-Encoding: identity\r\nContent-Encoding: gzip\r\n"):
            with self.subTest(extra=extra):
                result = collect_http(request(), transport=Transport(raw_response(
                    b"HTTP/1.1 200 OK\r\n" + extra + b"Connection: close\r\n\r\n{}")))
                self.assertIsNotNone(result.error)
                self.assertIsNone(result.decoded)
                header = "content-length" if b"Length" in extra else "content-encoding"
                self.assertEqual(len(result.headers[header]), 2)

    def test_http_error_and_retry_after_are_retained_without_retry(self):
        transport = Transport(Response(b"busy", status=503, headers={"Retry-After": "20"}))
        result = collect_http(request(), transport=transport)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.headers["retry-after"], ["20"])
        self.assertEqual(result.decoded, b"busy")
        self.assertTrue(result.receipt_complete)
        self.assertIn("503", result.error)

    def test_read_failure_keeps_partial_bytes_and_headers(self):
        chunks, receipts = [], []
        result = collect_http(request(), transport=Transport(Response(b"first", headers={"Retry-After": "5"},
                                     error=IncompleteRead(b"tail"))),
                              on_headers=receipts.append, on_chunk=chunks.append)
        self.assertEqual(result.encoded, b"firsttail")
        self.assertEqual(chunks, [b"first", b"tail"])
        self.assertEqual(receipts[0]["headers"], {"retry-after": ["5"]})
        self.assertFalse(result.receipt_complete)
        self.assertIsNone(result.response_received_at)

    def test_capture_write_failure_is_saving_stage(self):
        def failed(body):
            raise OSError("invented full disk")
        result = collect_http(request(), transport=Transport(Response(b"evidence")), on_chunk=failed)
        self.assertEqual(result.stage, "saving")
        self.assertEqual(result.encoded, b"evidence")
        self.assertFalse(result.receipt_complete)

    def test_clean_empty_receipt_has_explicit_completeness(self):
        result = collect_http(request(), transport=Transport(Response(b"", headers={"Content-Length": "0"})))
        self.assertEqual(result.encoded, b"")
        self.assertEqual(result.decoded, b"")
        self.assertTrue(result.receipt_complete)
        self.assertIsNotNone(result.response_received_at)

    def test_redirect_is_one_received_response(self):
        transport = Transport(Response(b"moved", status=302, headers={"Location": "https://example.org/"}))
        result = collect_http(request(), transport=transport)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(result.headers["location"], ["https://example.org/"])
        self.assertIn("302", result.error)


def _result(folder, *, decoded=b"{}", encoded=b"{}"):
    folder = Path(folder)
    if encoded:
        (folder / "encoded.body").write_bytes(encoded)
    if decoded:
        (folder / "decoded.body").write_bytes(decoded)
    metadata = {
        "status_code": 200, "headers": {"content-type": ["application/sparql-results+json"]},
        "started_at": "2026-11-03T00:00:00.000000Z",
        "headers_received_at": "2026-11-03T00:00:00.010000Z", "headers_observed": True,
        "response_received_at": "2026-11-03T00:00:00.020000Z", "response_elapsed_ms": 20,
        "receipt_complete": True, "error": None, "stage": "transport", "interrupted": False,
        "encoded_size": len(encoded), "decoded_size": len(decoded) if decoded is not None else None,
    }
    (folder / "result.json").write_text(json.dumps(metadata))


def complete_worker(request, timeout_seconds, folder):
    _result(folder)


def empty_worker(request, timeout_seconds, folder):
    _result(folder, decoded=b"", encoded=b"")


def blocked_worker(request, timeout_seconds, folder):
    folder = Path(folder)
    with (folder / "encoded.body").open("wb") as stream:
        stream.write(b"received prefix")
        stream.flush()
        os.fsync(stream.fileno())
    (folder / "receipt.json").write_text(json.dumps({
        "status_code": 503, "headers": {"retry-after": ["20", "30"]},
        "started_at": "2026-11-03T00:00:00.000000Z",
        "headers_received_at": "2026-11-03T00:00:00.010000Z", "headers_observed": True,
        "receipt_complete": False,
    }))
    time.sleep(10)


def no_outcome_worker(request, timeout_seconds, folder):
    (Path(folder) / "encoded.body").write_bytes(b"orphan evidence")


def known_preheader_failure_worker(request, timeout_seconds, folder):
    metadata = {
        "status_code": None, "headers": {}, "started_at": "2026-11-03T00:00:00.000000Z",
        "headers_received_at": None, "headers_observed": False, "response_received_at": None,
        "response_elapsed_ms": None, "receipt_complete": None, "error": "OSError: unavailable",
        "stage": "transport", "interrupted": False, "encoded_size": 0, "decoded_size": None,
    }
    (Path(folder) / "result.json").write_text(json.dumps(metadata))


class ClientSupervisorTests(unittest.TestCase):
    def test_unsuccessful_exit_after_published_result_is_saving_uncertainty(self):
        class FailedAfterPublish:
            def __init__(self, *, target, args):
                self.args = args
                self.pid = None
                self.exitcode = None

            def start(self):
                self.pid = 42
                complete_worker(*self.args)
                self.exitcode = 1

            def join(self, timeout=None):
                pass

            def is_alive(self):
                return False

        with TemporaryDirectory() as directory, patch(
                "scripts.idea_json_backup.client.multiprocessing.get_context") as context:
            context.return_value.Process.side_effect = FailedAfterPublish
            result = fetch(request(), Path(directory) / "capture")
            self.assertEqual(result.stage, "saving")
            self.assertIn("unsuccessfully", result.error)
            self.assertFalse(result.receipt_complete)
            self.assertIsNone(result.decoded)
            self.assertEqual(result.encoded, b"{}")
            self.assertTrue(result.headers_observed)
            self.assertEqual(result.headers["content-type"], ["application/sparql-results+json"])

    def test_real_worker_records_headers_before_first_body_read(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)

            class ReceiptCheckingResponse(Response):
                def read(self, size):
                    receipt = json.loads((folder / "receipt.json").read_bytes())
                    if receipt["headers"] != {"content-length": ["2"]}:
                        raise AssertionError("receipt not preserved before read")
                    return super().read(size)

            with patch("scripts.idea_json_backup.client.HTTPTransport", return_value=Transport(
                    ReceiptCheckingResponse(b"{}", headers={"Content-Length": "2"}))):
                network_worker(request(), 60, directory)
            self.assertEqual((folder / "encoded.body").read_bytes(), b"{}")
            self.assertEqual((folder / "decoded.body").read_bytes(), b"{}")
            result = json.loads((folder / "result.json").read_bytes())
            self.assertTrue(result["receipt_complete"])
            self.assertEqual(result["encoded_size"], 2)
            self.assertIsNone(result["error"])

    def test_process_start_failure_is_known_preheader_transport_failure(self):
        with TemporaryDirectory() as directory, patch(
                "scripts.idea_json_backup.client.multiprocessing.get_context") as context:
            process = context.return_value.Process.return_value
            process.pid = None
            process.start.side_effect = OSError("invented process start failure")
            result = fetch(request(), Path(directory) / "capture")
            self.assertIs(result.headers_observed, False)
            self.assertEqual(result.stage, "transport")
            self.assertIn("process start failure", result.error)

    def test_complete_worker_and_new_directory_are_preserved(self):
        with TemporaryDirectory() as directory:
            capture = Path(directory) / "capture"
            result = fetch(request(), capture, timeout_seconds=2, worker=complete_worker)
            self.assertIsNone(result.error)
            self.assertTrue(result.receipt_complete)
            self.assertEqual(result.decoded, b"{}")
            self.assertEqual((capture / "encoded.body").read_bytes(), b"{}")
            with self.assertRaises(FileExistsError):
                fetch(request(), capture, worker=complete_worker)

    def test_empty_complete_response_has_no_invented_body_file(self):
        with TemporaryDirectory() as directory:
            capture = Path(directory) / "capture"
            result = fetch(request(), capture, timeout_seconds=2, worker=empty_worker)
            self.assertTrue(result.receipt_complete)
            self.assertEqual(result.decoded, b"")
            self.assertIsNone(result.error)
            self.assertFalse((capture / "encoded.body").exists())
            self.assertFalse((capture / "decoded.body").exists())

    def test_deadline_retains_encoded_bytes_and_all_retry_headers(self):
        before = {process.pid for process in multiprocessing.active_children()}
        with TemporaryDirectory() as directory:
            capture = Path(directory) / "capture"
            result = fetch(request(), capture, timeout_seconds=0.7, worker=blocked_worker)
            self.assertIn("deadline", result.error)
            self.assertFalse(result.receipt_complete)
            self.assertEqual(result.encoded, b"received prefix")
            self.assertEqual(result.headers["retry-after"], ["20", "30"])
            self.assertTrue(result.headers_observed)
            self.assertIsNone(result.decoded)
            self.assertTrue((capture / "receipt.json").is_file())
        self.assertEqual({process.pid for process in multiprocessing.active_children()}, before)

    def test_known_preheader_failure_and_uncertain_receipt_are_distinct(self):
        for worker, expected in ((known_preheader_failure_worker, False), (no_outcome_worker, None)):
            with self.subTest(worker=worker), TemporaryDirectory() as directory:
                result = fetch(request(), Path(directory) / "capture", timeout_seconds=2, worker=worker)
                self.assertIs(result.headers_observed, expected)
                self.assertIsNotNone(result.error)
                self.assertIsNone(result.decoded)

    def test_interruption_and_exited_late_worker_cannot_pass(self):
        class ExitedProcess:
            def __init__(self, *, target, args):
                self.args = args
                self.pid = None

            def start(self):
                self.pid = 42
                complete_worker(*self.args)

            def join(self, timeout=None):
                pass

            def is_alive(self):
                return False

        with TemporaryDirectory() as directory, patch(
                "scripts.idea_json_backup.client.multiprocessing.get_context") as context:
            context.return_value.Process.side_effect = ExitedProcess
            with patch("scripts.idea_json_backup.client.time.monotonic", side_effect=[0, 0, 2]):
                result = fetch(request(), Path(directory) / "late", timeout_seconds=1, worker=complete_worker)
            self.assertIn("deadline", result.error)
            self.assertFalse(result.receipt_complete)
            self.assertIsNone(result.decoded)

        class InterruptedProcess(ExitedProcess):
            def join(self, timeout=None):
                raise KeyboardInterrupt()

        with TemporaryDirectory() as directory, patch(
                "scripts.idea_json_backup.client.multiprocessing.get_context") as context:
            context.return_value.Process.side_effect = InterruptedProcess
            result = fetch(request(), Path(directory) / "interrupted", worker=complete_worker)
            self.assertTrue(result.interrupted)
            self.assertIn("interrupted", result.error)
            self.assertIsNone(result.decoded)
            self.assertEqual(result.encoded, b"{}")

    def test_capture_writer_handles_short_and_failed_writes(self):
        class Stream:
            def __init__(self):
                self.body = b""

            def write(self, value):
                self.body += bytes(value[:2])
                return min(2, len(value))

            def flush(self):
                pass

            def fileno(self):
                return 7

        stream = Stream()
        with patch("scripts.idea_json_backup.client.os.fsync"):
            write_all(stream, b"abcdef")
        self.assertEqual(stream.body, b"abcdef")
        stream.write = lambda value: 0
        with self.assertRaises(OSError):
            write_all(stream, b"lost")


if __name__ == "__main__":
    unittest.main()
