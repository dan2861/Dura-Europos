"""Invented redirect-release metadata; no file or network operations."""
import copy
import unittest

from scripts.sample_backup.jsoncodec import Number, dumps, loads

STAMP = "2026-11-08T12:00:00.000000Z"
RUN_ID = "20261108T110000.000000Z-invented-run"
RELEASE_ID = "20261108T120000.000000Z-invented-release"


def descriptor(path, **extra):
    return dict(path=path, size_bytes=23, sha256="a" * 64, **extra)


def request():
    return {"format": "idea-json-backup-redirect-request", "format_version": "1.0.0",
            "run_id": RUN_ID, "state_sequence": 12, "qid_list_sha256": "b" * 64,
            "recorded_by": "Invented Danu's review~01",
            "redirects": [{"requested_qid": "Q2", "target_qid": "Q1",
                           "unavailable_attempt_id": "A000002",
                           "page_url": "https://www.wikidata.org/wiki/Q2?redirect=no",
                           "observed_at": None}]}


def resolutions():
    return {"format": "idea-json-backup-redirect-resolution", "format_version": "1.0.0",
            "run_id": RUN_ID, "state_sequence": 12,
            "inputs": {"qid_list": descriptor("selection/qids.txt"),
                       "inventory": descriptor("inventory.jsonl"), "attempts": descriptor("attempts.jsonl")},
            "redirects": [{"requested_qid": "Q2", "target_qid": "Q1", "unavailable_attempt_id": "A000002",
                           "source_response": descriptor("responses/A000002.decoded", complete=True),
                           "target_item": descriptor("items/Q1.json"),
                           "evidence": {"evidence_kind": "operator_recorded",
                                        "page_url": "https://www.wikidata.org/wiki/Q2?redirect=no",
                                        "observed_at": None, "recorded_at": STAMP,
                                        "recorded_by": "Invented Danu's review~01"}}]}


def release():
    return {"format": "idea-json-backup-release", "format_version": "1.0.0",
            "release_id": RELEASE_ID, "run_id": RUN_ID, "run_kind": "synthetic", "created_at": STAMP,
            "completion_basis": "usable_items_and_reviewed_redirects",
            "inputs": {"manifest": descriptor("collection/manifest.json"),
                       "inventory": descriptor("collection/inventory.jsonl"),
                       "attempts": descriptor("collection/attempts.jsonl"),
                       "qid_list": descriptor("collection/selection/qids.txt")},
            "resolutions": descriptor("redirect-resolutions.json"),
            "strict_verification": descriptor("strict-verification.json"),
            "readme": descriptor("README.md"), "verification_path": "verification.json",
            "counts": {"selected": 2, "usable_items": 1, "redirected": 1, "pending": 0, "unresolved": 0},
            "limitations": ["Invented operator-reported redirect; observation time unknown"]}


class ReleaseContractTests(unittest.TestCase):
    def test_valid_invented_records_preserve_unknown_times_and_exact_identifiers(self):
        from scripts.idea_json_backup.release_contract import validate_request, validate_resolutions, validate_release
        for factory, validator in ((request, validate_request), (resolutions, validate_resolutions), (release, validate_release)):
            for parsed in (False, True):
                with self.subTest(record=factory.__name__, parsed=parsed):
                    value = factory()
                    if parsed:
                        value = loads(dumps(value))
                    original = copy.deepcopy(value)
                    self.assertIsNone(validator(value))
                    self.assertEqual(value, original)

    def test_request_rejects_ambiguous_or_unsafe_mapping(self):
        from scripts.idea_json_backup.release_contract import validate_request
        for case in ("self", "duplicate", "chain", "secret", "missing", "bad_time", "bool_sequence", "extra"):
            with self.subTest(case=case):
                value = request()
                row = value["redirects"][0]
                if case == "self": row["target_qid"] = "Q2"
                elif case == "duplicate": value["redirects"].append(dict(row))
                elif case == "chain":
                    value["redirects"].append(dict(row, requested_qid="Q1", target_qid="Q3",
                        page_url="https://www.wikidata.org/wiki/Q1?redirect=no"))
                elif case == "secret": row["page_url"] += "&token=invented-secret"
                elif case == "missing": del row["observed_at"]
                elif case == "bad_time": row["observed_at"] = "2026-02-30T12:00:00Z"
                elif case == "bool_sequence": value["state_sequence"] = True
                else: value["extra"] = "unsupported"
                with self.assertRaises(ValueError) as caught: validate_request(value)
                self.assertNotIn("invented-secret", str(caught.exception))

    def test_resolutions_require_bound_regular_descriptor_shapes(self):
        from scripts.idea_json_backup.release_contract import validate_resolutions
        for case in ("source_incomplete", "target_path", "traversal", "sha", "missing_identity", "extra_evidence"):
            with self.subTest(case=case):
                value = resolutions()
                row = value["redirects"][0]
                if case == "source_incomplete": row["source_response"]["complete"] = False
                elif case == "target_path": row["target_item"]["path"] = "items/Q2.json"
                elif case == "traversal": row["source_response"]["path"] = "../outside"
                elif case == "sha": row["target_item"]["sha256"] = "bad"
                elif case == "missing_identity": row["evidence"]["recorded_by"] = None
                else: row["evidence"]["claimed_independent"] = True
                with self.assertRaises(ValueError): validate_resolutions(value)

    def test_release_counts_and_paths_cannot_imply_more_item_jsons(self):
        from scripts.idea_json_backup.release_contract import validate_release
        for case in ("counts", "pending", "unresolved", "basis", "path", "bad_id", "version"):
            with self.subTest(case=case):
                value = release()
                if case == "counts": value["counts"]["usable_items"] = 2
                elif case in ("pending", "unresolved"): value["counts"][case] = 1
                elif case == "basis": value["completion_basis"] = "all_items_accepted"
                elif case == "path": value["inputs"]["manifest"]["path"] = "manifest.json"
                elif case == "bad_id": value["release_id"] = "20260230T120000.000000Z-bad"
                else: value["format_version"] = "2"
                with self.assertRaises(ValueError): validate_release(value)

    def test_integer_types_preserve_large_tokens_without_coercion(self):
        from scripts.idea_json_backup.release_contract import integer
        self.assertEqual(integer(Number("900719925474099300000")), 900719925474099300000)
        for value in (True, 1.0, "1", Number("1.0"), Number("1e1")):
            with self.subTest(value=value), self.assertRaises(ValueError): integer(value)


if __name__ == "__main__":
    unittest.main()
