# Sample-backup runbook

Updated: 2026-10-20. Format: approved Spec 1.0.0. Exporter: 0.1.0.
Tested runtime: Python 3.12.0, standard library only. One project repository.

## Current implementation boundary

Local implementation and offline tests are authorized. A live export, retrieval of the sample, external edits, publication, and Git staging/commit/push are not authorized by this implementation task. No production run was made. All generated test artifacts used temporary directories; the existing saved real response was read unchanged.

The entry point is `scripts/export_sample_backup.py`. Importing it and building help do not retrieve or create run artifacts. The command requires an explicit action. `export` is the network action; `verify` reads existing artifacts offline. No implicit export, retry, resume, recursive lookup, media retrieval, or revision pinning exists.

## Offline tests

From `/Users/danu/Documents/ChatGPT/Dura-Europos`:

```bash
python3 -B -m unittest discover -s tests -p 'test_sample_backup_*.py' -v
```

Tests use invented transport responses and clearly identified synthetic entities. The real regression reads `review/q124840826-revision-2533342425-20261015T002253Z.json`; its fixed SHA-256 is `4824029e1fd0cf03a5e92bdbff07b2902b9efde11e580d219873290cc136bb3d`. Expected rows for that historical revision are 1 item, 41 statements, 28 qualifiers, 20 shared reference rows, and 29 attachments (11 complete groups; 70 expanded reference snaks). These are not expected counts for a future current retrieval.

The preservation tests compare complete source values/positions/relationships and CSV round-trips. The independent auditor reads sources and CSVs without calling the projection. Corruption tests recompute hashes deliberately to prove that matching inventory cannot conceal altered meaning. Synthetic manual evidence tests exercise status rules; they are not a real two-item manual review.

## Offline audit of an existing attempt

The following examples are future user commands, not commands run during implementation:

```bash
python3 scripts/export_sample_backup.py verify backup/ACTUAL_RUN_ID
```

This defaults to read-only. To persist check results atomically:

```bash
python3 scripts/export_sample_backup.py verify backup/ACTUAL_RUN_ID --write
```

Persisted validation does not refresh the original sizes/checksums/counts. It checkpoints completed automated checks before manual review, retaining pending states and failure precedence if interrupted. A malformed manifest is reported rather than silently repaired. Original JSON, CSVs, and failure bodies are not rewritten by verification.

Exit codes for both actions:

| Code | Meaning |
| --- | --- |
| 0 | All six categories passed; every requested retrieval succeeded. |
| 1 | Known retrieval, saving, preservation, or validation failure. |
| 2 | Required work is unfinished (`not_checked`), such as pending manual review. Argument usage errors also use argparse's code 2 and print usage/error text. |

Successful collection with manual review pending therefore returns 2, not success. The printed JSON report identifies each check and its details.

## Future explicitly requested live export

Only after a separate instruction to retrieve the sample:

```bash
python3 scripts/export_sample_backup.py export --input config/sample-items.txt --output backup
```

Preflight reads exact QID lines, preserves order, and rejects blank/malformed/duplicate IDs before any folder or request. Surrounding whitespace and lowercase prefixes are rejected rather than normalized. Canonical request QIDs use a positive unpadded ASCII number after Q; this does not alter or prohibit leading zeros in source inventory strings or datavalues. LF, CRLF and CR separate lines. An ordinary final line terminator does not add an empty record.

Each attempt exclusively creates `backup/<UTC-start>-<unique-suffix>/`, five header-bearing tables, the manifest, and original/failure directories. The actual list and count are snapshotted; no hard-coded 15-item count. Originals use the exact requested QID even if a different ID is returned. An empty request file produces an unfinished zero-request attempt, not a validated sample.

Requests use GET, JSON Accept, descriptive versioned User-Agent, no query filters, one at a time, at most five forwarding steps, and zero automatic retries. A supervised process enforces the 60-second overall response deadline across connection, redirect and body collection. Received body bytes and HTTP trace are spooled separately so partial evidence can survive worker termination. A complete 200 response must still contain usable unambiguous entity JSON.

All complete originals are saved before retrieval success is recorded. Diagnostic bodies retain received bytes unchanged and truthfully report complete/partial/unknown status. Empty received bodies create no diagnostic file. Saving failures stop further collection if storage cannot be used safely; earlier files remain. Missing checkpoint durability is reported, never claimed successful.

Returned-ID differences and collisions withhold affected CSV rows pending concrete identity review. Do not edit IDs, accept counterparts, merge requests, or change the schema automatically. Verification reports the hold. Resolving an actual hold requires Danu's decision and a separately reviewed change; no identity-acceptance command is provided.

## Actual two-item manual review

After an authorized run, compare its saved Q124840826 response with all five table roles. Select a second saved item with an actual structural contrast. Titles or matching confidence alone do not show contrast. Use the source pointers, revisions, table keys/orders, group contents/attachments, date precision, and exact media filename/derived URL described in plan.md. If no existing item provides a contrast, leave this check unfinished and discuss a concrete choice before expanding the sample.

Keep the human review record under `review/sample-backup-<run_id>-manual.md`. A local JSON companion supplies the auditor's evidence. The companion contains:

- `reviewer`: actual reviewer name; `reviewed_at`: actual ISO date or timestamp.
- `status`: `passed`, `failed`, or `not_checked`; `findings`: list of concrete unresolved findings, empty only when none remain.
- `contrast`: actual reason the selected saved structures contrast.
- `items`: exactly two distinct selections, each with `qid`, `lastrevid` (preserve its JSON numeric type), `source_sha256`, and `comparisons`.
- `comparisons`: five nonempty strings keyed `items`, `statements`, `qualifiers`, `references`, `statement_references`. Record concrete source pointers, table keys/positions, comparisons, and findings; these are review observations, not generic assurances.

Use actual saved-byte checksums and revisions, not the historical regression's metadata. Provide the completed local companion explicitly:

```bash
python3 scripts/export_sample_backup.py verify backup/ACTUAL_RUN_ID --manual-review review/ACTUAL_MANUAL_RECORD.json --write
```

The auditor verifies both saved identities/revisions/checksums, five comparison roles, and that their structural inventories actually differ. It records the review evidence in manual-review details. This does not independently prove a human performed the review; that responsibility remains with the named reviewer. Missing evidence/contrast stays not_checked; recorded unresolved preservation findings fail. Fixture evidence must never be supplied as an actual sample review.

## Failure and recovery

Retain each attempt, including failed and unfinished attempts. A user-chosen retry uses a new folder and its actual explicit scope. Do not combine successful responses from separate attempts into a fictitious passed run.

On interruption, completed originals remain, unattempted requests remain pending, and validation remains unfinished unless a known failure makes the overall result failed. A hard crash can leave the last valid manifest and staging files. Start recovery with read-only verification; it reports unexplained/staging/orphan files and missing expected files. Verification does not promote staging data, resume collection, follow external links, or repair source files.

Unexpected structures retain raw originals and representable rows and fail the affected completeness category with a source path and reason. Compact complete JSON is the approved fallback for values outside reviewed renderers; this alone is not a failure. A concrete representation/schema change still needs review and a new schema version when the format changes.

## Review and remaining limits

The four separate milestone reviews and final integrated review are recorded in `review/sample-backup-implementation-2026-10-20.md`. Passing offline tests establishes the tested implementation behavior, not sample completion. Transport tests used doubles/spawned synthetic workers, not a live endpoint. The actual current sample, contrasting-item review, full IDEA coverage/readability, and Dataverse ingestion/download checks remain unperformed.
