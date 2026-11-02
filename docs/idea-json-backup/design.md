# IDEA JSON backup: specification

Drafted: 2026-10-28. **Approved by Danu: 2026-10-28**, with an explicit request to prepare the implementation Plan. This approval does not authorize a pilot, collection or deposit.
Format identity: `idea-json-backup`, version `1.0.0`, distinct from the historical sample CSV format. Proposal wording retained in the body describes the approved design; explicitly deferred empirical format/retention checks remain pending.
Basis: [brief.md](brief.md) and [research.md](research.md).

## 1. Goal and confirmed scope

Make one preservation export before LUX edits and deliver it as downloadable archives in Yale Dataverse. Approximately 33,000 items is the expected scale, not a required result count.

An item qualifies if it has at least one normal or preferred P5008 = Q114241199 statement. Deprecated-only IDEA tags do not qualify. Freeze the selected QID list before collection. Account for each selected QID without silently adding/removing items later. Preserve each selected item's complete returned JSON, including all languages, ranks, qualifiers, references and unknown fields. The membership filter does not filter the contents of an accepted item.

Current revisions may be collected over a documented period. Record each accepted revision and retrieval time plus overall start/finish times. Do not describe the result as one synchronized historical instant.

**Proposed scope boundary for approval:** current structured item records only. URLs, linked identifiers and media filenames remain in the JSON; media bytes, recursive linked-item retrieval, full revision history and LUX/Wikidata edits are outside this export. The five CSV tables and their manual-comparison procedure are not required.

## 2. Discovery and frozen selection

Use the explicit statement/rank query recorded in Research. Cover both the main and scholarly query graphs and deduplicate the union. Preserve the query, exact endpoints, complete raw results, actual UTC discovery start/finish times and checksums. A failed, truncated or invalid discovery result prevents freezing the selection and starting collection. Zero results must be reviewed rather than accepted as a complete empty backup.

Create an immutable, canonical QID list: valid distinct item QIDs, one per UTF-8 line, sorted numerically by QID number. Keep the raw discovery results as separate evidence. Record the list's count, size and SHA-256. Its checksum identifies this run's population; do not use the approximate 33,000 estimate as a pass criterion.

A saved response that has lost its qualifying tag since discovery stays in the frozen scope. Preserve it and report the membership difference. This difference alone does not mean its JSON was lost. Do not claim to discover every membership change after selection; an additional end-of-run query is not required for the initial export.

## 3. Proposed collection route and pilot condition

**Proposed route:** sequential, small-batch Wikibase Action API collection, using `wbgetentities`. Preserve each complete response and extract per-item JSON from it. This is a proposed design choice, not an already authorized or tested bulk run.

Candidate request contract:

```text
action=wbgetentities
ids=<at most 50 frozen QIDs, separated by |>
format=json
formatversion=2
redirects=no
maxlag=5
```

Omit language, site and property filters: do not request a subset of claims, languages or sitelinks, or synthesize fallback-language terms. Use the documented default entity attributes; do not send an invented `props=all` value. Record the exact endpoint, parameters, relevant headers and software/runtime versions used. Supply genuine operator/project identification, not an invented contact.

Allow only one request in flight, with at least one second between requests and a 60-second overall response deadline per attempt. HTTP compression may be used, but record the content encoding and decoding performed. Preserve the exact JSON-body bytes after HTTP content decoding, not a claim to preserve compressed wire traffic.

Official guidance cautions against large-volume use of both EntityData and the Action API. A separately requested pilot must check response structure, completeness, service behavior, size/timing, recovery and packaging before full collection is considered. Technical pilot success is not an official endorsement of bulk use. Recheck current access guidance before execution; if this route is unsuitable, revise the specification rather than automatically switching to a dump or increasing concurrency.

## 4. Source preservation and per-item acceptance

Retain the complete response-body bytes and request/response metadata before accepting any contained item. Keep every attempt's received failure/partial body when present, with complete/partial/unknown status. Never label a truncated body complete.

