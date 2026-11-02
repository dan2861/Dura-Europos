"""Offline transport tests: no public service is contacted."""
import gzip
from http.client import HTTPResponse
from io import BytesIO
import json
import multiprocessing
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from scripts.idea_json_backup.transport import capture_batch, collect_http, request_options


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
    def test_exited_worker_is_still_late_when_parent_resumes_after_deadline(self):
        class ExitedProcess:
            def __init__(self, *, target, args):
                self.args = args
                self.pid = None

            def start(self):
                self.pid = 7
                complete_worker(*self.args)

            def join(self, timeout=None):
                pass

            def is_alive(self):
                return False

        with patch('scripts.idea_json_backup.transport.multiprocessing.get_context') as context:
            context.return_value.Process.side_effect = ExitedProcess
            with patch('scripts.idea_json_backup.transport.time.monotonic', side_effect=[0, 0, 2]):
                capture = capture_batch(['Q1'], timeout_seconds=1, worker=complete_worker)
        self.assertFalse(capture.complete)
        self.assertIn('deadline', capture.error)
        self.assertEqual(capture.encoded, b'{}')
        self.assertIsNone(capture.body)

    def test_duplicate_content_length_cannot_make_truncated_response_complete(self):
        body = b'{}'
        for lengths in ((len(body) + 100, len(body)), (len(body), len(body))):
            with self.subTest(lengths=lengths):
                raw = (b'HTTP/1.1 200 OK\r\n'
                       + b''.join(f'Content-Length: {length}\r\n'.encode('ascii') for length in lengths)
                       + b'Connection: close\r\n\r\n' + body)
                response = raw_response(raw)
                receipts = []
                capture = collect_http(['Q1'], transport=FakeTransport(response), on_headers=receipts.append)
                self.assertFalse(capture.complete)
                self.assertIn('Content-Length', capture.error)
                self.assertEqual(capture.encoded, body)
                self.assertIsNone(capture.body)
                joined = ', '.join(str(length) for length in lengths)
                self.assertEqual(capture.headers['content-length'], joined)
                self.assertEqual(receipts[0]['headers']['content-length'], joined)
                self.assertIsNotNone(capture.headers_received_at)

    def test_duplicate_content_encoding_is_unresolved_with_original_headers(self):
        body = gzip.compress(b'{}')
        raw = (b'HTTP/1.1 200 OK\r\nContent-Encoding: identity\r\nContent-Encoding: gzip\r\n'
               + f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body)
        capture = collect_http(['Q1'], transport=FakeTransport(raw_response(raw)))
        self.assertFalse(capture.complete)
        self.assertIn('encoding', capture.error)
        self.assertEqual(capture.encoded, body)
        self.assertEqual(capture.headers['content-encoding'], 'identity, gzip')
        self.assertIsNone(capture.body)

    def test_negative_content_length_retains_bytes_but_cannot_complete(self):
        capture = collect_http(['Q1'], transport=FakeTransport(raw_response(
            b'HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n{}',
        )))
        self.assertFalse(capture.complete)
        self.assertIn('Content-Length', capture.error)
        self.assertEqual(capture.encoded, b'{}')
        self.assertEqual(capture.headers['content-length'], '-1')

    def test_caller_owned_capture_directory_retains_timeout_evidence(self):
        with TemporaryDirectory() as directory:
            capture_dir = Path(directory) / 'capture'
            capture = capture_batch(['Q1'], timeout_seconds=0.7, worker=blocked_worker,
                                    capture_directory=capture_dir)
            self.assertIn('deadline', capture.error)
            self.assertEqual((capture_dir / 'encoded.body').read_bytes(), b'already received')
            self.assertEqual(json.loads((capture_dir / 'receipt.json').read_text())['headers'],
                             {'retry-after': '20'})
            with self.assertRaises(FileExistsError):
                capture_batch(['Q1'], worker=complete_worker, capture_directory=capture_dir)

    def test_response_close_failure_retains_captured_evidence(self):
        class CloseFailure(FakeResponse):
            def close(self):
                raise OSError('close failed')

        capture = collect_http(['Q1'], transport=FakeTransport(CloseFailure(b'{}')))
        self.assertEqual(capture.encoded, b'{}')
        self.assertIsNotNone(capture.error)
        self.assertIn('close failed', capture.error)
        self.assertFalse(capture.complete)

    def test_supervised_worker_returns_complete_capture(self):
        capture = capture_batch(['Q1'], timeout_seconds=2, worker=complete_worker)
        self.assertTrue(capture.complete)
        self.assertIsNone(capture.error)
        self.assertEqual(capture.encoded, b'{}')
        self.assertEqual(capture.body, b'{}')
        self.assertEqual(capture.status, 200)

    def test_absolute_deadline_terminates_worker_and_retains_evidence(self):
        before_pids = {process.pid for process in multiprocessing.active_children()}
        before = time.monotonic()
        capture = capture_batch(['Q1'], timeout_seconds=0.7, worker=blocked_worker)
        self.assertLess(time.monotonic() - before, 2)
        self.assertFalse(capture.complete)
        self.assertIn('deadline', capture.error)
        self.assertEqual(capture.encoded, b'already received')
        self.assertEqual(capture.headers['retry-after'], '20')
        self.assertIsNotNone(capture.headers_received_at)
        self.assertIsNone(capture.body)
        self.assertEqual({process.pid for process in multiprocessing.active_children()}, before_pids)

    def test_worker_exit_without_outcome_keeps_partial_capture(self):
        capture = capture_batch(['Q1'], timeout_seconds=2, worker=unfinished_worker)
        self.assertFalse(capture.complete)
        self.assertIn('outcome', capture.error)
        self.assertEqual(capture.encoded, b'already received')
        self.assertEqual(capture.headers['retry-after'], '20')

    def test_keyboard_interrupt_terminates_worker_and_keeps_partial_capture(self):
        class InterruptProcess:
            def __init__(self, *, target, args):
                self.args = args
                self.pid = None
                self.alive = False
                self.joins = 0

            def start(self):
                self.pid = 7
                self.alive = True
                unfinished_worker(*self.args)

            def join(self, timeout=None):
                self.joins += 1
                if self.joins == 1:
                    raise KeyboardInterrupt()

            def is_alive(self):
                return self.alive

            def terminate(self):
                self.alive = False

            def kill(self):
                self.alive = False

        with patch('scripts.idea_json_backup.transport.multiprocessing.get_context') as context:
            context.return_value.Process.side_effect = InterruptProcess
            capture = capture_batch(['Q1'], timeout_seconds=1, worker=unfinished_worker)
        self.assertTrue(capture.interrupted)
        self.assertFalse(capture.complete)
        self.assertIn('interrupted', capture.error)
        self.assertEqual(capture.encoded, b'already received')

    def test_http_client_has_no_automatic_redirects(self):
        from scripts.idea_json_backup.transport import HTTPTransport, NoRedirect
        with patch('scripts.idea_json_backup.transport.build_opener') as builder:
            expected = FakeResponse()
            builder.return_value.open.return_value = expected
            options = request_options(['Q1'])
            self.assertIs(HTTPTransport().open(options['url'], options['headers'], 5), expected)
            request = builder.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Accept'), 'application/json')
            self.assertIsInstance(builder.call_args.args[0], NoRedirect)
            self.assertIsNone(builder.call_args.args[0].redirect_request(None, None, 302, None, None, '/next'))

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


