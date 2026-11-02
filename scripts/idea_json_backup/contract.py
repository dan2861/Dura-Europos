"""Validation for a single MVP batch, without storage or network access."""
import re
from datetime import datetime

from scripts.sample_backup.jsoncodec import Number, loads


def validate_qids(qids):
    if (not isinstance(qids, (list, tuple)) or not 1 <= len(qids) <= 50
            or any(not isinstance(q, str) or not re.fullmatch(r"Q[1-9][0-9]*", q) for q in qids)
            or len(set(qids)) != len(qids)):
        raise ValueError("Expected 1–50 distinct canonical QIDs")
    return list(qids)


def valid_utc(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z", value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_provenance(value):
    if value is None:
        value = {"kind": "saved", "description": "Caller-supplied offline bytes; origin unspecified",
                 "retrieved_at": None}
    if (not isinstance(value, dict) or set(value) != {"kind", "description", "retrieved_at"}
            or value["kind"] not in ("synthetic", "saved", "live")
            or not isinstance(value["description"], str) or not value["description"].strip()
            or (not valid_utc(value["retrieved_at"]) if value["kind"] == "live"
                else value["retrieved_at"] is not None)):
        raise ValueError("Invalid provenance or invented retrieval time")
    return dict(value)


def entities_from_response(body, qids):
    response = loads(body)
    if (not isinstance(response, dict) or set(response) != {"success", "entities"}
            or not isinstance(response.get("success"), Number) or response["success"].token != "1"
            or not isinstance(response.get("entities"), dict)
            or set(response["entities"]) - set(qids)):
        raise ValueError("Unusable response: expected clean success and requested entity keys")
    return response["entities"]


def require_entity(entities, qid):
    if qid not in entities:
        raise ValueError(f"Requested {qid} is missing from response entities")
    entity = entities[qid]
    if not isinstance(entity, dict):
        raise ValueError(f"Requested {qid} must be an item object")
    if entity.get("id") != qid:
        raise ValueError(f"Requested {qid}, but entity ID is {entity.get('id')!r}")
    if "missing" in entity:
        raise ValueError(f"Requested {qid} is unavailable: missing_or_redirect")
    if any(key in entity for key in ("redirect", "redirects", "error")):
        raise ValueError(f"Requested {qid} has an unresolved redirect/error indication")
    if entity.get("type") != "item":
        raise ValueError(f"Requested {qid} must have type=item")
    revision = entity.get("lastrevid")
    if not isinstance(revision, Number) or not re.fullmatch(r"[1-9][0-9]*", revision.token):
        raise ValueError(f"Requested {qid} has invalid revision metadata")
    if not valid_utc(entity.get("modified")):
        raise ValueError(f"Requested {qid} has invalid modified metadata")
    return entity
