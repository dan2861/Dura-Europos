# IDEA JSON backup: implementation plan

Drafted: 2026-10-28. **Approved by Danu on 2026-10-28, with the direction to start with an MVP.** Danu selected guided execution: Danu edits code/tests and runs commands, with the assistant explaining each TDD increment.
Authority: [Spec](design.md), explicitly approved by Danu on 2026-10-28.
Companion: [record layouts](record-layouts.md), part of this Plan's review.

**Current delivery order:** implement and review the [small MVP](mvp.md) first. The detailed modules/schemas/milestones below are the production roadmap, not a request to build every component before showing a working result. The MVP preserves the core source/item correctness rules but is explicitly a prototype; full discovery, SQLite recovery, large-scale collection and deposit features follow in later increments. Its first preservation test supersedes the original full-discovery-first order below. Danu performs the application/test edits and commands with step-by-step guidance; roadmap approval does not authorize live execution.

## 1. Outcome and execution boundary

Implement a resumable JSON-only collector, an independent offline verifier, archive packaging and offline verification of downloaded deposit files. Preserve the frozen population, original response evidence and complete extracted item objects. Keep the historical sample exporter and its format intact.

Danu approved the roadmap, requested MVP-first delivery and selected guided execution. At Danu’s explicit request on 2026-11-02, the assistant added the first MVP stub/test and observed one expected offline failure (“Original response must be saved”). At Danu’s subsequent explicit request, the assistant applied the minimal implementation and observed one passing focused offline test. Identity validation subsequently passed and was committed as `0aef380`; at Danu’s explicit request, the next omitted-entity increment was completed RED–GREEN (three focused tests pass). Unavailable-entity stubs are next; no discovery, pilot, full collection, upload or publication has started. The command names below are planned interfaces, not existing commands or actions performed. Let the user (Danu) execute operational commands unless explicitly requesting execution.

Remain in the existing repository. Use new code/tests/task documents; do not move old evidence, change .gitignore, stage, commit or push as part of Plan preparation. The existing .gitignore/cache modifications are pre-existing work, not this Plan's output.

## 2. Runtime and code boundaries

Observed during planning: Python 3.12.0 and SQLite 3.43.2. Proposed runtime is Python 3.12 with standard-library sqlite3, urllib/http.client, multiprocessing, gzip, tarfile, hashlib, pathlib and unittest; no dependency installation is needed. Record actual versions in future runs.

| Proposed file/module | Responsibility |
| --- | --- |
| `scripts/export_idea_json.py` | Explicit CLI actions; construct a live client only in network handlers |
| `scripts/idea_json_backup/contract.py` | Versions, record validators, settings and state enumerations from this Plan |
| `selection.py` | Saved query, raw discovery evidence, canonical union and membership evaluation |
| `codec.py` | Thin adapter to the existing strict numeric-token JSON codec; no CSV projection |
| `files.py` | Safe relative paths, fsync, atomic replacement of projections and no-clobber immutable payload publication |
| `state.py` | Internal SQLite progress/attempt journal and public snapshot generation |
| `client.py` | Generic supervised GET, body capture, decoding and timing; no entity acceptance logic |
| `collector.py` | Batch scheduler, response classification, extraction, durable acceptance and recovery |
| `verify.py` | Independent scope/source/item/record audit; never call extraction or consult SQLite for expected values |
| `package.py` | Final payload inventory, bounded archives and exact local extraction verification |
| `deposit.py` | Offline comparison of supplied downloads and recorded acquisition evidence |
| `tests/test_idea_json_*.py` | Focused offline tests, failure injection and synthetic scale exercise |
| `tests/fixtures/idea-json-backup/README.md` | Provenance and intended meanings of invented fixtures |
| `docs/idea-json-backup/runbook.md` | Future actual interfaces, status meanings, recovery and operational prerequisites |

Reuse the existing codec only behind explicit new contract tests. Use the old storage/transport code as reviewed reference; do not import RunStore or the sample collector/validator, which require the five CSVs and sample-only statuses. A JSON-only verifier may share strict parsing primitives, but must independently traverse the preserved entity and compare every field/type/value.

