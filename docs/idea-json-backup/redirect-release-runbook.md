# Guided redirect-release operations

Prepared2026-11-08 after Danu approved redirect-record-only. Offline implementation is complete:342 tests passed29.744s, separate contract/producer/verifier/package reviews and a final independent invented CLI composition are clear. The original33,708-accepted/1-unresolved source has not been re-audited operationally with the improved diagnostics, and no actual release/package has been created by the assistant.

The [reviewed request](../../review/idea-json-backup-production-redirect-request-001.json) explicitly binds run20261109T012636.715412Z-746d5d786f2f, generation36409, frozen-list hash and Q134471369→Q122677115/A000623. observed_at is null; the mapping is operator_recorded. All future generated record times describe creation, not the unknown earlier observation. No historical JSON retrieval is requested.

## Stop1: audit all original saved data and retain its strict result

From /Users/danu/Documents/ChatGPT/Dura-Europos, Danu runs:

```bash
python3 -B -m scripts.export_idea_json verify \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --report /Users/danu/Documents/ChatGPT/Dura-Europos/review/idea-json-backup-production-strict-001.json
```

Return the entire JSON report. This reads/hashes every accepted source/item and writes a new external diagnostic report. It does not change the original run or request new data. Read-only preflight found the report path absent. Never overwrite it or add --write to this step.

Expected result: original strict status/scope **failed** only for Q134471369, accurate counts33,709selected/33,708accepted/0pending/1unresolved, and source_content/provenance/files **passed**. The failure remains intentional under the original rule; the new release will separately reconcile the reviewed redirect. If another finding/check fails, stop and review it before making the release.

## Stop2: capacity before a separate public-payload copy

After reviewing Stop1, Danu obtains the current allocated breakdown and free space:

```bash
du -h -d 1 /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001
df -h /Users/danu/Documents/ChatGPT/Dura-Europos
```

Return both outputs. The old289M/12Gi measurements were before the remainder was collected. Plan for one additional public-payload copy excluding .state/, then later archives/downloads/temporary extraction. No cleanup, drive purchase or fixed free-space threshold is assumed.

## Stop3: create the separate resolved release

Only after source/capacity review, Danu runs:

```bash
python3 -B -m scripts.export_idea_json create-release \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --request /Users/danu/Documents/ChatGPT/Dura-Europos/review/idea-json-backup-production-redirect-request-001.json \
  --output /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-release-001
```

The output must be absent; do not create it beforehand. Initial read-only preflight found it absent/no symlink. Return the report. Expect status passed, all four release checks passed, selected33,709/usable_items33,708/redirected1/pending0/unresolved0. The nested original collection/ remains unchanged and strictly failed for that one unavailable QID. On interruption/failure retain the original and partial release; do not delete, overwrite or reuse output to retry without review.

## Stop4: separate saved-release verification

After reviewing creation, Danu runs:

```bash
python3 -B -m scripts.export_idea_json verify-release \
  /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-release-001
```

Return the entire report. This independently checks all saved release/source/resolution/report bytes and does not repair anything. A passing reconciliation is distinct from ordinary acceptance of the old QID and from deposit/publication.

## Stop5: archive the verified release

After saved-release and profile/capacity review, Danu runs:

```bash
python3 -B -m scripts.export_idea_json package-release \
  --release /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-release-001 \
  --output /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-package-001 \
  --profile /Users/danu/Documents/ChatGPT/Dura-Europos/changes/idea-json-backup/production-archive-profile.json
```

Output must be absent; initial preflight found it absent/no symlink. Return the JSON. The external package inventory uses1.1.0/payload_kind resolved_release, bounded tar.gz parts, and full independent extraction/audit. The proposed profile's local caps are not measured Yale maximum limits; its embedded pilot byte evidence still says deposit not_checked for unknown times. Do not change the immutable pilot.

After reviewing packaging, separately run verify-package on that new package and return its report. Full production deposit metadata/destination/upload/download/acquisition verification and publication remain later guided operations. The pilot's DOI/file IDs do not automatically identify a production deposit.
