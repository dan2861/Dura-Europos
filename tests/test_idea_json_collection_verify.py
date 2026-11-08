"""Independent invented public collection records; no store or collector used."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.sample_backup.jsoncodec import Number, dumps, loads
from test_idea_json_selection_verify import fixture as selection_fixture

TIME = "2026-11-03T12:00:00.000000Z"
HEADERS = {"Accept": "application/json", "Accept-Encoding": "gzip, identity",
           "User-Agent": "Invented-Test/1 (https://example.org/contact)"}
PARAMETERS = {"action": "wbgetentities", "format": "json", "formatversion": "2",
              "redirects": "no", "maxlag": "5"}
ENTITY = (b'{"id":"Q1","type":"item","lastrevid":7,"modified":"2026-11-03T11:00:00Z",'
          b'"unknown":{"identifier":"0007","number":1.2300000000000000000001,"flag":true},'
          b'"claims":{"P5008":[{"rank":"normal","mainsnak":{"snaktype":"value",'
          b'"datavalue":{"type":"wikibase-entityid","value":{"entity-type":"item","id":"Q114241199"}}}}]}}')


def store(root, name, body, **extra):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return dict(path=name, size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), **extra)


def write_json(root, name, value):
    return store(root, name, (dumps(value) + "\n").encode())


def rewrite(root, manifest, inventory, attempts):
    for name, records in (("inventory", inventory), ("attempts", attempts)):
        descriptor = store(root, name + ".jsonl", b"".join((dumps(row) + "\n").encode() for row in records))
        manifest["public_records"][name]["file"] = descriptor
    write_json(root, "manifest.json", manifest)


def fixture(root):
    root.mkdir()
    selection_fixture(root / "selection", main=("Q1",), scholarly=())
    selection = {"metadata": store(root, "selection/selection.json", (root / "selection/selection.json").read_bytes()),
                 "qid_list": store(root, "selection/qids.txt", b"Q1\n"), "selected_count": 1}
    source = b'{"success":1,"entities":{"Q1":' + ENTITY + b'}}'
    source_descriptor = store(root, "responses/A000001.json", source, complete=True)
    attempt = {"attempt_id": "A000001", "requested_qids": ["Q1"], "reserved_at": TIME,
               "dispatch_started_at": "2026-11-03T12:00:01.000000Z",
               "headers_received_at": "2026-11-03T12:00:02.000000Z", "headers_observed": True,
               "response_received_at": "2026-11-03T12:00:02.000000Z", "response_elapsed_ms": 1000,
               "receipt_complete": True, "finished_at": "2026-11-03T12:00:03.000000Z", "recovered_at": None,
               "request": {"method": "GET", "url": "https://www.wikidata.org/w/api.php",
                           "parameters": dict(PARAMETERS, ids="Q1"), "headers": dict(HEADERS)},
               "http": {"status_code": 200, "headers": {"content-encoding": ["identity"],
                        "content-length": [str(len(source))]}},
               "encoded": source_descriptor, "decoded": dict(source_descriptor), "diagnostics": [],
               "api_error": None, "warnings": None, "outcome": "succeeded",
               "item_results": [{"qid": "Q1", "outcome": "accepted", "returned_qid": "Q1", "error": None}],
               "next_eligible_at": None, "error": None}
    inventory = [{"requested_qid": "Q1", "returned_qid": "Q1", "status": "accepted", "lastrevid": 7,
                  "modified": "2026-11-03T11:00:00Z", "retrieved_at": attempt["response_received_at"],
                  "item": store(root, "items/Q1.json", ENTITY), "source_response_id": "A000001",
                  "source_entity_key": "Q1", "attempt_ids": ["A000001"], "membership_at_retrieval": "matches",
                  "next_eligible_at": None, "error": None}]
    manifest = {"format": "idea-json-backup", "format_version": "1.0.0",
                "run_id": "20261103T120000.000000Z-invented", "run_kind": "synthetic", "exporter_version": "0.1.0",
                "runtime": {"python": "3.12.0", "sqlite": "3.43.2", "platform": "Invented"},
                "selection": selection, "created_at": TIME, "started_at": attempt["dispatch_started_at"],
                "finished_at": attempt["finished_at"], "request_settings": {
                    "endpoint": "https://www.wikidata.org/w/api.php", "action_parameters": dict(PARAMETERS),
                    "headers": dict(HEADERS), "batch_size": 50, "concurrency": 1, "minimum_gap_seconds": 1,
                    "response_deadline_seconds": 60, "max_attempts_per_item": 3, "retry_backoff_seconds": [5, 10],
                    "supported_content_encodings": ["identity", "gzip"], "http_redirect_policy": "reject"},
                "next_dispatch_at": "2026-11-03T12:00:04.000000Z", "phase": "collected", "state_sequence": 5,
                "public_records": {name: {"file": None, "state_sequence": 5} for name in ("inventory", "attempts")},
                "counts": {"selected": 1, "accepted": 1, "pending": 0, "unresolved": 0},
                "collection_status": "not_checked", "verification_path": None,
                "limitations": ["Collection period; no media, full history or recursive linked-entity retrieval"]}
    # Declared independently: the verifier fixture never calls documentation generation.
    store(root, "README.md", (
        "# Invented preservation run\n\n"
        "Run ID: 20261103T120000.000000Z-invented\n"
        "Run kind: synthetic\n"
        "Frozen QIDs: 1\n"
        "Frozen QID list SHA-256: " + selection["qid_list"]["sha256"] + "\n\n"
        "Items are extracted item JSON; responses retain preserved response-body bytes.\n"
        "A collection period is not one historical instant. Scope excludes media bytes,\n"
        "full revision history and recursive linked entities. Consult manifest.json,\n"
        "inventory.jsonl, attempts.jsonl and verification.json for actual outcomes.\n"
        ".state/ is private local recovery evidence; retain it locally, never deposit it.\n"
        "Keep the frozen selection, accepted revisions and consumed retry quota on recovery.\n"
    ).encode())
    rewrite(root, manifest, inventory, [attempt])
    return manifest, inventory, [attempt]


def at(second):
    return (datetime(2026, 11, 3, 12, tzinfo=timezone.utc) + timedelta(seconds=second)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")


def with_retry(root, *, dispatch=8, status=503, retry_after=None, api_error=None):
    manifest, inventory, attempts = fixture(root)
    successful = attempts[0]
    successful.update(attempt_id="A000002", reserved_at=at(dispatch), dispatch_started_at=at(dispatch),
                      headers_received_at=at(dispatch + 1), response_received_at=at(dispatch + 1),
                      finished_at=at(dispatch + 2))
    response = (root / successful["decoded"]["path"]).read_bytes()
    (root / successful["decoded"]["path"]).unlink()
    successful["encoded"] = store(root, "responses/A000002.json", response, complete=True)
    successful["decoded"] = dict(successful["encoded"])
    failed_body = (b'{"error":{"code":"maxlag","info":"busy"}}' if api_error else b"busy")
    previous = copy.deepcopy(successful)
    previous.update(attempt_id="A000001", reserved_at=at(0), dispatch_started_at=at(1),
                    headers_received_at=at(2), response_received_at=at(2), finished_at=at(3),
                    http={"status_code": status, "headers": {"content-length": [str(len(failed_body))]}},
                    api_error=api_error, outcome="transient_failure",
                    error={"stage": "api" if api_error else "transport", "code": "maxlag" if api_error else "http_error",
                           "message": "busy", "retryable": True},
                    item_results=[{"qid": "Q1", "outcome": "transient_failure", "returned_qid": None,
                                   "error": {"stage": "api" if api_error else "transport", "code": "busy",
                                             "message": "busy", "retryable": True}}], next_eligible_at=at(8))
    if retry_after:
        previous["http"]["headers"]["retry-after"] = retry_after
        previous["next_eligible_at"] = at(max(8, 2 + max(int(v) for v in retry_after)))
    previous["encoded"] = store(root, "responses/A000001.failure", failed_body, complete=True)
    previous["decoded"] = dict(previous["encoded"])
    inventory[0].update(source_response_id="A000002", retrieved_at=at(dispatch + 1),
                        attempt_ids=["A000001", "A000002"])
    manifest.update(finished_at=at(dispatch + 2), next_dispatch_at=at(dispatch + 3))
    rewrite(root, manifest, inventory, [previous, successful])
    return manifest, inventory, [previous, successful]


class CollectionVerifierTests(unittest.TestCase):
    def test_declared_readme_is_accounted_without_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            fixture(root)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(verify_collection(root)["status"], "passed")
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_terminal_missing_readme_prevents_a_passing_collection(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            fixture(root)
            (root / "README.md").unlink()
            report = verify_collection(root)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["findings"][0]["code"], "missing_readme")
            self.assertEqual(report["findings"][0]["path"], "README.md")

    def test_active_legacy_missing_readme_is_unfinished_without_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = fixture(root)
            manifest.update(phase="paused", finished_at=None)
            rewrite(root, manifest, inventory, attempts)
            (root / "README.md").unlink()
            self.assertEqual(verify_collection(root)["status"], "not_checked")
            self.assertFalse((root / "README.md").exists())

    def test_invalid_readme_identity_or_text_cannot_pass(self):
        for corruption in ("run_id", "kind", "count", "list_hash", "duplicate_identity", "empty", "utf8"):
            with self.subTest(corruption=corruption), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                fixture(root)
                path = root / "README.md"
                body = path.read_bytes()
                if corruption == "run_id":
                    body = body.replace(b"20261103T120000.000000Z-invented", b"20261103T120000.000000Z-another")
                elif corruption == "kind":
                    body = body.replace(b"Run kind: synthetic", b"Run kind: production")
                elif corruption == "count":
                    body = body.replace(b"Frozen QIDs: 1", b"Frozen QIDs: 33709")
                elif corruption == "list_hash":
                    body = body.replace(hashlib.sha256(b"Q1\n").hexdigest().encode(), b"0" * 64)
                elif corruption == "duplicate_identity":
                    body += b"Run kind: production\n"
                elif corruption == "empty":
                    body = b"\n  \n"
                else:
                    body = b"\xff\xfe"
                path.write_bytes(body)
                report = verify_collection(root)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["findings"][0]["code"], "invalid_readme")
                self.assertEqual(report["findings"][0]["path"], "README.md")

    def test_linked_readme_cannot_be_treated_as_public_documentation(self):
        for link in ("symlink", "hardlink"):
            with self.subTest(link=link), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                fixture(root)
                path = root / "README.md"
                outside = Path(directory) / "outside.md"
                outside.write_bytes(path.read_bytes())
                path.unlink()
                if link == "symlink":
                    path.symlink_to(outside)
                else:
                    path.hardlink_to(outside)
                report = verify_collection(root)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["findings"][0]["path"], "README.md")

    def test_nonretryable_item_hold_cannot_be_silently_requested_again(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = with_retry(root)
            prior = attempts[0]
            prior["outcome"] = "review_required"
            prior["error"]["retryable"] = False
            prior["item_results"][0].update(outcome="review_required", error=copy.deepcopy(prior["error"]))
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_internal_state_must_be_a_directory_not_a_symlink(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            fixture(root)
            outside = Path(directory) / "outside-state"
            outside.mkdir()
            (root / ".state").symlink_to(outside, target_is_directory=True)
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_nonvalue_membership_with_a_datavalue_is_not_accepted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = fixture(root)
            entity = loads(ENTITY)
            entity["claims"]["P5008"][0]["mainsnak"]["snaktype"] = "novalue"
            encoded = dumps({"success": 1, "entities": {"Q1": entity}}).encode()
            descriptor = store(root, attempts[0]["decoded"]["path"], encoded, complete=True)
            attempts[0].update(encoded=descriptor, decoded=dict(descriptor))
            attempts[0]["http"]["headers"]["content-length"] = [str(len(encoded))]
            inventory[0].update(membership_at_retrieval="changed", item=store(root, "items/Q1.json", dumps(entity).encode()))
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_warning_bearing_maxlag_is_a_hold_not_retry_history(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = with_retry(root, status=200, api_error={"code": "maxlag", "message": "busy"})
            prior = attempts[0]
            name = prior["decoded"]["path"]
            envelope = loads((root / name).read_bytes())
            envelope["warnings"] = {"wbgetentities": {"*": "Invented warning requiring review"}}
            encoded = dumps(envelope).encode()
            descriptor = store(root, name, encoded, complete=True)
            prior.update(encoded=descriptor, decoded=dict(descriptor), warnings=envelope["warnings"])
            prior["http"]["headers"]["content-length"] = [str(len(encoded))]
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_known_header_transport_interruption_can_resume_without_recovery_timestamp(self):
        for known, expected in ((True, "passed"), (False, "passed"), (None, "failed")):
            with self.subTest(known=known), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                manifest, inventory, attempts = with_retry(root, status=200)
                prior = attempts[0]
                name = prior["decoded"]["path"]
                prior.update(outcome="interrupted", recovered_at=None, receipt_complete=False if known else None,
                             headers_observed=known, response_received_at=None, response_elapsed_ms=None,
                             decoded=None, error={"stage": "transport", "code": "interrupted_capture",
                             "message": "Interrupted during capture", "retryable": True})
                prior["item_results"][0]["error"] = copy.deepcopy(prior["error"])
                if known is True:
                    prior["encoded"]["complete"] = False
                else:
                    prior.update(http=None, headers_received_at=None, encoded=None)
                    (root / name).unlink()
                rewrite(root, manifest, inventory, attempts)
                self.assertEqual(verify_collection(root)["status"], expected)

    def test_recovered_reservation_uses_recovery_time_without_inventing_finish(self):
        for known, dispatched, expected in ((True, True, "passed"), (False, True, "passed"),
                                            (None, False, "passed"), (None, True, "failed")):
            with self.subTest(known=known, dispatched=dispatched), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                manifest, inventory, attempts = with_retry(root, dispatch=15)
                prior = attempts[0]
                old_path = prior["encoded"]["path"]
                prior.update(finished_at=None, recovered_at=at(10), receipt_complete=None,
                             response_received_at=None, response_elapsed_ms=None, headers_observed=known,
                             encoded=None, decoded=None, outcome="interrupted", next_eligible_at=at(15),
                             diagnostics=[{"role": "recovered_body", "file": store(root, old_path, b"busy", complete=None),
                                           "explanation": "Receipt completion was not journaled"}],
                             error={"stage": "recovery", "code": "interrupted", "message": "Recovered reservation", "retryable": True})
                prior["item_results"][0].update(outcome="unknown", error=copy.deepcopy(prior["error"]))
                if not dispatched:
                    prior["dispatch_started_at"] = None
                    manifest["started_at"] = attempts[1]["dispatch_started_at"]
                if known is not True:
                    prior.update(http=None, headers_received_at=None)
                rewrite(root, manifest, inventory, attempts)
                self.assertEqual(verify_collection(root)["status"], expected)

    def test_attempt_outcome_and_error_coherence_cannot_hide_failures(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "success-error"
            manifest, inventory, attempts = fixture(root)
            attempts[0]["error"] = {"stage": "saving", "code": "write_failed", "message": "disk failure", "retryable": False}
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "failed")
        with TemporaryDirectory() as directory:
            root = Path(directory) / "retry-error"
            manifest, inventory, attempts = with_retry(root, dispatch=7)
            attempts[0]["item_results"][0]["error"] = None
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_membership_is_derived_from_all_preserved_statement_ranks(self):
        base = loads(ENTITY)["claims"]["P5008"][0]
        other = copy.deepcopy(base)
        other["rank"] = "preferred"
        other["mainsnak"]["datavalue"]["value"]["id"] = "Q1"
        for rows, expected in (([copy.deepcopy(base), other], "matches"),
                               ([dict(copy.deepcopy(base), rank="deprecated")], "changed"),
                               ([dict(copy.deepcopy(base), rank="preferred")], "matches"), ([], "changed")):
            with self.subTest(expected=expected, rows=rows), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                manifest, inventory, attempts = fixture(root)
                entity = loads(ENTITY)
                entity["claims"]["P5008"] = rows
                encoded = dumps({"success": 1, "entities": {"Q1": entity}}).encode()
                descriptor = store(root, attempts[0]["decoded"]["path"], encoded, complete=True)
                attempts[0].update(encoded=descriptor, decoded=dict(descriptor))
                attempts[0]["http"]["headers"]["content-length"] = [str(len(encoded))]
                inventory[0].update(membership_at_retrieval=expected, item=store(root, "items/Q1.json", dumps(entity).encode()))
                rewrite(root, manifest, inventory, attempts)
                self.assertEqual(verify_collection(root)["status"], "passed")

    def test_changed_source_with_refreshed_descriptor_still_disagrees_with_item(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = fixture(root)
            name = attempts[0]["decoded"]["path"]
            original = (root / name).read_bytes()
            changed = original.replace(b'"identifier":"0007"', b'"identifier":"0008"')
            descriptor = store(root, name, changed, complete=True)
            attempts[0].update(encoded=descriptor, decoded=dict(descriptor))
            rewrite(root, manifest, inventory, attempts)
            report = verify_collection(root)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(next(check for check in report["checks"] if check["check_id"] == "source_content")["status"], "failed")

    def test_committed_complete_source_before_local_finish_is_unfinished(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = fixture(root)
            manifest.update(phase="paused", finished_at=None)
            attempts[0]["finished_at"] = None
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "not_checked")
            manifest.update(phase="collected", finished_at=at(3))
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_retry_waits_and_api_error_provenance_are_independent(self):
        for dispatch, retry_after, status, api_error, expected in (
                (8, None, 503, None, "passed"), (7, None, 503, None, "failed"),
                (10, ["20"], 503, None, "failed"), (22, ["2", "20"], 503, None, "passed"),
                (8, None, 200, {"code": "maxlag", "message": "busy"}, "passed"),
                (8, None, 200, {"code": "other_error", "message": "busy"}, "failed")):
            with self.subTest(dispatch=dispatch, retry_after=retry_after, api_error=api_error), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                with_retry(root, dispatch=dispatch, retry_after=retry_after, status=status, api_error=api_error)
                self.assertEqual(verify_collection(root)["status"], expected)

    def test_finalized_report_requires_full_shape_and_current_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = fixture(root)
            report = verify_collection(root)
            manifest.update(phase="finalized", collection_status="passed", verification_path="verification.json")
            write_json(root, "verification.json", {"run_id": manifest["run_id"], "status": "passed"})
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "failed")
            write_json(root, "verification.json", report)
            self.assertEqual(verify_collection(root)["status"], "passed")
            report["counts"]["selected"] = 2
            write_json(root, "verification.json", report)
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_independent_complete_public_fixture_passes_without_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            fixture(root)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            report = verify_collection(root)
            self.assertEqual(report["status"], "passed", report)
            self.assertEqual(report["findings"], [])
            self.assertEqual([row["check_id"] for row in report["checks"]],
                             ["scope", "source_content", "provenance", "files"])
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_changed_content_and_number_tokens_fail_after_checksum_refresh(self):
        for update in (lambda e: e["unknown"].update(number=Number("1.23")),
                       lambda e: e["unknown"].update(flag=Number("1")),
                       lambda e: e["unknown"].update(identifier="7")):
            with self.subTest(update=update), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                manifest, inventory, attempts = fixture(root)
                entity = loads(ENTITY)
                update(entity)
                inventory[0]["item"] = store(root, "items/Q1.json", dumps(entity).encode())
                rewrite(root, manifest, inventory, attempts)
                self.assertEqual(verify_collection(root)["status"], "failed")

    def test_stale_view_is_unfinished_but_corruption_still_dominates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            manifest, inventory, attempts = fixture(root)
            manifest["state_sequence"] = 6
            rewrite(root, manifest, inventory, attempts)
            self.assertEqual(verify_collection(root)["status"], "not_checked")
            (root / "items/Q1.json").write_bytes(b'{}')
            self.assertEqual(verify_collection(root)["status"], "failed")

    def test_scope_and_unaccounted_artifacts_fail(self):
        for mode in ("count", "duplicate", "extra"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                manifest, inventory, attempts = fixture(root)
                if mode == "count":
                    manifest["counts"]["selected"] = 2
                elif mode == "duplicate":
                    inventory.append(copy.deepcopy(inventory[0]))
                else:
                    (root / "unaccounted.body").write_bytes(b"unknown")
                rewrite(root, manifest, inventory, attempts)
                self.assertEqual(verify_collection(root)["status"], "failed")
