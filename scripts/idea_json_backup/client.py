"""Generic identified GET capture for discovery and production collection."""
import gzip
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