## 3. Commands and effects

| Proposed action | Effect and prerequisite |
| --- | --- |
| `discover --output NEW_SELECTION` | Network: query both graphs, preserve attempts/results, freeze only a valid nonempty union |
| `pilot-selection --parent SELECTION --qids EXPLICIT_LIST --output NEW_SELECTION` | Offline: create an explicitly labeled subset bundle retaining the complete production-parent evidence |
| `collect --selection SELECTION --run NEW_RUN --kind production` | Network: initialize a new run from the frozen full selection and collect it |
| `resume --run RUN` | Network only after recovery checks: reuse accepted revisions and request eligible unresolved items |
| `status --run RUN` | Offline, read-only: report journal/projection state and remaining work |
| `verify --run RUN [--write] [--report EXTERNAL_PATH]` | Offline, read-only by default; --write coordinates finalization of a collected run without refreshing source/item hashes; finalized payload is never rewritten |
| `package --run RUN --output NEW_PACKAGE --profile PROFILE` | Offline: require a finalized verified collection and produce/verify archives plus external inventory |
| `verify-deposit --package PACKAGE --downloads DOWNLOADS --acquisition RECEIPT [--report PATH]` | Offline: compare all downloaded files with the local package and record the supplied dataset/version/download provenance |

Imports, help and offline actions must not initialize a live transport or fetch remote metadata. No action automatically starts the next phase. Initial access is unauthenticated; credentials are not needed or retained. The later runbook supplies concrete commands only after implementation is verified.

Exit outcomes: 0 means the requested action passed its own checks; 1 means a known failure; 2 means required work is unfinished. Discover success is not collection completion, and package success is not deposit/publication success. Argparse usage errors also use 2 with usage/error text. Pilot and synthetic runs are labeled explicitly and can never be reported as the full IDEA export.

collect also accepts --kind pilot only with a verified pilot-selection bundle. pilot-selection must prove its requested IDs form exactly the declared nonempty subset of a complete production parent with the same criterion; copy that parent's query, raw graph evidence and full frozen list under selection/parent/. It cannot create an all-item claim from an arbitrary handwritten list. Synthetic fixtures are explicitly labeled and use injected transports.

## 4. Discovery and network contract

Use the approved explicit-rank query from Research at `https://query.wikidata.org/sparql` and `https://query-scholarly.wikidata.org/sparql`, sequentially, with no LIMIT or label service. Preserve raw results before deriving IDs. Validate HTTP completeness and SPARQL result structure: item URI bindings, valid canonical QIDs, no error/truncation. An empty scholarly result is valid; an empty combined union needs review. Preserve duplicates in raw evidence and deduplicate only the final union. Sort QIDs by their numeric suffix and write UTF-8/LF with a final newline. Copy the entire frozen selection bundle into each new run and verify its hashes.

Discovery uses at most three attempts per graph with recorded attempts, the same transient HTTP/transport backoff rules below, and no item-request quota consumption. A failed graph prevents freeze/collect. A partial discovery remains evidence rather than a collection input. A new discovery attempt uses a new selection directory, not silent replacement of a prior frozen list.

Pin the Action endpoint to `https://www.wikidata.org/w/api.php`. Use the exact approved wbgetentities parameters, at most 50 currently eligible QIDs in frozen-list order. Omit props/languages/sitefilter/languagefallback/sites/titles/normalize. Set JSON Accept for Action API and SPARQL-results JSON Accept for discovery. Use `Accept-Encoding: gzip, identity`; support identity/gzip only. Supply a genuine versioned User-Agent, initially `IDEA-JSON-Backup/0.1.0 (https://github.com/dan2861/Dura-Europos)` or an explicitly supplied genuine operator identifier, and record the actual value. Do not automatically follow unexpected HTTP redirects; retain status/Location and report the exception.

