"""Preserve one supplied batch as a documented, independently verifiable prototype."""
from .contract import entities_from_response, require_entity, validate_provenance, validate_qids
from .files import Run


def _extract(run, body, *, source_saved=False):
    current = None
    try:
        if not source_saved:
            run.source(body)
        entities = entities_from_response(body, run.manifest["requested_qids"])
        for current in run.manifest["items"]:
            run.accept(current, require_entity(entities, current["qid"]))
        return run.finish()
    except BaseException as exc:
        run.fail(exc, current)
        raise


def preserve_batch(response_body, requested_qids, output_dir, *, provenance=None):
    qids = validate_qids(requested_qids)
    provenance = validate_provenance(provenance)
    if not isinstance(response_body, bytes):
        raise ValueError("Response body must be bytes")
    return _extract(Run(output_dir, qids, provenance), response_body)
