"""Sequential production collection and local recovery from the durable journal."""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import time

from scripts.sample_backup import jsoncodec as codec

from .client import fetch, HEADER_NAMES
from .discovery import TRANSIENT, _retry_after
from .files import describe, _sync
from .production_response import classify_response, error
from .state import RunState, utc_now
from .transport import DEFAULT_USER_AGENT


def _date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _after(stamp, seconds):
    return (_date(stamp) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _request(qids, settings):
    return {"method": "GET", "url": settings["endpoint"], "headers": settings["headers"],
            "parameters": dict(settings["action_parameters"], ids="|".join(qids))}


def _retain_wait(store, until):
    previous = store.manifest["next_dispatch_at"]
    if previous is None or until > previous:
        store.set_run(next_dispatch_at=until)


def _receipt_wait(headers, received, current):
    deadlines = []
    for value in headers.get("retry-after", []):
        try:
            if value.isascii() and value.isdigit():
                deadlines.append(_after(received, int(value)))
            else:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    raise ValueError("Retry-After date lacks timezone")
                deadlines.append(parsed.astimezone(_date(current).tzinfo).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        except (ValueError, TypeError, OverflowError):
            continue
    return max(deadlines) if deadlines else None


def _publish_body(store, attempt_id, role, body, complete):
    if not body:
        return None
    return store.publish(f"responses/{attempt_id}.{role}", body, complete=complete)


def _diagnostic(store, attempt, relative, body, explanation):
    if any(row["file"]["path"] == relative for row in attempt["diagnostics"]):
        return
    path = store.path(relative)
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError("Recovered diagnostic path contains different evidence")
        descriptor = dict(describe(relative, body), complete=None)
    else:
        descriptor = store.publish(relative, body, complete=None)
    attempt["diagnostics"].append({"role": "recovered", "file": descriptor, "explanation": explanation})


def _recover_payload_intents(store):
    for key, intent in store.internal_items("payload:").items():
        attempt_id = intent.get("attempt_id")
        if not isinstance(attempt_id, str):
            raise ValueError("Unowned interrupted publication requires review")
        attempt = store.get_attempt(attempt_id)
        relative = intent["staging_path"]
        if not relative.startswith(".state/staging/" ) or ".." in Path(relative).parts:
            raise ValueError("Unsafe interrupted staging intent")
        stage = store.root / relative
        if stage.is_symlink():
            raise ValueError("Linked interrupted staging evidence")
        if stage.exists():
            _diagnostic(store, attempt, f"diagnostics/{attempt_id}-{key.split(':', 1)[1]}.pending",
                        stage.read_bytes(), "Interrupted owned publication; bytes retained without promoting completeness")
            store.record_attempt(attempt_id, attempt)
            stage.unlink()  # owned staging link only, after durable diagnostic publication
            _sync(stage.parent)
        store.set_internal(key, None)


def _recover_reserved(store, attempt):
    attempt_id = attempt["attempt_id"]
    folder = store.root / ".state" / attempt_id
    known = attempt["dispatch_started_at"] is None
    receipt = None
    for name in ("receipt.json", "result.json"):
        path = folder / name
        if path.exists() and not path.is_symlink():
            try:
                candidate = json.loads(path.read_bytes())
                headers = candidate.get("headers")
                observed = candidate.get("headers_observed")
                if (type(observed) is bool and isinstance(headers, dict) and set(headers) <= HEADER_NAMES
                        and all(isinstance(values, list) and all(isinstance(v, str) for v in values)
                                for values in headers.values())):
                    if observed is False or (type(candidate.get("status_code")) is int
                                             and isinstance(candidate.get("headers_received_at"), str)):
                        receipt = candidate
                        known = True
            except (ValueError, TypeError):
                pass
    if receipt:
        attempt.update(headers_observed=receipt["headers_observed"],
                       headers_received_at=receipt.get("headers_received_at"),
                       http={"status_code": receipt["status_code"], "headers": receipt["headers"]}
                       if receipt.get("status_code") is not None else None)
    elif attempt["dispatch_started_at"] is None:
        attempt["headers_observed"] = False
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            _diagnostic(store, attempt, f"diagnostics/{attempt_id}-{path.name}", path.read_bytes(),
                        "Recovered worker evidence; no complete source was committed")
    for role in ("encoded", "decoded"):
        path = store.root / f"responses/{attempt_id}.{role}"
        if path.exists():
            _diagnostic(store, attempt, path.relative_to(store.root).as_posix(), path.read_bytes(),
                        "Published response without a committed complete-source record")
    headers = attempt["http"]["headers"] if attempt["http"] else {}
    server, malformed = _retry_after(headers, store.now())
    wait = max(5 if max(len(store.get_item(q)["attempt_ids"]) for q in attempt["requested_qids"]) == 1 else 10, server)
    code = "interrupted_capture" if known else "server_wait_unknown"
    status = attempt["http"]["status_code"] if attempt["http"] else None
    retryable = known and (status is None or status == 200 or status in TRANSIENT)
    issue = error("recovery", code, "Interrupted attempt retained; " +
                  ("known header wait recovered" if known else "server_wait_unknown: no durable header outcome"), retryable)
    attempt.update(outcome="interrupted", recovered_at=store.now(), receipt_complete=None,
                   response_received_at=None, response_elapsed_ms=None, encoded=None, decoded=None,
                   next_eligible_at=_after(store.now(), wait) if retryable else None, error=issue,
                   item_results=[{"qid": q, "outcome": "transient_failure" if retryable else "review_required",
                                  "returned_qid": None, "error": issue} for q in attempt["requested_qids"]])
    store.record_attempt(attempt_id, attempt)
    for qid in attempt["requested_qids"]:
        if store.get_item(qid)["status"] != "accepted":
            store.unresolve(qid, issue, next_eligible_at=attempt["next_eligible_at"])
    if known:
        _retain_wait(store, _after(store.now(), wait))
    return not known


def _complete_source(store, attempt):
    body = store._read_descriptor(attempt["decoded"])
    result = classify_response(body, attempt["requested_qids"])
    for row in attempt["item_results"]:
        if row["outcome"] == "accepted" and store.get_item(row["qid"])["status"] != "accepted":
            qid = row["qid"]
            store.accept(qid, attempt["attempt_id"], result["entities"][qid], result["memberships"][qid])
        elif row["outcome"] != "accepted" and store.get_item(row["qid"])["status"] != "accepted":
            store.unresolve(row["qid"], row["error"], returned_qid=row["returned_qid"],
                            next_eligible_at=attempt["next_eligible_at"] if row["error"]["retryable"] else None)
    if attempt["finished_at"] is None:
        attempt["finished_at"] = store.now()
        store.record_attempt(attempt["attempt_id"], attempt)


def recover(store):
    _recover_payload_intents(store)
    hold = False
    for attempt in store.attempts():
        if attempt["outcome"] == "reserved":
            hold = _recover_reserved(store, attempt) or hold
        elif attempt["error"] and attempt["error"]["code"] == "server_wait_unknown":
            hold = True
        elif attempt["outcome"] in ("succeeded", "mixed"):
            _complete_source(store, attempt)
        if attempt["finished_at"] or attempt["recovered_at"]:
            _retain_wait(store, _after(attempt["finished_at"] or attempt["recovered_at"], 1))
        if attempt["http"]:
            receipt = attempt["headers_received_at"] or attempt["recovered_at"] or store.now()
            deadline = _receipt_wait(attempt["http"]["headers"], receipt, store.now())
            if deadline:
                _retain_wait(store, deadline)
        if attempt["next_eligible_at"]:
            _retain_wait(store, attempt["next_eligible_at"])
    if hold:
        raise ValueError("server_wait_unknown: review required before any new dispatch")


def _process(store, *, fetcher, sleep, now_fn, max_batches, monotonic):
    if store.manifest["phase"] == "finalized":
        raise ValueError("Finalized run cannot collect or resume")
    completed = 0
    not_before = monotonic()
    try:
        recover(store)
        while True:
            if store.manifest["counts"]["accepted"] == store.manifest["counts"]["selected"]:
                return store.collected() if store.manifest["phase"] != "collected" else store.snapshot()
            if max_batches is not None and completed >= max_batches:
                return store.pause()
            global_wait = store.manifest["next_dispatch_at"]
            duration = max(0, not_before - monotonic())
            if global_wait:
                duration = max(duration, (_date(global_wait) - _date(now_fn())).total_seconds())
            if duration > 0:
                sleep(duration)
            qids = store.eligible(now_fn())
            if not qids:
                future = [row["next_eligible_at"] for row in store.items()
                          if row["status"] != "accepted" and row["next_eligible_at"]
                          and (row["error"] or {}).get("retryable") and len(row["attempt_ids"]) < 3]
                if future and min(future) > now_fn():
                    sleep((_date(min(future)) - _date(now_fn())).total_seconds())
                    continue
                if store.manifest["phase"] == "collected":
                    return store.snapshot()
                return store.collected()
            settings = store.manifest["request_settings"]
            attempt = store.reserve(qids, _request(qids, settings))
            attempt_id = attempt["attempt_id"]
            store.dispatch(attempt_id)
            attempt = store.get_attempt(attempt_id)
            capture = fetcher(attempt["request"], store.root / ".state" / attempt_id, timeout_seconds=60)
            attempt.update(headers_received_at=capture.headers_received_at, headers_observed=capture.headers_observed,
                           response_received_at=capture.response_received_at, response_elapsed_ms=capture.response_elapsed_ms,
                           receipt_complete=capture.receipt_complete,
                           http={"status_code": capture.status_code, "headers": capture.headers}
                           if capture.status_code is not None else None,
                           encoded=_publish_body(store, attempt_id, "encoded", capture.encoded, capture.receipt_complete),
                           decoded=_publish_body(store, attempt_id, "decoded", capture.decoded,
                                                 capture.decoded is not None and capture.receipt_complete is True))
            if (capture.status_code == 200 and capture.receipt_complete is True and capture.decoded is not None
                    and capture.error is None and capture.headers_observed is True and not capture.interrupted):
                classification = classify_response(capture.decoded, qids)
            else:
                retryable = (capture.status_code in TRANSIENT or
                             (capture.stage == "transport" and capture.error is not None and capture.receipt_complete is not True))
                retryable = retryable and capture.stage != "saving" and capture.headers_observed is not None and not capture.interrupted
                issue = error(capture.stage, "server_wait_unknown" if capture.headers_observed is None else "capture_failed",
                              capture.error or "Unusable response receipt", retryable)
                outcome = "saving_failure" if capture.stage == "saving" else "transient_failure" if retryable else "review_required"
                classification = {"outcome": outcome, "api_error": None, "warnings": None, "error": issue,
                                  "item_results": [{"qid": q, "outcome": "transient_failure" if retryable else "review_required",
                                                    "returned_qid": None, "error": issue} for q in qids]}
            attempt.update(**{key: classification[key] for key in ("outcome", "api_error", "warnings", "error", "item_results")})
            server_wait, malformed = _retry_after(capture.headers, now_fn())
            retry = any(row["error"] and row["error"]["retryable"] for row in attempt["item_results"])
            floor = max(5 if len(store.get_item(q)["attempt_ids"]) == 1 else 10 for q in qids) if retry else 1
            delay = max(1, server_wait, floor)
            if attempt["outcome"] in ("succeeded", "mixed"):
                store.record_attempt(attempt_id, attempt)  # complete source proof precedes every item publication
                _complete_source(store, attempt)
            else:
                for row in attempt["item_results"]:
                    store.unresolve(row["qid"], row["error"], returned_qid=row["returned_qid"],
                                    next_eligible_at=None)
                attempt["finished_at"] = now_fn()
                attempt["next_eligible_at"] = _after(attempt["finished_at"], delay) if retry else None
                if retry:
                    for row in attempt["item_results"]:
                        store.unresolve(row["qid"], row["error"], returned_qid=row["returned_qid"],
                                        next_eligible_at=attempt["next_eligible_at"])
                store.record_attempt(attempt_id, attempt)
            finished = store.get_attempt(attempt_id)["finished_at"]
            not_before = monotonic() + delay
            _retain_wait(store, _after(finished, delay))
            if attempt["error"] and attempt["error"]["code"] == "server_wait_unknown":
                raise ValueError("server_wait_unknown: review required before new dispatch")
            if attempt["outcome"] == "saving_failure":
                raise OSError(attempt["error"]["message"])
            if capture.interrupted:
                raise KeyboardInterrupt("Interrupted capture retained")
            completed += 1
    except BaseException:
        store.pause()
        raise


def collect(selection, run_dir, *, fetcher=None, sleep=time.sleep, now_fn=utc_now,
            user_agent=DEFAULT_USER_AGENT, max_batches=None, monotonic=time.monotonic):
    if max_batches is not None and (type(max_batches) is not int or max_batches < 1):
        raise ValueError("max_batches must be a positive integer")
    with RunState.create(selection, run_dir, user_agent=user_agent, now_fn=now_fn) as store:
        return _process(store, fetcher=fetcher or fetch, sleep=sleep, now_fn=now_fn, max_batches=max_batches, monotonic=monotonic)


def resume(run_dir, *, fetcher=None, sleep=time.sleep, now_fn=utc_now, max_batches=None, monotonic=time.monotonic):
    if max_batches is not None and (type(max_batches) is not int or max_batches < 1):
        raise ValueError("max_batches must be a positive integer")
    with RunState.open(run_dir, now_fn=now_fn) as store:
        return _process(store, fetcher=fetcher or fetch, sleep=sleep, now_fn=now_fn, max_batches=max_batches, monotonic=monotonic)
