"""Pure versioned redirect-release records; no file or network operations."""
from datetime import datetime
from functools import wraps
from pathlib import PurePosixPath
import re

from scripts.sample_backup.jsoncodec import Number
from .contract import valid_utc

VERSION = "1.0.0"
REQUEST_FORMAT = "idea-json-backup-redirect-request"
RESOLUTIONS_FORMAT = "idea-json-backup-redirect-resolution"
RELEASE_FORMAT = "idea-json-backup-release"
COMPLETION_BASIS = "usable_items_and_reviewed_redirects"
COUNT_KEYS = {"selected", "usable_items", "redirected", "pending", "unresolved"}
INPUT_PATHS = {"manifest": "collection/manifest.json", "inventory": "collection/inventory.jsonl",
               "attempts": "collection/attempts.jsonl", "qid_list": "collection/selection/qids.txt"}


def integer(value):
    if type(value) is int:
        return value
    if isinstance(value, Number) and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value.token):
        return int(value.token)
    raise ValueError("Expected a JSON integer")


def require(condition):
    if not condition:
        raise ValueError("Invalid redirect-release record")


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected))


def text(value):
    require(isinstance(value, str) and bool(value.strip()))


def stamp(value, *, nullable=False):
    require(nullable and value is None or valid_utc(value))


def identifier(value):
    match = re.fullmatch(r"([0-9]{8}T[0-9]{6}\.[0-9]{6})Z-[A-Za-z0-9-]+", value) if isinstance(value, str) else None
    require(match is not None)
    datetime.strptime(match.group(1), "%Y%m%dT%H%M%S.%f")


def descriptor(value, *, path=None, body=False):
    keys(value, {"path", "size_bytes", "sha256"} | ({"complete"} if body else set()))
    name = value["path"]
    text(name)
    relative = PurePosixPath(name)
    require("\\" not in name and "\x00" not in name and not relative.is_absolute()
            and str(relative) == name and name != "." and ".." not in relative.parts
            and ".state" not in relative.parts and (path is None or name == path))
    require(integer(value["size_bytes"]) >= 0)
    require(isinstance(value["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["sha256"]))
    if body:
        require(value["complete"] is True)


def guarded(function):
    @wraps(function)
    def validate(value):
        try:
            function(value)
        except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
            raise ValueError("Invalid redirect-release record") from None
    return validate


def mappings(rows):
    require(isinstance(rows, list) and bool(rows))
    origins, targets = [], []
    for row in rows:
        for field in ("requested_qid", "target_qid"):
            require(isinstance(row[field], str) and re.fullmatch(r"Q[1-9][0-9]*", row[field]))
        require(row["requested_qid"] != row["target_qid"])
        require(isinstance(row["unavailable_attempt_id"], str)
                and re.fullmatch(r"A0*[1-9][0-9]*", row["unavailable_attempt_id"]))
        origins.append(row["requested_qid"])
        targets.append(row["target_qid"])
    require(len(set(origins)) == len(origins) and not set(origins).intersection(targets))


def evidence(row, value, *, recorded):
    keys(value, {"page_url", "observed_at"} | ({"evidence_kind", "recorded_at", "recorded_by"} if recorded else set()))
    require(value["page_url"] == "https://www.wikidata.org/wiki/" + row["requested_qid"] + "?redirect=no")
    stamp(value["observed_at"], nullable=True)
    if recorded:
        require(value["evidence_kind"] == "operator_recorded")
        stamp(value["recorded_at"])
        text(value["recorded_by"])


@guarded
def validate_request(value):
    keys(value, {"format", "format_version", "run_id", "state_sequence", "qid_list_sha256", "recorded_by", "redirects"})
    require(value["format"] == REQUEST_FORMAT and value["format_version"] == VERSION)
    identifier(value["run_id"])
    require(integer(value["state_sequence"]) >= 0)
    require(isinstance(value["qid_list_sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["qid_list_sha256"]))
    text(value["recorded_by"])
    for row in value["redirects"]:
        keys(row, {"requested_qid", "target_qid", "unavailable_attempt_id", "page_url", "observed_at"})
        evidence(row, {key: row[key] for key in ("page_url", "observed_at")}, recorded=False)
    mappings(value["redirects"])


@guarded
def validate_resolutions(value):
    keys(value, {"format", "format_version", "run_id", "state_sequence", "inputs", "redirects"})
    require(value["format"] == RESOLUTIONS_FORMAT and value["format_version"] == VERSION)
    identifier(value["run_id"])
    require(integer(value["state_sequence"]) >= 0)
    paths = {"qid_list": "selection/qids.txt", "inventory": "inventory.jsonl", "attempts": "attempts.jsonl"}
    keys(value["inputs"], paths)
    for key, path in paths.items():
        descriptor(value["inputs"][key], path=path)
    for row in value["redirects"]:
        keys(row, {"requested_qid", "target_qid", "unavailable_attempt_id", "source_response", "target_item", "evidence"})
        descriptor(row["source_response"], body=True)
        descriptor(row["target_item"], path="items/" + row["target_qid"] + ".json")
        evidence(row, row["evidence"], recorded=True)
    mappings(value["redirects"])


@guarded
def validate_release(value):
    keys(value, {"format", "format_version", "release_id", "run_id", "run_kind", "created_at", "completion_basis",
                 "inputs", "resolutions", "strict_verification", "readme", "verification_path", "counts", "limitations"})
    require(value["format"] == RELEASE_FORMAT and value["format_version"] == VERSION
            and value["completion_basis"] == COMPLETION_BASIS)
    identifier(value["run_id"])
    identifier(value["release_id"])
    stamp(value["created_at"])
    require(value["run_kind"] in ("production", "pilot", "synthetic"))
    keys(value["inputs"], INPUT_PATHS)
    for key, path in INPUT_PATHS.items():
        descriptor(value["inputs"][key], path=path)
    for field, path in (("resolutions", "redirect-resolutions.json"), ("strict_verification", "strict-verification.json"),
                        ("readme", "README.md")):
        descriptor(value[field], path=path)
    require(value["verification_path"] == "verification.json")
    keys(value["counts"], COUNT_KEYS)
    counts = {key: integer(val) for key, val in value["counts"].items()}
    require(counts["usable_items"] > 0 and counts["redirected"] > 0 and counts["pending"] == counts["unresolved"] == 0
            and counts["selected"] == counts["usable_items"] + counts["redirected"])
    require(isinstance(value["limitations"], list) and bool(value["limitations"]))
    for line in value["limitations"]:
        text(line)