If HTTP content decoding fails, preserve the received encoded bytes as diagnostic evidence with their encoding and honest completeness status. Do not describe them as decoded JSON or accept items from an incomplete decode.

Per-item files contain the whole returned entity object, not a five-table reconstruction. Preserve exact strings, number tokens, JSON types, arrays and duplicate occurrences. Do not round values or discard unknown fields. JSON object-key serialization order and formatting may differ; the original response preserves the source serialization. Label these files **extracted item JSON**, not original HTTP response bodies.

Do not match entities by array/request position. For an ordinary accepted item, require a complete usable response, the expected entity-map key, matching inner QID, `type=item`, no missing/redirect/error indication, usable revision metadata, and an unambiguous provenance link to its response. Batch-level success does not prove all requested items exist. An omitted QID, unexpected entity, warning or malformed response must have an explicit finding and disposition.

With redirects disabled, missing responses can mean missing **or redirected**, so report `missing_or_redirect` until investigated. Preserve the evidence and hold the item unresolved. Never silently substitute a redirect target, rename an item by returned ID, merge requests or omit a frozen QID.

An item becomes accepted only after its body, extracted file, checksums, provenance and durable checkpoint are consistent. Once accepted, keep that revision immutable within the run.

## 5. Failure, retry and resume policy

- Retry temporary transport failures, timeouts, HTTP 429/500/502/503/504 and API maxlag errors, with at most **three attempts per unresolved item in the run**, counted across resume. Retain every attempt. Missing/redirect, identity and malformed-data exceptions need review rather than automatic repeated requests.
- Honor Retry-After. Otherwise wait at least five seconds before the second attempt and ten before the third. Longer service-directed waits take precedence. Detect API errors even when HTTP status is 200.
- Stop collection if saving/checkpointing is unsafe. Graceful interruption preserves accepted work and leaves unfinished work identifiable. Resume must use the same run and unchanged frozen-list checksum.
- Before reuse on resume, check previously accepted files against their recorded hashes/provenance. Corruption is a failure, not permission to overwrite or silently retrieve a later revision. Retry only unresolved eligible work; do not reset attempt limits on restart.
- Keep inventory updates incremental during collection. Do not reread every earlier file after every request. A separate final verification pass must reread every accepted file.

An earlier failed attempt does not permanently fail an item if a permitted later attempt succeeds. Unresolved item, saving, identity or integrity failures prevent a complete-collection claim. Preserve and describe partial results honestly.

## 6. Required local records

Suggested run layout under the existing ignored backup/ directory:

```text
backup/idea-json/<run_id>/
  selection/             query, raw results, discovery metadata, frozen qids.txt
  responses/             unchanged response-body bytes, including diagnostics
  items/<QID>.json       complete extracted item objects
  manifest.json          run identity, method, timing, counts, limits and status
  inventory.jsonl        one entry for every frozen QID
  attempts.jsonl         durable request/outcome/provenance records
  verification.json      independent collection-check results
  README.md              scope, method, contents, limitations and recovery notes
```

The manifest identifies the format/version, run ID, selection checksum/count, actual times, exact request settings, exporter/runtime versions, record paths and outcomes. Unknown times remain null; a finish time does not imply successful validation.

Each item inventory entry associates its requested QID, returned QID or null, status (`pending`, `accepted`, `unresolved`), accepted revision/modified/retrieval times, item path/size/SHA-256, source-response ID/entity key, attempt IDs, membership-at-retrieval result and any unresolved error. Keep unavailable fields null and preserve JSON integer revision types.

Attempt records identify requested QIDs, request settings, actual start/finish times, HTTP/API outcome and received headers needed for decoding/backoff, response path/size/hash/completeness, and item-level results/errors. Record exceptions separately from successful items in a mixed-result batch. Do not store credentials or authentication tokens in public records.

Implementation may use internal checkpoints/journals for recovery, but the final inventory must reconcile to every frozen QID. Exact record schemas and recovery mechanics must be made concrete in the reviewed implementation plan before code is written; do not claim the old manifest implements this contract.

## 7. Independent collection verification

A verifier, independent of the extraction path, must read saved source bodies, extracted files, selection and inventory and establish:

