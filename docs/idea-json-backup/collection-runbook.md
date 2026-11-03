# Production collector: guided pilot runbook

Reviewed 2026-11-03. **Offline collection-stage reviews are clear for the guided parent-linked pilot.** The full offline suite passed 227 tests, including the historical sample suite. Danu executes operational commands one guided step at a time and returns each report. The assistant runs offline TDD and makes local commits. Full-population collection, scale and archive readiness are not established by this clearance.

The saved production parent `backup/idea-selection-001` contains the frozen 33,709-QID population. The earlier MVP pilot tested prototype preservation; it did not exercise this production journal, recovery or finalization workflow. Start with a parent-linked three-item production pilot.

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

Use each command only at its guided step, returning its output before proceeding:

```bash
python3 -B -m scripts.export_idea_json status --run backup/idea-pilot-run-001
```

`status: passed` here means the journal status was read successfully. Inspect its phase, counts and `collection_status`; it is not an independent content-verification result.

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
