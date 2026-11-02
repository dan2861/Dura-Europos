"""One request and one new run; no discovery, retry, resume or deposit."""
from dataclasses import asdict
import json

from .contract import valid_utc, validate_qids
from .files import Run, describe
from .mvp import _extract
from .transport import DEFAULT_USER_AGENT, capture_batch, request_options


def _capture_inventory(run):
    folder = run.root / "capture"
    if folder.is_dir():
        names = {entry["path"] for entry in run.manifest["evidence"]}
        for path in sorted(folder.iterdir()):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(run.root).as_posix()
                if relative not in names:
                    run.manifest["evidence"].append(describe(relative, path.read_bytes()))


def collect_batch(qids, output_dir, *, timeout_seconds=60, user_agent=DEFAULT_USER_AGENT,
                  capture=None, provenance_kind="live", description="One identified Action API batch"):
    """Call only for an explicitly authorized pilot; tests inject invented captures."""
    qids = validate_qids(qids)
    options = request_options(qids, timeout_seconds=timeout_seconds, user_agent=user_agent)
    if (provenance_kind not in ("synthetic", "live") or not isinstance(description, str)
            or not description.strip()):
        raise ValueError("Invalid capture provenance")
    run = Run(output_dir, qids, {"kind": provenance_kind, "description": description,
                                "retrieved_at": None})
    try:
        request = dict(options, method="GET")
        run.manifest["evidence"].append(run.artifact("request.json", json.dumps(request).encode()))
        run.checkpoint()
        result = (capture or capture_batch)(
            qids, timeout_seconds=timeout_seconds, user_agent=user_agent,
            capture_directory=run.root / "capture")
        _capture_inventory(run)
        run.manifest["evidence"].append(run.artifact("encoded.body", result.encoded))
        receipt = asdict(result)
        del receipt["encoded"]
        del receipt["body"]
        receipt["encoded_path"] = "encoded.body"
        run.manifest["evidence"].append(run.artifact("transport.json", json.dumps(receipt).encode()))
        if result.body is not None:
            run.source(result.body)
        else:
            run.checkpoint()
        if (result.status != 200 or not result.complete or result.error
                or result.interrupted or result.body is None or not valid_utc(result.received_at)):
            raise ValueError(result.error or "Incomplete or unsuccessful response capture")
        if provenance_kind == "live":
            run.manifest["provenance"]["retrieved_at"] = result.received_at
            run.checkpoint()
    except BaseException as exc:
        _capture_inventory(run)
        run.fail(exc)
        raise
    return _extract(run, result.body, source_saved=True)
