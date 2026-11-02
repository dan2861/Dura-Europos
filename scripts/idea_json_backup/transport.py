"""One identified HTTP batch; capture evidence without retries or redirects."""
import gzip
import json
import math
import multiprocessing
import os
import re
import tempfile
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = "https://www.wikidata.org/w/api.php"
DEFAULT_USER_AGENT = "IDEA-JSON-Backup/0.1.0 (https://github.com/dan2861/Dura-Europos)"
HEADER_NAMES = {"content-length", "content-type", "content-encoding", "retry-after", "location"}


@dataclass
class Capture:
    encoded: bytes
    body: bytes | None
    status: int | None
    headers: dict
    complete: bool
    error: str | None
    started_at: str | None
    headers_received_at: str | None
    received_at: str | None
    interrupted: bool = False


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_options(qids, *, timeout_seconds=60, user_agent=DEFAULT_USER_AGENT):
    if (not isinstance(qids, (list, tuple)) or not 1 <= len(qids) <= 50
            or any(not isinstance(qid, str) or not re.fullmatch(r"Q[1-9][0-9]*", qid) for qid in qids)
            or len(set(qids)) != len(qids)):
        raise ValueError("Expected 1–50 distinct canonical item QIDs")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60):
        raise ValueError("Deadline must be positive and at most 60 seconds")
    if not isinstance(user_agent, str) or not user_agent.strip() or any(c in user_agent for c in "\r\n"):
        raise ValueError("A nonempty identifying User-Agent is required")
    parameters = {
        "action": "wbgetentities", "ids": "|".join(qids), "format": "json",
        "formatversion": "2", "redirects": "no", "maxlag": "5",
    }
    return {
        "url": ENDPOINT + "?" + urlencode(parameters),
        "headers": {"Accept": "application/json", "Accept-Encoding": "gzip, identity", "User-Agent": user_agent},
        "timeout_seconds": timeout_seconds,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPTransport:
    def open(self, url, headers, timeout):
        try:
            return build_opener(NoRedirect()).open(Request(url, headers=headers, method="GET"), timeout=timeout)
        except HTTPError as response:
            return response


def collect_http(qids, *, transport=None, timeout_seconds=60, user_agent=DEFAULT_USER_AGENT,
                 on_headers=None, on_chunk=None):
    """Capture a single request; injected transport keeps tests fully offline.

    The process supervisor provides the hard deadline. Local monotonic checks
    also reject a response that reaches clean EOF after its allotted interval.
    """
    options = request_options(qids, timeout_seconds=timeout_seconds, user_agent=user_agent)
    deadline = time.monotonic() + timeout_seconds
    started_at = _now()
    chunks = []
    response = None
    headers = {}
    status = None
    headers_received_at = None
    received_at = None
    capture = None
    try:
        response = (transport or HTTPTransport()).open(options["url"], options["headers"], timeout_seconds)
        status = response.status
        header_values = {}
        for key, value in response.headers.items():
            name = key.lower()
            if name in HEADER_NAMES:
                header_values.setdefault(name, []).append(str(value))
        # HTTPMessage.items() preserves repeated fields. Do not let a later
        # value conceal the framing/encoding rule used by http.client.
        headers = {name: ", ".join(values) for name, values in header_values.items()}
        headers_received_at = _now()
        if on_headers:
            on_headers({"status": status, "headers": headers, "started_at": started_at,
                        "headers_received_at": headers_received_at})
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("total response deadline exceeded")
            chunk = response.read(65536)
            if chunk:
                chunks.append(chunk)
                if on_chunk:
                    on_chunk(chunk)
            if time.monotonic() >= deadline:
                raise TimeoutError("total response deadline exceeded")
            if not chunk:
                break
        encoded = b"".join(chunks)
        if len(header_values.get("content-length", [])) > 1:
            raise OSError("ambiguous Content-Length headers")
        length = headers.get("content-length")
        if length is not None and (not re.fullmatch(r"[0-9]+", length) or len(encoded) != int(length)):
            raise OSError("incomplete response: Content-Length mismatch")
        received_at = _now()
        if len(header_values.get("content-encoding", [])) > 1:
            raise ValueError("ambiguous content encoding headers")
        encoding = headers.get("content-encoding", "identity").strip().lower()
        if encoding == "identity":
            body = encoded
        elif encoding == "gzip":
            body = gzip.decompress(encoded)
        else:
            raise ValueError(f"unsupported content encoding: {encoding}")
        capture = Capture(encoded, body, status, headers, True,
                          None if status == 200 else f"HTTP status {status}",
                          started_at, headers_received_at, received_at)
    except Exception as exc:
        partial = getattr(exc, "partial", b"")
        if isinstance(partial, bytes) and partial:
            chunks.append(partial)
            if on_chunk:
                on_chunk(partial)
        capture = Capture(b"".join(chunks), None, status, headers, False,
                          f"{type(exc).__name__}: {exc}", started_at, headers_received_at, received_at)
    finally:
        if response is not None:
            try:
                response.close()
            except Exception as exc:
                # Closing cannot erase already captured response evidence.
                if capture is not None:
                    capture.error = capture.error or f"{type(exc).__name__}: {exc}"
                    capture.complete = False
    return capture


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_all(stream, body):
    remaining = memoryview(body)
    while remaining:
        count = stream.write(remaining)
        if not isinstance(count, int) or count <= 0:
            raise OSError("incomplete response capture write")
        remaining = remaining[count:]
    stream.flush()
    os.fsync(stream.fileno())


def _publish(path, body):
    staging = path.with_name(path.name + ".staging")
    with staging.open("xb", buffering=0) as stream:
        _write_all(stream, body)
    os.replace(staging, path)
    _sync_directory(path.parent)


def network_worker(qids, options, folder):
    """Stream receipt/encoded evidence before publishing the final outcome."""
    folder = Path(folder)
    with (folder / "encoded.body").open("xb", buffering=0) as stream:
        _sync_directory(folder)

        def save_headers(receipt):
            _publish(folder / "receipt.json", json.dumps(receipt).encode("utf-8"))

        capture = collect_http(
            qids, timeout_seconds=options["timeout_seconds"],
            user_agent=options["headers"]["User-Agent"],
            on_headers=save_headers, on_chunk=lambda body: _write_all(stream, body),
        )
    if capture.body is not None:
        _publish(folder / "decoded.body", capture.body)
    metadata = asdict(capture)
    del metadata["encoded"]
    del metadata["body"]
    _publish(folder / "result.json", json.dumps(metadata).encode("utf-8"))


def capture_batch(qids, *, timeout_seconds=60, user_agent=DEFAULT_USER_AGENT, worker=None,
                  capture_directory=None):
    """Supervise one request with an absolute deadline and no retry.

    Returns partial encoded evidence and received headers on deadline or
    KeyboardInterrupt. Never promote a killed/unfinished worker to success.
    """
    options = request_options(qids, timeout_seconds=timeout_seconds, user_agent=user_agent)
    started_at = _now()
    deadline = time.monotonic() + timeout_seconds
    forced_error = None
    interrupted = False
    with ExitStack() as stack:
        if capture_directory is None:
            directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="idea-json-mvp-"))
        else:
            directory = Path(capture_directory)
            directory.mkdir()  # caller-owned spool is exclusive and never removed
            _sync_directory(directory.parent)
        folder = Path(directory)
        process = multiprocessing.get_context("spawn").Process(
            target=worker or network_worker, args=(list(qids), options, directory),
        )
        try:
            process.start()
            process.join(max(0, deadline - time.monotonic()))
            if time.monotonic() >= deadline or process.is_alive():
                forced_error = "total response deadline exceeded"
        except KeyboardInterrupt:
            interrupted = True
            forced_error = "interrupted during response capture"
        except Exception as exc:
            forced_error = f"{type(exc).__name__}: {exc}"
        finally:
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join()
        metadata = {
            "status": None, "headers": {}, "complete": False,
            "error": "response worker exited without outcome", "started_at": started_at,
            "headers_received_at": None, "received_at": None, "interrupted": interrupted,
        }
        for filename in ("receipt.json", "result.json"):
            path = folder / filename
            if path.exists():
                try:
                    metadata.update(json.loads(path.read_text(encoding="utf-8")))
                except (ValueError, UnicodeError):
                    forced_error = forced_error or "incomplete response worker outcome"
        encoded_path = folder / "encoded.body"
        encoded = encoded_path.read_bytes() if encoded_path.exists() else b""
        decoded_path = folder / "decoded.body"
        body = decoded_path.read_bytes() if decoded_path.exists() else None
        if metadata["complete"] and body is None:
            forced_error = forced_error or "response worker outcome has no decoded body"
        if forced_error:
            metadata.update(error=forced_error, complete=False, received_at=None)
            body = None
        metadata["interrupted"] = interrupted
        return Capture(encoded=encoded, body=body, **metadata)
