"""Two sequential graph queries with bounded retries and preserved evidence."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
import time

from .files import describe, write_bytes
from .selection import checkpoint, freeze_selection, new_selection, now, parse_results, query_request
from .transport import DEFAULT_USER_AGENT

TRANSIENT = {429, 500, 502, 503, 504}


def _retry_after(headers, current):
    delay = 0
    malformed = False
    for value in headers.get("retry-after", []):
        try:
            if re.fullmatch(r"[0-9]+", value):
                seconds = int(value)
            else:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    raise ValueError("Retry-After date needs timezone")
                seconds = (date - datetime.fromisoformat(current.replace("Z", "+00:00"))).total_seconds()
            delay = max(delay, seconds)
        except (TypeError, ValueError, OverflowError):
            malformed = True
    return max(0, delay), malformed


def _body(root, graph, number, role, value, complete):
    if not value:
        return None  # a clean empty receipt is represented by receipt_complete, not an invented file
    relative = f"sources/{graph}-{number}.{role}"
    write_bytes(root / relative, value)
    return dict(describe(relative, value), complete=complete)


def discover(output_dir, *, kind="production", user_agent=DEFAULT_USER_AGENT,
             fetcher=None, sleep=time.sleep, monotonic=time.monotonic, utcnow=now):
    """Network only when explicitly invoked; tests supply invented captures/clocks."""
    if fetcher is None:
        from .client import fetch
        fetcher = fetch
    # Validate requests before creating a directory or making any request.
    from .client import request_url
    for graph in ("main", "scholarly"):
        request_url(query_request(graph, user_agent))
    root = Path(output_dir)
    metadata = new_selection(root, kind=kind)
    not_before = monotonic()
    for source in metadata["sources"]:
        for number in range(1, 4):
            remaining = not_before - monotonic()
            if remaining > 0:
                sleep(remaining)
            started = utcnow()
            source["started_at"] = source["started_at"] or started
            request = query_request(source["graph"], user_agent)
            attempt = {"attempt_id": f"{source['graph']}-{number}", "request": request,
                       "started_at": started, "headers_received_at": None, "headers_observed": None,
                       "response_received_at": None, "response_elapsed_ms": None, "receipt_complete": None,
                       "finished_at": None, "status_code": None, "headers": {}, "encoded": None,
                       "decoded": None, "next_dispatch_at": None, "outcome": "pending", "error": None}
            source["attempts"].append(attempt)
            checkpoint(root, metadata)
            try:
                result = fetcher(request, root / ".state" / attempt["attempt_id"], timeout_seconds=60)
                for key in ("started_at", "headers_received_at", "headers_observed", "response_received_at",
                            "response_elapsed_ms", "receipt_complete", "status_code", "headers"):
                    attempt[key] = getattr(result, key)
                attempt["encoded"] = _body(root, source["graph"], number, "encoded", result.encoded,
                                           result.receipt_complete)
                attempt["decoded"] = _body(root, source["graph"], number, "decoded", result.decoded,
                                           result.decoded is not None and result.receipt_complete is True)
                retryable = (result.status_code in TRANSIENT or
                             (result.stage == "transport" and result.error is not None
                              and result.receipt_complete is not True))
                if result.stage == "saving" or result.headers_observed is None or result.interrupted:
                    retryable = False
                problem = result.error
                code = "capture_failed"
                stage = result.stage
                if (result.status_code != 200 or result.receipt_complete is not True
                        or result.decoded is None or result.headers_observed is not True):
                    problem = problem or "Incomplete or unsuccessful discovery receipt"
                if problem is None:
                    try:
                        parse_results(result.decoded)
                    except ValueError as exc:
                        problem, code, stage, retryable = str(exc), "invalid_results", "selection", False
                server_wait, malformed = _retry_after(result.headers, utcnow())
                if malformed:
                    if problem is None:
                        problem, retryable = "Malformed Retry-After requires review", False
                    else:
                        problem += "; malformed Retry-After retained, ordinary backoff applies"
                    code = "invalid_retry_after"
                if result.headers_observed is None:
                    problem, code = problem or "Receipt headers lost after possible dispatch", "server_wait_unknown"
                wait = max(1, server_wait, (5 if number == 1 else 10) if retryable else 0)
                not_before = monotonic() + wait
                attempt["next_dispatch_at"] = (datetime.fromisoformat(utcnow().replace("Z", "+00:00"))
                                                + timedelta(seconds=wait)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                attempt["finished_at"] = utcnow()
                if problem is None:
                    attempt["outcome"] = "succeeded"
                    source.update(outcome="succeeded", finished_at=utcnow())
                    checkpoint(root, metadata)
                    break
                attempt.update(outcome="transient_failure" if retryable else "review_required",
                               error={"stage": stage, "code": code, "message": problem, "retryable": retryable})
                if retryable and number < 3:
                    checkpoint(root, metadata)
                    continue
                source.update(outcome="failed", finished_at=utcnow())
                checkpoint(root, metadata)
                raise ValueError(problem)
            except BaseException as exc:
                if source["outcome"] != "failed":
                    attempt.update(outcome="interrupted" if isinstance(exc, KeyboardInterrupt) else "saving_failure",
                                   finished_at=utcnow(), error={"stage": "saving" if isinstance(exc, OSError) else "transport",
                                   "code": "interrupted" if isinstance(exc, KeyboardInterrupt) else "discovery_aborted",
                                   "message": f"{type(exc).__name__}: {exc}", "retryable": False})
                    source.update(outcome="failed", finished_at=utcnow())
                    checkpoint(root, metadata)
                raise
    return freeze_selection(root, metadata, utcnow=utcnow)
