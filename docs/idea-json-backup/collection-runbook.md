# Production collector: guided pilot runbook

Reviewed 2026-11-03; updated 2026-11-07 after the successful third pilot attempt and documentation fix. **Offline collection-stage reviews are clear for the guided parent-linked pilot.** The current full offline suite passed 238 tests, including the historical sample suite. Danu executes operational commands one guided step at a time and returns each report. The assistant runs offline TDD and makes local commits. Full-population collection, scale and archive readiness are not established by this clearance.

The saved production parent `backup/idea-selection-001` contains the frozen 33,709-QID population. The earlier MVP pilot tested prototype preservation; it did not exercise this production journal, recovery or finalization workflow. Start with a parent-linked three-item production pilot.

Checkpoint 2026-11-03: Danu reported Stop 1 creation and separate saved-selection verification passed with no findings, count 3. Read-only preflight confirmed the exact declared subset, unchanged copied parent evidence/descriptors and absent `backup/idea-pilot-run-001`. Current official access/module/etiquette/maxlag guidance has been rechecked for this bounded pilot; see the [Research update](research.md#2026-11-03-production-pilot-access-recheck). The next guided command is the one-batch pilot below; it has not been executed by the assistant.

Subsequent pilot result: Danu executed that one-batch command; it paused with three unresolved items and zero accepted because Wikidata returned API `maxlag` with Retry-After 5. The complete error response is retained as A000001, consuming one attempt per QID. Scope/overall verification is `not_checked`; source-content/provenance/files checks passed. Guided recovery now uses `resume --run backup/idea-pilot-run-001 --max-batches 1` after the persisted cooldown, retaining the same run and quota. Do not rerun `collect` into this directory. This expected transient path is already covered by offline tests; no implementation change is required by the observed evidence.

Second result: Danu's bounded resume also returned maxlag, with the same unfinished counts and passed non-scope checks. A000002 is retained; each QID has now consumed two of three attempts. The recorded ten-second lower bound is `2026-11-03T09:38:41.595270Z`. Recommend waiting a further 15–30 minutes before the final bounded resume. That voluntary wait does not change settings/quota. If the third attempt also fails, retain the run and review the outcome before any further retrieval; do not reset quota or bypass maxlag.

Third result (November 7 New York; saved UTC November 8): all three accepted, none unresolved, all four checks passed. Local review confirms strict item/source equality and retained earlier errors. The run is collected and awaits explicit finalization. Review found that the original implementation omitted the required README and its audit accounting; the reviewed offline fix is now implemented. **Current guided stop: add that missing README using the command below.** Do not resume or restart collection.

Run commands from `/Users/danu/Documents/ChatGPT/Dura-Europos`. Every new output directory must be absent; do not create it beforehand or reuse an earlier attempt.

## Stop 1: prepare the exact parent-linked subset

Danu runs:

```bash
python3 -B -m scripts.export_idea_json pilot-selection \
  --parent backup/idea-selection-001 \
  --qids docs/idea-json-backup/pilot-001/qids.txt \
  --output backup/idea-pilot-selection-001
```

This is an offline operation. It verifies the complete production parent, retains its public evidence unchanged, and freezes the declared three-QID subset in numeric order with `kind: pilot`. It cannot expand the subset or replace the parent list. A passing report should give `selected_count: 3`.

**Stop and return the complete report.** After it is reviewed, perform the separate read-only check:

```bash
python3 -B -m scripts.export_idea_json verify-selection backup/idea-pilot-selection-001
```

Stop again and return that report. Passing subset verification is not item-collection completion.

## Later guided stop: collect one pilot batch

Only after the subset and its persisted check are reviewed, and current service-access guidance has been checked:

```bash
python3 -B -m scripts.export_idea_json collect \
  --selection backup/idea-pilot-selection-001 \
  --run backup/idea-pilot-run-001 \
  --kind pilot \
  --max-batches 1
```

This is a live read-only Wikidata request. Reservations consume attempt quota before dispatch. Complete source evidence is committed before item acceptance; extracted JSON retains all fields, types and numeric tokens. Membership changes stay visible without removing a frozen QID. The command then independently audits the public saved files.

Stop and return its report. The one-batch limit is an execution bound, not a completeness criterion. A run with unresolved items or remaining work cannot be reported as a complete collection.

## Guided status, audit and finalization

The actual pilot was created before README generation was fixed. First, Danu explicitly adds its missing scope documentation offline:

```bash
python3 -B -m scripts.export_idea_json write-readme --run backup/idea-pilot-run-001
```

Stop and return the report. Expected status passed, created true and a README descriptor. The writer holds the existing lock, audits accepted/source evidence and adds only the missing README; existing public files and consumed quota stay unchanged. Existing matching documentation is an unchanged created-false result. Different documentation, pending publication or a finalized run is held for review. An interrupted documentation publication retains private staging and requires review; do not delete it to retry. New runs create their scope README automatically. Terminal runs missing valid documentation now fail independent verification, closing the earlier omission.

Use each command only at its guided step, returning its output before proceeding:

```bash
python3 -B -m scripts.export_idea_json status --run backup/idea-pilot-run-001
```

`status: passed` here means the journal status was read successfully. Inspect its phase, counts and `collection_status`; it is not an independent content-verification result.

For this collected pilot, expect selected/accepted 3, pending/unresolved 0, phase collected and collection_status not_checked until explicit finalization records its report.

```bash
python3 -B -m scripts.export_idea_json verify --run backup/idea-pilot-run-001
```

This is a read-only public audit, with no fetching, repairs or checksum refresh. Known failures take precedence over unfinished work. Exit 0 means that action passed; exit 1 means known failure; exit 2 means required work is unfinished or interrupted.

After the stopped collected run and all required checks pass, explicit finalization is:

```bash
python3 -B -m scripts.export_idea_json verify --run backup/idea-pilot-run-001 --write
```

Finalization publishes the verification report before the final manifest, then commits journal bookkeeping. A passing finalization makes the payload immutable; later audits are read-only. Interrupted finalization must complete only its exact prepared bytes after input checks, without regenerating evidence or fetching again.

## Recovery and retained evidence

Use `resume --run backup/idea-pilot-run-001` only when a guided review determines it is needed. It can make live requests for unresolved eligible QIDs, so it is not a status command. It preserves accepted revisions, honors recovered server waits and retains the maximum three-attempt quota per QID across restarts. A committed usable source is recovered locally before any refetch is considered.

Missing/corrupt state, changed immutable inputs, saving failures or `server_wait_unknown` require review. Do not delete or reset the journal, clear quota, reuse a directory, overwrite an item, or create a replacement attempt to bypass a server wait. Retain partial bytes and error evidence.

Public records link each item to its complete source response and recorded descriptors/checksums. `.state/` contains local SQLite/lock/receipt/staging/finalization recovery artifacts; retain it locally and never upload it as collection payload.

## Boundary before expansion

Full 33,709-item collection must wait for this parent-linked production pilot review and later synthetic scale/archive feasibility checks. No full-collection command is supplied at this stage. A passing small pilot is not a bulk-service endorsement. Packaging, Yale archive-retention testing, deposit verification and publication remain later stages; destination/access/metadata still need resolution before deposit. No Wikidata edits are part of this workflow.

Implementation evidence: [increment log](production-log.md) and [local stage review](../../review/idea-json-backup-production-collection-review-2026-11-03.md). The latter records separate storage, recovery, verification and integrated review passes; it is offline implementation evidence, not a live production pilot result.
