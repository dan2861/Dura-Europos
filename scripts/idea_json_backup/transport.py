"""One identified HTTP batch; capture evidence without retries or redirects."""
import gzip
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
    try:
        response = (transport or HTTPTransport()).open(options["url"], options["headers"], timeout_seconds)
        status = response.status
        headers = {key.lower(): str(value) for key, value in response.headers.items() if key.lower() in HEADER_NAMES}
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
        length = headers.get("content-length")
        if length is not None and (not re.fullmatch(r"[0-9]+", length) or len(encoded) != int(length)):
            raise OSError("incomplete response: Content-Length mismatch")
        received_at = _now()
        encoding = headers.get("content-encoding", "identity").strip().lower()
        if encoding == "identity":
            body = encoded
        elif encoding == "gzip":
            body = gzip.decompress(encoded)
        else:
            raise ValueError(f"unsupported content encoding: {encoding}")
        return Capture(encoded, body, status, headers, True,
                       None if status == 200 else f"HTTP status {status}",
                       started_at, headers_received_at, received_at)
    except Exception as exc:
        partial = getattr(exc, "partial", b"")
        if isinstance(partial, bytes) and partial:
            chunks.append(partial)
            if on_chunk:
                on_chunk(partial)
        return Capture(b"".join(chunks), None, status, headers, False,
                       f"{type(exc).__name__}: {exc}", started_at, headers_received_at, received_at)
    finally:
        if response is not None:
            response.close()