1. Every frozen QID has exactly one accepted, usable, matching item; no unexplained duplicates, substitutions or extra item files exist.
2. Each complete extracted object equals its entity object in the preserved response, ignoring only object-key order/formatting. Exact strings, number tokens, array order, multiplicity, unknown fields and absent/empty distinctions survive.
3. Revisions, identities, provenance, sizes, checksums, item statuses and membership findings agree with the saved evidence.
4. Every required file exists, parses where appropriate and stays within the run; no unexplained partial/staging files remain in a finalized collection.

Verification must not refresh the inventory to conceal changes. Deliberate corruptions in offline tests must be detected even after someone recomputes a damaged item's checksum. Those tests and scale/recovery tests belong in the implementation plan; no new implementation test result is claimed here.

Report collection status as `not_checked`, `failed` or `passed`, with known failures dominant. Only all required checks passing with every frozen QID accepted permits **collection complete**. Later membership differences remain visible but do not change the list.

## 8. Archives and Dataverse delivery

Confirmed delivery is archive downloads containing per-item JSONs. Preserve source responses, discovery evidence, inventory and documentation as well as item files; these may occupy separate archive parts. Each payload file must occur exactly once in its designated archive set, with relative paths and bytes preserved.

**Proposed archive format:** bounded `.tar.gz` parts, subject to Yale retaining/downloading them unchanged. ZIP is an alternative only if the agreed upload method retains the archives. Format, compression reproducibility settings and part limits must be finalized after a separately requested draft test; do not rely on ZIP defaults that unpack into thousands of repository files.

Build parts from a verified, finalized collection. Before archiving, create an external package inventory recording **every finalized payload file's relative path, byte size and SHA-256**, including item JSONs, source responses, selection evidence, manifest, attempt records, verification report and README. This is separate from the one-entry-per-QID inventory. Associate each payload path with exactly one archive part, and record every archive's filename, size, SHA-256 and complete member list. The external package inventory and later package/deposit verification records are not payload members; do not attempt to hash an inventory inside itself or put an archive's own checksum inside itself. Reporting must not modify the finalized payload.

Before deposit, extract every part into an empty local directory. Reject unsafe/duplicate paths. The extracted path set must equal the entire external payload inventory exactly, with every size and checksum matching; checking only item JSONs is insufficient. Retain a local verified copy.

For the actual Yale dataset, record collection/dataset identity, version and uploaded archive identifiers. Deposit the external package inventory alongside the archive parts. Download **all** archive parts and that inventory after upload; first compare the downloaded inventory with the local finalized copy, then compare archive hashes, extract every part and repeat the exact all-payload inventory comparison above. A visible filename, successful upload response or spot-check alone does not establish **deposit verified**.

Keep separate outcomes: **collection complete**, **deposit verified**, and **published**. Upload/deposit testing and publication require the corresponding explicit execution request. Publishing is not implied by Spec approval or by verified collection. Required dataset metadata and depositor access must be established before upload; no account access, dataset or deposit is claimed now.

## 9. Review boundary and next stage

On 2026-10-28 Danu approved this specification, including the pilot-gated API route, current-data boundary, source/extracted-file contract, finite retry/resume policy and archive verification requirements, and requested Plan preparation. Deferred empirical checks are not waived. No code, tests, discovery query, pilot, collection or upload has been run for this new workstream.

The [implementation Plan](plan.md) and [record layouts](record-layouts.md) translate the approved requirements into the production roadmap. Danu subsequently approved that roadmap with an [MVP-first direction](mvp.md). The first prototype is explicitly separate from full production-format/completion claims; final Spec requirements remain unchanged. Use small TDD increments, separate milestone reviews, final integrated review and distinct later pilot/production/deposit steps. Do not treat specification approval as a live execution request.

Separate assistant review passes checked scope/recovery/verification coherence and the proposed API contract. The all-payload inventory and decoding-failure clarifications were incorporated; this is not human approval or a live test. See [review record](../../review/idea-json-backup-spec-review-2026-10-28.md).
