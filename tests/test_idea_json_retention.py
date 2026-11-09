"""Invented historical evidence; no real collection or repository operations."""
import copy
import traceback
import unittest


INCOMPLETE = {"code": "acquisition_incomplete", "qid": None, "path": None,
              "message": "Operator-recorded acquisition is incomplete; deposit remains unverified"}


def evidence(*, complete=False):
    stamp = "2026-11-08T12:00:00.000000Z" if complete else None
    return {"format_version": "1.0.0", "package_id": "20261108T120000.000000Z-invented-retention",
            "checked_at": "2026-11-08T12:01:00.000000Z", "byte_status": "passed",
            "deposit_status": "passed" if complete else "not_checked", "publication": None,
            "findings": [] if complete else [dict(INCOMPLETE)],
            "acquisition": {
                "dataset_url": "https://dataverse.yale.edu/dataset.xhtml?persistentId=doi:10.9999/fixture&version=DRAFT",
                "persistent_id": "doi:10.9999/fixture'0007~01", "dataset_version": "DRAFT",
                "downloaded_at": stamp, "recorded_by": "Invented operator's fixture~01",
                "evidence_kind": "operator_recorded",
                "files": [{"remote_file_id": f"{index:04d}", "download_url":
                           f"https://dataverse.yale.edu/api/access/datafile/{index:04d}",
                           "local_path": name, "downloaded_at": stamp}
                          for index, name in enumerate(("package-inventory.json", "part-00001.tar.gz"), 7)]}}


class RetentionTests(unittest.TestCase):
    def test_preserves_byte_evidence_with_explicitly_unknown_times(self):
        from scripts.idea_json_backup.retention import validate_retention_evidence
        report = evidence()
        before = copy.deepcopy(report)
        validate_retention_evidence(report)
        self.assertEqual(report, before)
        self.assertEqual(report["deposit_status"], "not_checked")
        self.assertIsNone(report["acquisition"]["downloaded_at"])

    def test_complete_historical_receipt_and_legacy_null_are_accepted(self):
        from scripts.idea_json_backup.retention import validate_retention_evidence
        validate_retention_evidence(None)
        report = evidence(complete=True)
        before = copy.deepcopy(report)
        validate_retention_evidence(report)
        self.assertEqual(report, before)
        self.assertEqual(report["acquisition"]["files"][0]["remote_file_id"], "0007")

    def test_failed_or_inconsistent_claims_cannot_confer_retention(self):
        from scripts.idea_json_backup.retention import validate_retention_evidence
        for case in ("failed_bytes", "false_deposit", "missing_finding", "extra_finding",
                     "published", "complete_but_unchecked"):
            with self.subTest(case=case):
                report = evidence(complete=case == "complete_but_unchecked")
                if case == "failed_bytes":
                    report["byte_status"] = "failed"
                elif case in ("false_deposit", "complete_but_unchecked"):
                    report["deposit_status"] = "passed" if case == "false_deposit" else "not_checked"
                elif case == "missing_finding":
                    report["findings"] = []
                elif case == "extra_finding":
                    report["findings"].append(dict(INCOMPLETE))
                else:
                    report["publication"] = {"claimed": "published"}
                with self.assertRaises(ValueError):
                    validate_retention_evidence(report)

    def test_only_timing_unknowns_are_allowed(self):
        from scripts.idea_json_backup.retention import validate_retention_evidence
        for field in ("dataset_url", "persistent_id", "dataset_version", "recorded_by", "files",
                      "remote_file_id", "download_url", "local_path"):
            with self.subTest(field=field):
                report = evidence()
                target = report["acquisition"]
                if field in ("remote_file_id", "download_url", "local_path"):
                    target = target["files"][0]
                target[field] = None
                with self.assertRaises(ValueError):
                    validate_retention_evidence(report)

    def test_inventory_and_sequential_unique_archive_identity_are_required(self):
        from scripts.idea_json_backup.retention import validate_retention_evidence
        for case in ("no_inventory", "no_archive", "gap", "duplicate_path", "duplicate_id"):
            with self.subTest(case=case):
                report = evidence()
                rows = report["acquisition"]["files"]
                if case == "no_inventory":
                    rows.pop(0)
                elif case == "no_archive":
                    rows.pop()
                elif case == "gap":
                    rows[1]["local_path"] = "part-00002.tar.gz"
                else:
                    key = "local_path" if case == "duplicate_path" else "remote_file_id"
                    rows[1][key] = rows[0][key]
                with self.assertRaises(ValueError):
                    validate_retention_evidence(report)

    def test_unsafe_historical_urls_are_rejected_without_echoing_secrets(self):
        from scripts.idea_json_backup.retention import validate_retention_evidence
        for url in ("https://dataverse.yale.edu/dataset?previewToken=invented-secret",
                    "https://dataverse.yale.edu/api/access/datafile/7?key=invented-secret",
                    "https://dataverse.yale.edu/api/datasets/:persistentId/privateUrlDatasetVersion/invented-secret",
                    "https://dataverse.yale.edu:invented-secret/dataset",
                    "https://user:invented-secret@dataverse.yale.edu/dataset"):
            with self.subTest(url=url):
                report = evidence()
                report["acquisition"]["files"][1]["download_url"] = url
                with self.assertRaises(ValueError) as caught:
                    validate_retention_evidence(report)
                self.assertNotIn("invented-secret", str(caught.exception))
                self.assertNotIn("invented-secret", "".join(traceback.format_exception(caught.exception)))

    def test_report_identity_schema_and_calendar_times_are_strict(self):
        from scripts.idea_json_backup.retention import validate_retention_evidence
        for change in ({"extra": "unapproved"}, {"format_version": "2"}, {"package_id": "invented"},
                       {"package_id": "20260230T120000.000000Z-invented"},
                       {"checked_at": "2026-02-30T12:00:00Z"}, {"checked_at": None}, {"acquisition": None}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_retention_evidence(dict(evidence(), **change))


if __name__ == "__main__":
    unittest.main()
