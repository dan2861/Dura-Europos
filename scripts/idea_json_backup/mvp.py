from pathlib import Path
from datetime import datetime
import re

from scripts.sample_backup.jsoncodec import Number, dumps, loads


def preserve_batch(response_body, requested_qids, output_dir):
    if (not isinstance(requested_qids, (list, tuple)) or not 1 <= len(requested_qids) <= 50
            or any(not isinstance(qid, str) or not re.fullmatch(r"Q[1-9][0-9]*", qid)
                   for qid in requested_qids)
            or len(set(requested_qids)) != len(requested_qids)):
        raise ValueError("Expected 1–50 distinct canonical QIDs")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True)

    (output_dir / "source.json").write_bytes(response_body)

    response = loads(response_body)
    items_dir = output_dir / "items"
    items_dir.mkdir()
    if (not isinstance(response, dict) or set(response) != {"success", "entities"}
            or not isinstance(response.get("success"), Number)
            or response["success"].token != "1"
            or not isinstance(response.get("entities"), dict)
            or set(response["entities"]) - set(requested_qids)):
        raise ValueError("Unusable response: expected clean success and requested entity keys")

    for qid in requested_qids:
        if qid not in response["entities"]:
            raise ValueError(f"Requested {qid} is missing from response entities")

        entity = response["entities"][qid]
        if not isinstance(entity, dict):
            raise ValueError(f"Requested {qid} must be an item object")
        returned_qid = entity.get("id")

        if returned_qid != qid:
            raise ValueError(
                f"Requested {qid}, but entity ID is {returned_qid!r}"
            )

        if "missing" in entity:
            raise ValueError(f"Requested {qid} is unavailable: missing_or_redirect")

        if entity.get("type") != "item":
            raise ValueError(f"Requested {qid} must have type=item")

        revision = entity.get("lastrevid")
        if not isinstance(revision, Number) or not re.fullmatch(r"[1-9][0-9]*", revision.token):
            raise ValueError(f"Requested {qid} has invalid revision metadata")
        modified = entity.get("modified")
        try:
            if not isinstance(modified, str) or not re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z", modified):
                raise ValueError("Expected UTC timestamp")
            datetime.fromisoformat(modified.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Requested {qid} has invalid modified metadata") from exc

        (items_dir / f"{qid}.json").write_text(
            dumps(entity),
            encoding="utf-8",
        )
