"""Bounded retrieval, with transport and process boundaries replaceable in offline tests."""
import json
import multiprocessing
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError

from . import jsoncodec as codec
from .schema import ENDPOINT, request_options
from .storage import utc_now


class CaptureError(OSError):
    """The response capture could not be saved completely."""


def write_all(stream, body):
    remaining = memoryview(body)
    try:
        while remaining:
            count = stream.write(remaining)
            if not isinstance(count, int) or count <= 0:
                raise CaptureError("short/failed response capture write")
            remaining = remaining[count:]
    except OSError as exc:
        raise CaptureError(str(exc)) from exc


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPTransport:
    def open(self, url, headers, timeout):
        request = Request(url, headers=headers, method="GET")
        try:
            return build_opener(NoRedirect()).open(request, timeout=timeout)
        except HTTPError as response:
            return response


def collect_http(url, options, transport, on_trace, on_chunk):
    deadline = time.monotonic() + options["timeout_seconds"]
    visited = set()
    redirects = 0
    response = None
    complete = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("total response deadline exceeded")
            if urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("unsupported redirect URL scheme")
            visited.add(url)
            response = transport.open(url, options["headers"], remaining)
            complete = False
            status = response.status
            location = response.headers.get("Location")
            on_trace({"url": url, "status_code": status, "location": location})
            error = None
            if status in (301, 302, 303, 307, 308):
                destination = urljoin(url, location) if isinstance(location, str) else None
                if not location or not destination or not urlsplit(destination).netloc:
                    error = "missing/invalid redirect Location"
                elif destination in visited:
                    error = "redirect loop"
                elif redirects >= options["max_redirects"]:
                    error = "redirect limit exceeded (required sixth step)"
                elif urlsplit(destination).scheme not in ("http", "https"):
                    error = "unsupported redirect URL scheme"
                else:
                    response.close()
                    response = None
                    url = destination
                    redirects += 1
                    continue
            elif not 200 <= status < 300:
                error = f"HTTP status {status}"
            count = 0
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("total response deadline exceeded")
                chunk = response.read(65536)
                if chunk:
                    on_chunk(chunk)
                    count += len(chunk)
                if time.monotonic() >= deadline:
                    raise TimeoutError("total response deadline exceeded")
                if not chunk:
                    break
            length = response.headers.get("Content-Length")
            if length is not None and count != int(length):
                raise IOError("incomplete response body (Content-Length mismatch)")
            complete = True
            return {"error": error, "complete": complete, "retrieved_at": utc_now()}
    except Exception as exc:
        partial = getattr(exc, "partial", b"")
        if isinstance(partial, bytes) and partial:
            on_chunk(partial)
        return {"error": f"{type(exc).__name__}: {exc}", "complete": complete,
                "retrieved_at": None, "stage": "saving" if isinstance(exc, CaptureError) else "retrieval"}
    finally:
        if response is not None:
            response.close()


@dataclass
class Result:
    body: bytes
    trace: list
    complete: bool | None
    error: str | None
    retrieved_at: str | None = None
    entity: dict | None = None
    interrupted: bool = False
    stage: str = "retrieval"


def usable_entity(body):
    envelope = codec.loads(body)
    if not isinstance(envelope, dict) or "error" in envelope:
        raise ValueError("missing/error entity envelope")
    entities = envelope.get("entities")
    if not isinstance(entities, dict) or len(entities) != 1:
        raise ValueError("expected exactly one identifiable entity")
    entity = next(iter(entities.values()))
    if (not isinstance(entity, dict) or "missing" in entity or entity.get("type") != "item"
            or not isinstance(entity.get("id"), str)
            or not re.fullmatch(r"Q[1-9][0-9]*", entity["id"])):
        raise ValueError("missing/deleted/non-item entity")
    return entity


def network_worker(url, options, folder):
    folder = Path(folder)
    with (folder / "body").open("wb", buffering=0) as body, (folder / "trace").open("wb", buffering=0) as trace:
        def record(entry):
            write_all(trace, (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
        outcome = collect_http(url, options, HTTPTransport(), record, lambda chunk: write_all(body, chunk))
    temporary = folder / "result.staging"
    temporary.write_text(json.dumps(outcome), encoding="utf-8")
    os.replace(temporary, folder / "result")


def retrieve(qid, *, timeout_seconds=60, worker=None):
    if not re.fullmatch(r"Q[1-9][0-9]*", qid):
        raise ValueError("Invalid requested QID")
    if timeout_seconds <= 0:
        raise ValueError("Deadline must be positive")
    options = request_options()
    options["timeout_seconds"] = timeout_seconds
    interrupted = False
    forced_error = None
    deadline = time.monotonic() + timeout_seconds
    with tempfile.TemporaryDirectory(prefix="sample-backup-transport-") as directory:
        folder = Path(directory)
        process = multiprocessing.get_context("spawn").Process(
            target=worker or network_worker,
            args=(ENDPOINT.format(qid=qid), options, directory))
        try:
            process.start()
            process.join(max(0, deadline - time.monotonic()))
            if process.is_alive():
                forced_error = "total response deadline exceeded"
        except KeyboardInterrupt:
            interrupted = True
            forced_error = "interrupted during retrieval"
        finally:
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join()
        body = (folder / "body").read_bytes() if (folder / "body").exists() else b""
        trace = []
        if (folder / "trace").exists():
            for line in (folder / "trace").read_text(encoding="utf-8").splitlines():
                try:
                    trace.append(json.loads(line))
                except ValueError:
                    forced_error = forced_error or "incomplete HTTP trace record"
        outcome = {"error": forced_error or "retrieval worker exited without outcome",
                   "complete": False if trace else None, "retrieved_at": None}
        if (folder / "result").exists():
            outcome = json.loads((folder / "result").read_text(encoding="utf-8"))
        result = Result(body=body, trace=trace, complete=outcome["complete"],
                        error=forced_error or outcome["error"],
                        retrieved_at=outcome["retrieved_at"], interrupted=interrupted,
                        stage=outcome.get("stage", "retrieval"))
        if result.error is None and result.complete:
            try:
                result.entity = usable_entity(body)
            except (ValueError, UnicodeError) as exc:
                result.error = f"unusable entity JSON: {exc}"
        return result
