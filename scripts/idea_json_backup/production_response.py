"""Batch classification and IDEA membership, without networking or acceptance writes."""
import re

from scripts.sample_backup.jsoncodec import Number, loads

from .contract import entities_from_response, require_entity, validate_qids


def error(stage, code, message, retryable=False):
    return {"stage": stage, "code": code, "message": str(message), "retryable": retryable}


def membership(entity):
    claims = entity.get("claims", {})
    if not isinstance(claims, dict):
        raise ValueError("Malformed claims object for membership")
    statements = claims.get("P5008", [])
    if not isinstance(statements, list):
        raise ValueError("Malformed P5008 statement list")
    matches = False
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("rank") not in ("normal", "preferred", "deprecated"):
            raise ValueError("Malformed P5008 statement/rank")
        snak = statement.get("mainsnak")
        if not isinstance(snak, dict) or snak.get("snaktype") not in ("value", "novalue", "somevalue"):
            raise ValueError("Malformed P5008 snak")
        if snak["snaktype"] != "value":
            if "datavalue" in snak:
                raise ValueError("Non-value P5008 snak has a datavalue")
            continue
        data = snak.get("datavalue")
        if (snak.get("datatype", "wikibase-item") != "wikibase-item" or not isinstance(data, dict)
                or data.get("type") != "wikibase-entityid" or not isinstance(data.get("value"), dict)):
            raise ValueError("Malformed P5008 value")
        value = data["value"]
        qid = value.get("id")
        if (not isinstance(qid, str) or not re.fullmatch(r"Q[1-9][0-9]*", qid)
                or value.get("entity-type", "item") != "item"):
            raise ValueError("Malformed P5008 item identifier")
        if "numeric-id" in value:
            number = value["numeric-id"]
            token = number.token if isinstance(number, Number) else str(number) if type(number) is int else ""
            if not re.fullmatch(r"[1-9][0-9]*", token) or int(token) != int(qid[1:]):
                raise ValueError("P5008 numeric identifier disagrees with item ID")
        if qid == "Q114241199" and statement["rank"] in ("normal", "preferred"):
            matches = True
    return "matches" if matches else "changed"


def classify_response(body, qids):
    qids = validate_qids(qids)
    result = {"entities": {}, "memberships": {}, "item_results": [], "api_error": None,
              "warnings": None, "outcome": "review_required", "error": None}
    try:
        envelope = loads(body)
        if isinstance(envelope, dict):
            result["warnings"] = envelope.get("warnings")
            api = envelope.get("error")
            if isinstance(api, dict):
                code, message = api.get("code"), api.get("info", api.get("message"))
                if not isinstance(code, str) or not isinstance(message, str):
                    raise ValueError("Malformed API error object")
                result["api_error"] = {"code": code, "message": message}
                result["error"] = error("api", code, message, code == "maxlag")
            elif "error" in envelope:
                raise ValueError("Malformed API error indication")
            if "warnings" in envelope:
                result["error"] = error("api", "api_warning", "API warning requires review")
        if result["error"] is None:
            result["entities"] = entities_from_response(body, qids)
    except (ValueError, TypeError, RecursionError) as exc:
        result["error"] = error("api", "invalid_response", exc)
    if result["error"] is not None:
        outcome = "transient_failure" if result["error"]["retryable"] else "review_required"
        result.update(outcome=outcome, item_results=[{"qid": qid, "outcome": outcome,
                      "returned_qid": None, "error": result["error"]} for qid in qids])
        return result
    accepted = 0
    for qid in qids:
        entity = result["entities"].get(qid)
        returned = entity.get("id") if isinstance(entity, dict) and isinstance(entity.get("id"), str) else None
        row = {"qid": qid, "outcome": "review_required", "returned_qid": returned, "error": None}
        try:
            entity = require_entity(result["entities"], qid)
            result["memberships"][qid] = membership(entity)
            row["outcome"] = "accepted"
            accepted += 1
        except ValueError as exc:
            code = ("omitted" if qid not in result["entities"] else "missing_or_redirect"
                    if isinstance(entity, dict) and "missing" in entity else "invalid_item")
            row["error"] = error("identity" if code != "invalid_item" else "extraction", code, exc)
        result["item_results"].append(row)
    result["outcome"] = "succeeded" if accepted == len(qids) else "mixed" if accepted else "review_required"
    return result
