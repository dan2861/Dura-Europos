"""Generic discovery capture uses invented HTTP responses only."""
import gzip
import io
from http.client import HTTPResponse, IncompleteRead
import unittest
from urllib.parse import parse_qs, urlsplit

from scripts.idea_json_backup.client import collect_http, request_url


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


if __name__ == "__main__":
    unittest.main()