def unfinished_worker(qids, options, folder):
    """Durable synthetic receipt/body; intentionally no outcome."""
    path = Path(folder)
    receipt = {'status': 200, 'headers': {'retry-after': '20'},
               'started_at': '2026-11-02T12:00:00Z',
               'headers_received_at': '2026-11-02T12:00:01Z'}
    with (path / 'receipt.json').open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    with (path / 'encoded.body').open('wb') as stream:
        stream.write(b'already received')
        stream.flush()
        os.fsync(stream.fileno())


def blocked_worker(qids, options, folder):
    unfinished_worker(qids, options, folder)
    time.sleep(10)


def complete_worker(qids, options, folder):
    path = Path(folder)
    (path / 'encoded.body').write_bytes(b'{}')
    (path / 'decoded.body').write_bytes(b'{}')
    (path / 'result.json').write_text(json.dumps({
        'status': 200, 'headers': {}, 'complete': True, 'error': None,
        'started_at': '2026-11-02T12:00:00Z',
        'headers_received_at': '2026-11-02T12:00:01Z',
        'received_at': '2026-11-02T12:00:02Z', 'interrupted': False,
    }), encoding='utf-8')


def raw_response(raw):
    class Socket:
        def makefile(self, mode):
            return BytesIO(raw)

    response = HTTPResponse(Socket())
    response.begin()
    return response