Define the one-second gap as completion of one attempt to dispatch of the next, including discovery. Enforce the 60-second total response deadline with a monotonic clock and a supervised worker; do not restart a socket timeout after each chunk. The worker streams encoded bytes to a unique spool and records receipt metadata. Validate clean framing/EOF, then decode gzip through its trailer to a separate spool. Keep both encoded and decoded evidence for compressed responses; for identity, both descriptors can reference the same unchanged file. On decode failure retain encoded bytes. A complete JSON prefix is insufficient proof of a complete response.

Classify saving/checkpoint failures first and stop. Known transport timeout/framing interruption and the approved transient HTTP/API classes are retryable even when their diagnostic body is not JSON. A complete HTTP 200 usable Action response must have the expected wrapper, a JSON-integer success=1 (not bool/string), and entity mapping. Other complete malformed/undecodable responses are review cases, not automatic retries. Top-level API warnings, unexpected entity keys, malformed wrappers or batch API errors other than maxlag hold the whole batch with findings. In a clean mixed batch, accept independently valid requested entities while preserving each neighbor's unresolved result.

Require matching map key and inner ID, type=item, no missing/redirect/error marker, positive JSON-integer lastrevid (not bool/string/fraction), and a valid UTC modified timestamp. Keep unknown fields. Evaluate membership independently from identity: a tag lost after selection is a recorded difference, not a reason to omit the item. Missing stubs are `missing_or_redirect`, not proof of deletion.

Retry only transport failures/timeouts, 429/500/502/503/504 and API maxlag. Reserve an attempt against each included QID before dispatch; at most three reservations per QID across resume. Wait at least max(one-second pacing, five/ten-second retry floor, valid Retry-After delay). Parse Retry-After as delta-seconds or HTTP-date; preserve malformed values as findings and use the ordinary floor. Persist per-item next eligibility and a collector-wide next-dispatch lower bound in UTC; do not evade a server wait by dispatching fresh QIDs instead. Retain monotonic waits during a live process. Never shorten a valid server wait; interruption checkpoints unfinished work instead.

Capture allowed response headers and their actual receipt time durably in an attempt-specific .state/ receipt before consuming the body; also record whether any headers were observed, clean response_received_at, receipt completeness, and monotonic response elapsed milliseconds. Apply/recover the most restrictive server wait from that receipt even if body/outcome completion was not committed. If dispatch may have happened but header receipt evidence was lost/uncertain, hold server_wait_unknown for review instead of assuming there was no Retry-After. A recorded known pre-header transport failure can follow ordinary retry rules. No new dispatch occurs before receipt/wait recovery. These rules cannot reconstruct bytes or headers never durably saved.

## 5. Durable progress and crash recovery

