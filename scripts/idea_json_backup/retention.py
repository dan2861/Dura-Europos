"""Historical operator evidence, distinct from verification of a new deposit.

Only the embedded record's schema and internal claims are checked here. No
historical transfer is re-observed and no maximum repository size is inferred.
"""
from datetime import datetime
import re

from .acquisition import _receipt, _stamp

REPORT_KEYS = {"format_version", "package_id", "checked_at", "acquisition",
               "byte_status", "deposit_status", "findings", "publication"}
INCOMPLETE = {"code": "acquisition_incomplete", "qid": None, "path": None,
              "message": "Operator-recorded acquisition is incomplete; deposit remains unverified"}


def validate_retention_evidence(value):
    """Accept legacy null or a consistent byte-passed historical report.

    Source identity must be known. Unknown download times remain explicit;
    they cannot confer deposit verification, even when byte checks passed.
    """
    if value is None:
        return
    try:
        if (not isinstance(value, dict) or set(value) != REPORT_KEYS
                or value["format_version"] != "1.0.0" or value["byte_status"] != "passed"
                or value["publication"] is not None or not _stamp(value["checked_at"])):
            raise ValueError
        identifier = value["package_id"]
        match = re.fullmatch(r"([0-9]{8}T[0-9]{6}\.[0-9]{6})Z-[A-Za-z0-9-]+", identifier) if isinstance(identifier, str) else None
        if match is None:
            raise ValueError
        datetime.strptime(match.group(1), "%Y%m%dT%H%M%S.%f")
        receipt = value["acquisition"]
        if not isinstance(receipt, dict):
            raise ValueError
        rows = receipt.get("files")
        if not isinstance(rows, list) or len(rows) < 2:
            raise ValueError
        expected = {"package-inventory.json"} | {f"part-{index:05d}.tar.gz" for index in range(1, len(rows))}
        complete = _receipt(receipt, expected)
        if (any(receipt[key] is None for key in ("dataset_url", "persistent_id", "dataset_version", "recorded_by"))
                or any(row[key] is None for row in rows for key in ("remote_file_id", "download_url", "local_path"))
                or {row["local_path"] for row in rows} != expected):
            raise ValueError
        if (value["deposit_status"] != ("passed" if complete else "not_checked")
                or value["findings"] != ([] if complete else [INCOMPLETE])):
            raise ValueError
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
        raise ValueError("Invalid historical archive-retention evidence") from None
