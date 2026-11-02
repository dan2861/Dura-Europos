"""Offline transport tests: no public service is contacted."""
import gzip
import unittest
from urllib.parse import parse_qs, urlsplit

from scripts.idea_json_backup.transport import collect_http, request_options


class FakeResponse:
    def __init__(self, body=b'{}', *, status=200, headers=None, error=None):
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.error = error
        self.closed = False

    def read(self, size):
        if self.body:
            body, self.body = self.body, b''
            return body
        if self.error:
            raise self.error
        return b''

    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.response


class BatchTransportTests(unittest.TestCase):
    def test_one_request_has_fixed_scope_and_identifies_operator(self):
        transport = FakeTransport(FakeResponse(b'{"success":1}'))
        capture = collect_http(['Q2', 'Q1'], transport=transport)
        self.assertTrue(capture.complete)
        self.assertIsNone(capture.error)
        self.assertEqual(capture.encoded, b'{"success":1}')
        self.assertEqual(capture.body, capture.encoded)
        self.assertEqual(len(transport.calls), 1)
        url, headers, timeout = transport.calls[0]
        self.assertEqual(urlsplit(url).scheme, 'https')
        self.assertEqual(urlsplit(url).netloc, 'www.wikidata.org')
        self.assertEqual(parse_qs(urlsplit(url).query), {
            'action': ['wbgetentities'], 'ids': ['Q2|Q1'],
            'format': ['json'], 'formatversion': ['2'],
            'redirects': ['no'], 'maxlag': ['5'],
        })
        self.assertIn('github.com/dan2861/Dura-Europos', headers['User-Agent'])
        self.assertEqual(headers['Accept-Encoding'], 'gzip, identity')
        self.assertEqual(headers['Accept'], 'application/json')
        self.assertGreater(timeout, 0)
        self.assertIsNotNone(capture.headers_received_at)
        self.assertIsNotNone(capture.received_at)
        self.assertTrue(transport.response.closed)

    def test_gzip_retains_encoded_and_decoded_bytes(self):
        original = b'{"future":{"id":"0007"}}'
        encoded = gzip.compress(original)
        capture = collect_http(['Q1'], transport=FakeTransport(FakeResponse(
            encoded, headers={'Content-Encoding': 'gzip', 'Content-Length': str(len(encoded))},
        )))
        self.assertTrue(capture.complete)
        self.assertEqual(capture.encoded, encoded)
        self.assertEqual(capture.body, original)
        self.assertEqual(capture.headers['content-encoding'], 'gzip')

    def test_invalid_gzip_retains_only_encoded_evidence(self):
        encoded = gzip.compress(b'{}')[:-4]
        capture = collect_http(['Q1'], transport=FakeTransport(FakeResponse(
            encoded, headers={'Content-Encoding': 'gzip'},
        )))
        self.assertFalse(capture.complete)
        self.assertIsNotNone(capture.error)
        self.assertEqual(capture.encoded, encoded)
        self.assertIsNone(capture.body)

    def test_content_length_mismatch_is_incomplete(self):
        capture = collect_http(['Q1'], transport=FakeTransport(FakeResponse(
            b'{}', headers={'Content-Length': '3'},
        )))
        self.assertFalse(capture.complete)
        self.assertIn('Content-Length', capture.error)
        self.assertEqual(capture.encoded, b'{}')
        self.assertIsNone(capture.received_at)

    def test_unknown_content_encoding_is_rejected_with_encoded_bytes(self):
        capture = collect_http(['Q1'], transport=FakeTransport(FakeResponse(
            b'compressed', headers={'Content-Encoding': 'br'},
        )))
        self.assertFalse(capture.complete)
        self.assertIn('encoding', capture.error)
        self.assertEqual(capture.encoded, b'compressed')
        self.assertIsNone(capture.body)

    def test_http_error_and_retry_header_are_preserved_without_retry(self):
        transport = FakeTransport(FakeResponse(b'busy', status=503, headers={'Retry-After': '20'}))
        capture = collect_http(['Q1'], transport=transport)
        self.assertEqual(capture.status, 503)
        self.assertEqual(capture.body, b'busy')
        self.assertEqual(capture.headers['retry-after'], '20')
        self.assertIn('503', capture.error)
        self.assertEqual(len(transport.calls), 1)

    def test_redirect_is_evidence_and_not_followed(self):
        transport = FakeTransport(FakeResponse(b'moved', status=302, headers={'Location': 'https://example.invalid/'}))
        capture = collect_http(['Q1'], transport=transport)
        self.assertIn('302', capture.error)
        self.assertEqual(capture.headers['location'], 'https://example.invalid/')
        self.assertEqual(len(transport.calls), 1)

    def test_read_failure_retains_headers_and_partial_bytes(self):
        capture = collect_http(['Q1'], transport=FakeTransport(FakeResponse(
            b'partial', headers={'Retry-After': '20'}, error=OSError('interrupted body'),
        )))
        self.assertFalse(capture.complete)
        self.assertEqual(capture.encoded, b'partial')
        self.assertEqual(capture.headers['retry-after'], '20')
        self.assertIsNotNone(capture.headers_received_at)
        self.assertIsNone(capture.body)

    def test_invalid_scope_never_opens_transport(self):
        invalid = [[], ['Q1', 'Q1'], ['q1'], ['Q0'], ['Q01'], ['../Q1'], 'Q1', ['Q1'] * 51]
        for qids in invalid:
            with self.subTest(qids=qids):
                transport = FakeTransport(FakeResponse())
                with self.assertRaises(ValueError):
                    collect_http(qids, transport=transport)
                self.assertEqual(transport.calls, [])

    def test_invalid_deadline_or_agent_is_rejected(self):
        for deadline in (0, -1, float('nan'), float('inf'), 61, True):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValueError):
                    request_options(['Q1'], timeout_seconds=deadline)
        for agent in ('', 'bad\r\nheader'):
            with self.subTest(agent=agent):
                with self.assertRaises(ValueError):
                    request_options(['Q1'], user_agent=agent)