Use `.state/state.sqlite` as the authoritative internal journal while collection is active; public JSONL records are consistent derived snapshots. Use one collector lock via flock, explicit short SQLite transactions, foreign keys, journal_mode=DELETE and synchronous=EXTRA, verifying the settings by reading them back. On macOS enable/read back fullfsync where supported. SQLite EXTRA adds directory syncing for DELETE-mode commits; filesystem durability still depends on the underlying OS/storage. [SQLite settings](https://www.sqlite.org/pragma.html#pragma_synchronous), [Python transaction control](https://docs.python.org/3.12/library/sqlite3.html#transaction-control).

Tables: run (identity/settings/phase/sequence), items (QID/ordinal/state/acceptance record/next eligibility), attempts (unique attempt ID and record), attempt_items (attempt/QID links and results). Use foreign keys and unique constraints; index item state/ordinal and attempt_items.QID. Count persistent attempt links for the limit. Store revision metadata and public records as precision-preserving JSON text rather than SQLite numeric coercions. No network call occurs inside a database transaction.

Order each attempt:

1. Validate eligible QIDs; transactionally reserve unique attempt ID and all attempt/QID links, then commit.
2. Dispatch/capture under that ID. Publish evidence using no-clobber writes and fsync file/parent directory, then commit body descriptors and completion/classification. A body is not complete merely because it parses.
3. Extract from a durably recorded complete usable source. Publish each full item file without replacement. Compare an already existing unaccepted file to that same source; do not overwrite mismatches.
4. Transactionally accept only consistent items and their hashes/provenance. Update affected rows/sequence and small run counts; prior accepted revisions remain immutable.

| Interruption point | Required recovery |
| --- | --- |
| Reservation committed; send/result uncertain | Keep an interrupted/unknown outcome and consumed quota; retain any captured bytes |
| Body exists without committed completion evidence | Preserve/account as diagnostic with incomplete/unknown status; do not promote by parsing alone |
| Complete response committed; extraction unfinished | Finish locally from that same source before considering another request |
| Item published; acceptance not committed | Compare with committed source; accept an exact match or fail without replacing it |
| Acceptance committed | Verify item/source hashes and provenance once before reuse; corruption stops collection |
| Journal missing/corrupt or selection/settings changed | Stop and report; do not rebuild quota from stale JSONL, silently reset counters or change scope |

Identify every staging artifact by attempt ID. Recovery retains it or registers/moves its bytes into diagnostic evidence; no unexplained staging file may disappear or enter the final payload. Missing or corrupt state needs a concrete recovery review, not automatic refetch.

Generate public inventory/attempt JSONL snapshots on initialization, orderly pause, explicit finalization and recovery completion, not after each item. From one database snapshot, atomically replace the two records, then publish manifest last with their generation/hashes. A crash between replacements leaves detectably stale projections; after integrity checks, resume can regenerate only these derived views without refreshing accepted artifact hashes. status reads the journal; verify reports stale views as unfinished and does not repair them.

Before independent verification, stop collection and finish public snapshots. The independent verifier works entirely from public records and payload; the CLI coordination layer alone opens the journal for finalization. .state/lock/journal files are explicitly documented local recovery artifacts excluded from deposit. A finalized collection cannot resume fetching later revisions.

**Finalization is performed only by verify --write.** Hold the writer lock, require phase=collected and consistent public views, and run the independent audit without using SQLite as expected evidence. Prepare the exact report and resulting manifest bytes under .state/ and durably journal an intent containing their hashes plus selection/public-record input descriptors. Publish report first and manifest last, fsync, then commit the journal phase (finalized only on passed; otherwise collected with the failed/unfinished outcome) and clear the intent. Phase/report bookkeeping does not advance the item/attempt content sequence, so unchanged public records remain current. No payload file can be edited by a collector during this sequence.

After a crash in finalization, recovery must verify that the intended inputs remain unchanged and complete only the exact prepared publication, or stop on disagreement; it must not rerun network requests or regenerate different accepted evidence. If report/manifest were already published, reconcile only the journal when their bytes match. Once finalized, reject verify --write, snapshot regeneration and all other payload mutations. Later audits print results or write an explicitly external report. Packaging holds the same lock and requires finalized public bytes. The verifier's own report/manifest are finalized before the external package inventory hashes them, avoiding a checksum cycle.

## 6. Verification and packaging design

The independent verifier checks the approved four collection categories using public evidence. It must not call extraction, trust prior passed flags, query Wikidata, or regenerate hashes into the inventory. Index only metadata; process one source batch and its associated items at a time, comparing complete types/tokens/arrays/maps. Parse every diagnostic's metadata while allowing non-JSON diagnostic bytes. Detect unexplained files, path escapes, duplicate records, absent files and changed selection/settings. Persist verification only with --write; report inputs by selection/projection hashes without creating self-referential report/manifest checksums. Finalize manifest/report before package inventory creation.

Candidate archive profile for offline tests: tar.gz, at most 5,000 regular-file members or 256 MiB summed payload bytes per part, whichever comes first; gzip level 6, gzip mtime=0/empty stored filename, stable path order and normalized tar header ownership/mode/time. Preserve payload bytes. A single oversized payload causes a reported packaging hold rather than splitting an item file or silently exceeding limits. These are **provisional test settings**, not empirically approved Yale limits. Final profile records the actual separately tested format/limits/retention evidence; a failed retention test requires an explicit profile/spec review before deposit.

Make a separate new package directory, outside the collection payload. Enumerate every finalized required payload file; exclude only documented .state/lock and external package/deposit records. Generate the all-payload external inventory before archiving and stream each file into exactly one part while verifying its recorded size/hash. Do not archive an output directory into itself. Keep both item and non-item evidence covered.

Safe extraction creates regular files in an empty temporary directory after validating expected POSIX paths and sizes. Reject absolute/parent/ambiguous paths, symbolic/hard links, devices, duplicate members within/across parts, missing/extra paths and invalid/truncated archives. Compare the exact full path set, every size and SHA-256. Use the same independent package check for local extraction and downloaded parts; do not trust tarfile.extractall on an unvalidated archive.

verify-deposit never downloads or fills missing files. Require all parts and the downloaded external inventory, first matching the inventory's bytes to the local finalized copy, then archive hashes and all extracted payloads. A separate operator-recorded acquisition receipt identifies actual Yale dataset/version/file URLs/IDs/download times. Without complete acquisition evidence, report only local-byte equivalence, not deposit verified. State that receipt provenance is operator-recorded, not independently fetched by the offline checker. Publication is a separate record/action.

## 7. TDD increments and separate reviews

For each new behavior: explain its expected result, write one focused test, observe its expected failure, implement the smallest behavior, refactor with relevant tests green. If reused behavior already passes, label the added test regression coverage; do not manufacture a failure. Use temporary directories, invented protocol responses, injected transports/clocks and synthetic workers. Ordinary tests deny external network access. A local loopback server may test actual HTTP framing/gzip/deadline behavior using invented bodies only.

**First full-discovery increment, after the MVP:** saved synthetic main results contain Q10/Q2 and scholarly results contain Q2/Q1. Freezing must preserve both source bodies and produce exactly `Q1\nQ2\nQ10\n`, count 3 and its SHA-256. The expected numeric union comes from Spec section 2, independently of the extractor/query's lexical ORDER BY. Proposed test: `test_freezes_numeric_union_and_retains_sources` in `tests/test_idea_json_selection.py`. Focused command when that increment is requested: `python3 -B -m unittest discover -s tests -p 'test_idea_json_selection.py' -v`. No such test has been written or run yet. The actual first implementation behavior/test is now the preservation slice in [mvp.md](mvp.md).

| Milestone | Small increments and meaningful checks | Separate review focus |
| --- | --- | --- |
| 1. Selection and contract | First test above; invalid/truncated/failed graph, zero combined results, immutable list, settings/schema validation. Review query's explicit ranks; local membership truth table includes normal IDEA plus preferred other project and deprecated-only IDEA. Static query review is not a live SPARQL correctness/completeness test. | Approved scope, both graphs, exact evidence, versioned record contract and no implicit network |
| 2. Store and lossless extraction | Durable no-clobber writes, SQLite attempt reservation, complete sources before items, source/key/ID checks, unknown nested fields, all languages, punctuation/leading-zero strings, huge numeric tokens, empty/absent/null, arrays/duplicates and missing stubs. Read the saved real sample unchanged as additional regression evidence. | Source versus extracted distinction, type/precision preservation, acceptance commit order |
| 3. Transport, retry and recovery | Shuffled/mixed batches; API error at HTTP 200; noninteger/missing success marker; warning/extra-key holds; encoded/decoded/partial evidence; clean zero-byte receipt; real loopback framing/gzip and supervised timeout; fake-clock pacing/Retry-After, including crash before outcome commit and fresh-QID cooldown evasion; three attempts across restart. Inject crashes/disk failures at every boundary in section 5. | Actual request contract, bounded timing, retry classification, quota/wait durability and accepted revision immutability |
| 4. Independent verification | Mutate a value/type/array/unknown field/number lexeme and recompute item hash: source comparison must still fail. Wrong source/revision, duplicate/missing/extra item, changed selection, unsafe path, stale projection, corrupted source and diagnostic metadata. Crash each finalization boundary; later verify --write must leave finalized payload untouched. Object-key order alone passes; membership drift stays visible without dropping IDs. | Independence from extraction/SQLite, exact reconciliation, finalization immutability and truthful failed/unfinished precedence |
| 5. Scale and archives | Synthetic 33,000-item exercise; instrument payload reads/hashes and public-view writes to detect repeated whole-run work. Stream all-payload inventories; split at test limits; exercise unsafe/duplicate/link/extra/missing paths and damaged archives, including lost README/source/discovery evidence. | Bounded passes rather than a brittle elapsed-time target; complete archive coverage and stable finalized bytes |
| 6. Integrated CLI and deposit verification | Help/import/offline network guard; full invented discovery→mixed collection→interrupt/resume→verify→package→simulated download; exhausted item prevents complete; changed downloaded inventory/part/payload fails. Run historical sample regression suite once because shared codec reuse must not break it. | Combined behavior, runbook and all separate outcomes; no automatic pilot/collection/upload/publication |

At each milestone, perform a distinct review pass after tests, record findings/dispositions and rerun affected checks only. After all six, perform a final integrated review across code, tests, schemas, failure paths and runbook. AI review findings require verification and are not evidence of a live successful export.

The scale exercise uses tiny invented objects, actual journal/file interfaces and counters, not 33,000 network requests. During uninterrupted collection, previously accepted payloads must not be rehashed per new request; full public views are written only at documented checkpoints. Resume/final verification may make bounded passes. This establishes algorithmic behavior, not real population representativeness, runtime or upload performance.

Use focused tests per increment and a coherent checkpoint suite per review. Intended final new-suite command: `python3 -B -m unittest discover -s tests -p 'test_idea_json_*.py' -v`; final shared-code regression: `python3 -B -m unittest discover -s tests -p 'test_sample_backup_*.py' -v`. Record actual results later, with no predetermined test count. No tests were executed to prepare this Plan.

## 8. Later operational stages and completion

The MVP is delivered/reviewed first under [mvp.md](mvp.md). Any actual MVP pilot still requires a separate request and prior review of the one-request transport/preservation checks; it is not production readiness. For the complete system, after requested implementation and passing production offline/final reviews:

1. Separately request discovery and an explicit pilot subset. Preserve a parent frozen-list checksum and mark the subset/run as pilot; its success is not full-population completion. Use actual saved outcomes to review defaults, latency/size, completeness, membership drift and recovery. Do not expand or relabel the pilot silently.
2. Separately request a Yale draft retention test of candidate archive parts. Confirm actual destination/access, metadata, downloadable retention, limits and all-byte roundtrip. Finalize the profile only from observed results. No colleague/admin contact is implicit.
3. Separately request full production discovery/collection, preserving the exact approved population and collection period. A new selection needs a new run. A pilot is never merged into a fictitious completed production run.
4. Independently verify all items/evidence and package the finalized collection. Retain partial/failed runs separately and report unresolved failures concretely.
5. On the corresponding requested deposit, upload the parts/inventory, download all of them and perform the offline deposit check with actual acquisition metadata. Keep the local verified copy.
6. Publish only when requested; record the actual published dataset/version and date. Verify/read back relevant public identifiers under that request.

Deliver implementation evidence in `review/idea-json-backup-implementation-<date>.md`, an actual runbook, passing offline tests, six milestone reviews and a final integrated review. Update SUMMARY only to observed stages. Distinguish implementation complete, collection complete, deposit verified and published. This Plan does not claim any of them achieved.

Separate assistant review passes checked recovery/finalization, request/record contracts and TDD/verification coverage. The resulting clarifications are incorporated; [review record](../../review/idea-json-backup-plan-review-2026-10-28.md). Danu subsequently approved the roadmap with an MVP-first direction; neither those reviews nor approval are implementation evidence.
