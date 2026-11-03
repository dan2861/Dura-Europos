"""Generic identified GET capture for discovery and production collection."""
import gzip
import json
import math
import multiprocessing
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .files import write_bytes


ENDPOINTS = {
    "https://query.wikidata.org/sparql",
    "https://query-scholarly.wikidata.org/sparql",
    "https://www.wikidata.org/w/api.php",
}
HEADER_NAMES = {"content-type", "content-encoding", "content-length", "retry-after",
                "date", "etag", "last-modified", "location", "x-database-lag"}


@dataclass
class FetchResult:
    encoded: bytes
    decoded: bytes | None
    status_code: int | None
    headers: dict[str, list[str]]
    started_at: str
    headers_received_at: str | None
    headers_observed: bool | None
    response_received_at: str | None
    response_elapsed_ms: int | None
    receipt_complete: bool | None
    error: str | None
    stage: str = "transport"
    interrupted: bool = False


class CaptureWriteError(OSError):
    """A received byte/header could not be durably recorded."""


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _deadline(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 60:
        raise ValueError("Response deadline must be positive and at most 60 seconds")


def request_url(request):
    if (not isinstance(request, dict) or set(request) != {"method", "url", "parameters", "headers"}
            or request["method"] != "GET" or request["url"] not in ENDPOINTS
            or not isinstance(request["parameters"], dict)
            or any(not isinstance(k, str) or not isinstance(v, str)
                   for k, v in request["parameters"].items())
            or not isinstance(request["headers"], dict)
            or any(not isinstance(k, str) or not isinstance(v, str) or "\r" in v or "\n" in v
                   for k, v in request["headers"].items())):
        raise ValueError("Invalid or unsupported GET request")
    headers = {key.lower(): value for key, value in request["headers"].items()}
    expected = "application/json" if request["url"].endswith("api.php") else "application/sparql-results+json"
    if (len(headers) != len(request["headers"])
            or set(headers) != {"accept", "accept-encoding", "user-agent"}
            or headers["accept"] != expected or headers["accept-encoding"] != "gzip, identity"
            or not headers["user-agent"].strip()):
        raise ValueError("Expected identifying User-Agent and explicit JSON/encoding headers")
    return request["url"] + ("?" + urlencode(request["parameters"]) if request["parameters"] else "")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPTransport:
    def open(self, url, headers, timeout):
        try:
            return build_opener(NoRedirect()).open(Request(url, headers=headers, method="GET"), timeout=timeout)
        except HTTPError as response:
            return response


def _record(callback, value):
    if callback is not None:
        try:
            callback(value)
        except Exception as exc:
            raise CaptureWriteError(str(exc)) from exc


def collect_http(request, *, transport=None, timeout_seconds=60, on_headers=None, on_chunk=None):
    """Capture exactly one response; the supervisor supplies the hard deadline.

    Receipt completeness describes encoded EOF/framing, separately from decode
    success. A clean empty receipt therefore stays complete with zero bytes.
    """
    url = request_url(request)
    _deadline(timeout_seconds)
    start = time.monotonic()
    deadline = start + timeout_seconds
    metadata = dict(status_code=None, headers={}, started_at=utc_now(), headers_received_at=None,
                    headers_observed=False, response_received_at=None, response_elapsed_ms=None,
                    receipt_complete=None, error=None)
    response = None
    chunks = []
    stage = "transport"
    result = None
    try:
        response = (transport or HTTPTransport()).open(url, request["headers"], timeout_seconds)
        metadata.update(status_code=response.status, headers_received_at=utc_now(),
                        headers_observed=True, receipt_complete=False)
        for key, value in response.headers.items():
            name = key.lower()
            if name in HEADER_NAMES:
                metadata["headers"].setdefault(name, []).append(str(value))
        _record(on_headers, dict(metadata))
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("total response deadline exceeded")
            chunk = response.read(65536)
            if chunk:
                chunks.append(chunk)
                _record(on_chunk, chunk)
            if time.monotonic() >= deadline:
                raise TimeoutError("total response deadline exceeded")
            if not chunk:
                break
        encoded = b"".join(chunks)
        lengths = metadata["headers"].get("content-length", [])
        if (len(lengths) > 1 or (lengths and (not re.fullmatch(r"[0-9]+", lengths[0])
                                             or int(lengths[0]) != len(encoded)))):
            raise OSError("Incomplete/ambiguous Content-Length framing")
        metadata.update(receipt_complete=True, response_received_at=utc_now(),
                        response_elapsed_ms=max(0, int((time.monotonic() - start) * 1000)))
        stage = "decoding"
        encodings = metadata["headers"].get("content-encoding", ["identity"])
        if len(encodings) != 1:
            raise ValueError("Ambiguous content encoding")
        encoding = encodings[0].strip().lower()
        if encoding == "identity":
            decoded = encoded
        elif encoding == "gzip":
            decoded = gzip.decompress(encoded)
        else:
            raise ValueError(f"Unsupported content encoding: {encoding}")
        if metadata["status_code"] != 200:
            metadata["error"] = f"HTTP status {metadata['status_code']}"
        result = FetchResult(encoded=encoded, decoded=decoded, **metadata)
    except Exception as exc:
        partial = getattr(exc, "partial", b"")
        if isinstance(partial, bytes) and partial:
            chunks.append(partial)
            try:
                _record(on_chunk, partial)
            except CaptureWriteError as saving:
                exc = saving
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        result = FetchResult(encoded=b"".join(chunks), decoded=None, **metadata,
                             stage="saving" if isinstance(exc, CaptureWriteError) else stage)
    finally:
        if response is not None:
            try:
                response.close()
            except Exception as exc:
                if result is not None:
                    result.error = result.error or f"{type(exc).__name__}: {exc}"
    return result


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_all(stream, body):
    """Write every received byte and synchronize before acknowledging capture."""
    remaining = memoryview(body)
    while remaining:
        count = stream.write(remaining)
        if type(count) is not int or count <= 0 or count > len(remaining):
            raise CaptureWriteError("Incomplete response capture write")
        remaining = remaining[count:]
    stream.flush()
    os.fsync(stream.fileno())


def _publish(path, value):
    write_bytes(path, json.dumps(value).encode("utf-8"))


def network_worker(request, timeout_seconds, directory):
    """Persist headers before reading; body files exist only for received bytes."""
    folder = Path(directory)
    stream = None

    def save_chunk(body):
        nonlocal stream
        if stream is None:
            stream = (folder / "encoded.body").open("xb", buffering=0)
            _sync_directory(folder)
        write_all(stream, body)

    try:
        result = collect_http(request, timeout_seconds=timeout_seconds,
                              on_headers=lambda value: _publish(folder / "receipt.json", value),
                              on_chunk=save_chunk)
    finally:
        if stream is not None:
            stream.close()
    if result.decoded:
        try:
            write_bytes(folder / "decoded.body", result.decoded)
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.stage = "saving"
            result.decoded = None
    metadata = asdict(result)
    metadata["encoded_size"] = len(metadata.pop("encoded"))
    decoded = metadata.pop("decoded")
    metadata["decoded_size"] = None if decoded is None else len(decoded)
    _publish(folder / "result.json", metadata)


def fetch(request, capture_directory, *, timeout_seconds=60, worker=None):
    """Supervise one GET; retain the exclusive caller-owned spool on every path.

    A missing outcome after possible dispatch has unknown header observation.
    A durable pre-header failure is distinct and can be classified by its caller.
    No retry, sleep/backoff or item acceptance is performed here.
    """
    request_url(request)
    _deadline(timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    started_at = utc_now()
    folder = Path(capture_directory)
    folder.mkdir()
    _sync_directory(folder.parent)
    _publish(folder / "dispatch.json", {"request": request, "started_at": started_at,
                                      "timeout_seconds": timeout_seconds})
    process = multiprocessing.get_context("spawn").Process(
        target=worker or network_worker, args=(request, timeout_seconds, str(folder)))
    forced_error = None
    interrupted = False
    start_failed = False
    try:
        process.start()
        process.join(max(0, deadline - time.monotonic()))
        if time.monotonic() >= deadline or process.is_alive():
            forced_error = "total response deadline exceeded"
        elif getattr(process, "exitcode", None) not in (None, 0):
            forced_error = "response worker exited unsuccessfully"
    except KeyboardInterrupt:
        interrupted = True
        forced_error = "interrupted during response capture"
    except Exception as exc:
        forced_error = f"{type(exc).__name__}: {exc}"
        start_failed = process.pid is None
    finally:
        if process.pid is not None and process.is_alive():
            process.terminate()
            process.join(1)
            if process.is_alive():
                process.kill()
                process.join()
    metadata = dict(status_code=None, headers={}, started_at=started_at, headers_received_at=None,
                    headers_observed=False if start_failed else None, response_received_at=None,
                    response_elapsed_ms=None, receipt_complete=None,
                    error="response worker exited without durable outcome", stage="saving", interrupted=interrupted)
    encoded_size, decoded_size = None, None
    outcome = False
    for filename in ("receipt.json", "result.json"):
        path = folder / filename
        if not path.exists():
            continue
        try:
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict):
                raise ValueError("worker metadata must be an object")
            metadata.update({key: value[key] for key in metadata if key in value})
            if filename == "result.json":
                encoded_size, decoded_size = value["encoded_size"], value["decoded_size"]
                if (type(encoded_size) is not int or encoded_size < 0
                        or (decoded_size is not None and (type(decoded_size) is not int or decoded_size < 0))):
                    raise ValueError("invalid worker body sizes")
                outcome = True
        except (OSError, ValueError, KeyError) as exc:
            forced_error = forced_error or f"Invalid durable capture metadata: {exc}"
            metadata["stage"] = "saving"
    encoded_path = folder / "encoded.body"
    encoded = encoded_path.read_bytes() if encoded_path.exists() else b""
    decoded_path = folder / "decoded.body"
    decoded = decoded_path.read_bytes() if decoded_path.exists() else None
    if outcome and len(encoded) != encoded_size:
        forced_error = forced_error or "encoded capture size disagrees with durable outcome"
        metadata["stage"] = "saving"
    if outcome and decoded_size == 0 and decoded is None:
        decoded = b""
    elif outcome and decoded_size is not None and (decoded is None or len(decoded) != decoded_size):
        forced_error = forced_error or "decoded capture size disagrees with durable outcome"
        metadata["stage"] = "saving"
    if not outcome:
        metadata.update(error="response worker exited without durable outcome", stage="saving")
    if forced_error:
        metadata.update(error=forced_error, receipt_complete=False if metadata["headers_observed"] else None,
                        response_received_at=None, response_elapsed_ms=None)
        decoded = None
        if start_failed or "deadline" in forced_error or interrupted:
            metadata["stage"] = "transport"
    metadata["interrupted"] = interrupted
    return FetchResult(encoded=encoded, decoded=decoded, **metadata)
