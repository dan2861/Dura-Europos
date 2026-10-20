"""Precision-preserving JSON codec."""
import json
import re
from dataclasses import dataclass

NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


@dataclass(frozen=True)
class Number:
    token: str

    def __post_init__(self):
        if not NUMBER.fullmatch(self.token):
            raise ValueError("Not a JSON number")

    def __str__(self):
        return self.token


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _constant(token):
    raise ValueError(f"Non-JSON numeric extension: {token}")


def loads(body):
    try:
        return json.loads(body, parse_int=Number, parse_float=Number,
                          parse_constant=_constant, object_pairs_hook=_pairs)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds supported parser depth") from exc


def _dumps(value, *, sort_keys=False):
    if isinstance(value, Number):
        return value.token
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list) or isinstance(value, tuple):
        return "[" + ",".join(_dumps(v, sort_keys=sort_keys) for v in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("JSON object keys must be strings")
        keys = sorted(value) if sort_keys else value.keys()
        return "{" + ",".join(_dumps(k) + ":" + _dumps(value[k], sort_keys=sort_keys)
                               for k in keys) + "}"
    raise ValueError(f"Unsupported JSON type (no float coercion): {type(value).__name__}")


def dumps(value, *, sort_keys=False):
    try:
        return _dumps(value, sort_keys=sort_keys)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds supported serialization depth") from exc


def equal(left, right):
    return dumps(left, sort_keys=True) == dumps(right, sort_keys=True)
