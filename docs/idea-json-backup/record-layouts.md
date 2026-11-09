# IDEA JSON backup: planned record layouts

Date: 2026-10-28. Companion to the [Plan](plan.md), approved by Danu as the production roadmap with an [MVP-first delivery direction](mvp.md). Status 2026-11-08: selection, manifest, item/attempt records, collection verification, candidate packages and offline acquisition/deposit verification are implemented. Actual Dataverse transfer remains unperformed. These production schemas are distinct from the separately labeled first prototype; the public record keys below are unchanged.

## Common rules

Approved redirect-release addendum2026-11-08: the original collection format/rows remain1.0.0 and unchanged. A distinct self-contained release implements the approved operator-recorded redirect exception. Its records below do not mark a missing stub as an accepted item.

### Redirect release records

The pure release_contract module validates exact keys, canonical distinct QIDs, unique origins/no chains, strict integer tokens, safe descriptors, UTC/null observation times and exact canonical origin page URLs. Cross-binding to actual files/source/accepted targets belongs to the independent release audit.

- Request format idea-json-backup-redirect-request/version1.0.0: `{format,format_version,run_id,state_sequence,qid_list_sha256,recorded_by,redirects}`. Each request row is `{requested_qid,target_qid,unavailable_attempt_id,page_url,observed_at}`. The page URL is exactly `https://www.wikidata.org/wiki/<requested_qid>?redirect=no`.
- Resolution format idea-json-backup-redirect-resolution/version1.0.0: `{format,format_version,run_id,state_sequence,inputs,redirects}`. inputs binds `{qid_list:F,inventory:F,attempts:F}` in the unchanged collection's relative namespace. Each row is `{requested_qid,target_qid,unavailable_attempt_id,source_response:B,target_item:F,evidence}`. evidence is `{evidence_kind:operator_recorded,page_url,observed_at,recorded_at,recorded_by}`. Source body must be complete; observed_at may be null; recorded_at is actual creation time.
- Release format idea-json-backup-release/version1.0.0: `{format,format_version,release_id,run_id,run_kind,created_at,completion_basis,inputs,resolutions,strict_verification,readme,verification_path,counts,limitations}`. completion_basis is usable_items_and_reviewed_redirects. inputs binds manifest/inventory/attempts/QID-list F under collection/. The three record descriptors point to redirect-resolutions.json, strict-verification.json and README.md. verification_path is verification.json and is not self-hashed.
- Reconciled counts are `{selected,usable_items,redirected,pending,unresolved}`. Selected equals usable_items+redirected; usable/redirected are positive and pending/unresolved zero for a completed release. Original accepted/unresolved counts stay in the nested collection and strict report.
- Release verification is `{format_version,release_id,run_id,checked_at,inputs,status,checks,counts,findings}` with inputs `{release:F,resolutions:F,strict_verification:F}` and checks scope/source_content/provenance/files. The saved report binds exact release.json bytes; fresh comparisons ignore only its check time after validating that time. Publish the report before the final release marker. A pending release has no completed release claim.

See [redirect-release.md](redirect-release.md) for copy/publication, exact exception coverage and guided execution requirements. Package inventory1.1.0 identifies payload_kind resolved_release and selects the new independent release audit; legacy inventory1.0.0 remains unchanged.

Format identity/version: `idea-json-backup` / `1.0.0`; proposed new exporter version: `0.1.0`. Metadata is UTF-8 JSON with LF/final newline; JSONL has one complete object per line. No NaN/Infinity, duplicate object keys or floating-point number coercion. Public record keys below are required; unavailable values are JSON null. Internal records may add implementation fields, but public additions require explicit versioned contract review. Preserve unknown fields **inside captured entity/source content**; do not confuse them with the fixed metadata schema.

UTC generated timestamps use `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Keep entity modified strings and numeric revision tokens exactly as supplied after validation. Counts/sequences/status codes are real JSON integers, not booleans/strings; counts are nonnegative. SHA-256 values are lowercase 64-hex strings. Relative paths are safe POSIX paths beneath their declared root, with no links, absolute/parent components or ambiguous separators. File descriptor `F` means exactly `{path, size_bytes, sha256}`. Body descriptor `B` adds `complete` (true/false/null); it records one named byte layer, not a full wire capture.

All generated record objects have a fixed format_version via their containing manifest or their own wrapper. JSONL entries inherit the manifest's version and state_sequence through their descriptor; line order is defined below. Revision values are positive JSON integer tokens; SQLite stores their token-preserving representation as TEXT.

Unless a field has a different explicit shape, error means null or `{stage, code, message, retryable}`; retryable is boolean and stage is one of selection/transport/api/decoding/identity/extraction/saving/recovery. Unavailable body/time evidence stays null rather than an invented value. api_error is a separate API summary with its explicitly stated shape.

## Selection bundle

`selection.json` keys: `format`, `format_version`, `kind`, `criterion`, `query`, `discovery_settings`, `sources`, `qid_list`, `selected_count`, `frozen_at`, `parent_selection`. Its descriptors are relative to the directory containing that selection.json; copied parent metadata retains its own parent/ root. Manifest/item/attempt descriptors below are relative to the run root, and package descriptors to the package root (payload paths identify paths relative to the frozen collection).

- kind: `production`, `pilot`, or `synthetic`. Production means the full deduplicated main/scholarly union; synthetic is fixture-only and cannot be passed off as live evidence.
- criterion: `{property_id: "P5008", value_id: "Q114241199", ranks: ["normal", "preferred"]}`.
- query: F for query.rq; qid_list: F for qids.txt; selected_count must equal its distinct canonical line count. frozen_at is actual completion of freeze.
- discovery_settings: `{minimum_gap_seconds: 1, response_deadline_seconds: 60, max_attempts_per_graph: 3, retry_backoff_seconds: [5,10], supported_content_encodings: ["identity","gzip"], http_redirect_policy: "reject"}`. Actual query/format parameters and Accept/User-Agent/encoding headers are recorded on every attempt, not inferred from a later collection manifest.
- sources: two graph entries in main/scholarly order, each `{graph, endpoint, started_at, finished_at, outcome, attempts}`; graph is main/scholarly and outcome pending/succeeded/failed. Each discovery attempt records `{attempt_id, request, started_at, headers_received_at, headers_observed, response_received_at, response_elapsed_ms, receipt_complete, finished_at, status_code, headers, encoded, decoded, next_dispatch_at, outcome, error}`. request is `{method, url, parameters, headers}` with method GET. Body fields are B/null; headers use the allowlist below. outcome is succeeded/transient_failure/review_required/interrupted/saving_failure. Both sources must succeed before freeze; a graph may validly return zero items if the combined union is nonempty. Raw source files are retained unchanged. Header/wait evidence recovery uses the same rules as collection.
- parent_selection: null for production/synthetic unions. A pilot stores typed `{metadata: F, qid_list: F, selected_count}` descriptors for a complete production parent copied under parent/. Require the parent kind/criterion/full graph evidence/canonical list hashes and count to agree, every child QID to belong to that parent, and the child list to equal the explicitly requested nonempty subset. The root/pilot descriptors use parent/ prefixes; the unchanged parent selection.json resolves its own descriptors within parent/. Record the method in README; a subset is not an all-item census.

Copy and hash-check all referenced selection files into each run. Both full graph sources remain present for a pilot parent; the pilot's canonical qids.txt contains only the explicitly chosen subset.

## manifest.json

Required keys: `format`, `format_version`, `run_id`, `run_kind`, `exporter_version`, `runtime`, `selection`, `created_at`, `started_at`, `finished_at`, `request_settings`, `next_dispatch_at`, `phase`, `state_sequence`, `public_records`, `counts`, `collection_status`, `verification_path`, `limitations`.

- run_id: actual UTC creation plus unique suffix; new directory must not already exist. run_kind matches selection.kind. runtime: `{python, sqlite, platform}` using versions/OS, not a hostname.
- selection: `{metadata: F, qid_list: F, selected_count}` for the copied immutable bundle. Content and child-descriptor consistency are checked independently.
- started_at: first collection dispatch time, null before dispatch; finished_at: actual terminal collection stop, null while resumable/paused. Discovery times remain separate. Interrupted sessions are evidenced by attempts.
- request_settings: `{endpoint, action_parameters, headers, batch_size, concurrency, minimum_gap_seconds, response_deadline_seconds, max_attempts_per_item, retry_backoff_seconds, supported_content_encodings, http_redirect_policy}`. Pin approved values: batch_size50, concurrency1, gap1, deadline60, max_attempts3, backoff[5,10], encodings[identity,gzip], redirect policy reject. action_parameters contain approved fixed fields excluding the per-attempt ids; each attempt records its actual ids. Headers are actual nonsecret sent headers.
- phase: `initialized`, `collecting`, `paused`, `collected`, `finalized`. collected may still have unresolved failures; finalized requires verified complete. A finalized run cannot collect again.
- next_dispatch_at: persistent collector-wide UTC cooldown/null, enforced in addition to each item's next_eligible_at. A valid server delay also constrains requests for previously unattempted QIDs.
- state_sequence: monotonic committed item/attempt content sequence, excluding phase/report-only bookkeeping. public_records maps `inventory` and `attempts` to `{file: F, state_sequence}`. Older view sequence means stale, not silently current; stale/inconsistent views block verification until explicit pre-finalization recovery/snapshot generation. Finalized public records cannot be regenerated.
- counts: `{selected, pending, accepted, unresolved}`, summing exactly. collection_status: `not_checked`, `failed`, `passed`; derived independently, never trusted as proof. verification_path is null or verification.json. limitations is an explicit nonempty array including collection-period and excluded media/history/recursive scope.

The manifest does not hash itself or the report that updates its outcome. The later external package inventory hashes the finalized manifest/report like any payload file.

## inventory.jsonl

One row per frozen QID, in canonical qid-list order. Keys: `requested_qid`, `returned_qid`, `status`, `lastrevid`, `modified`, `retrieved_at`, `item`, `source_response_id`, `source_entity_key`, `attempt_ids`, `membership_at_retrieval`, `next_eligible_at`, `error`.

- status: `pending`, `accepted`, `unresolved`. Pending means no completed item outcome yet; an active attempt can be reported by status separately.
- item: F/null. Accepted requires a usable immutable file plus every acceptance metadata/provenance field; it is not accepted merely because a file exists. Before acceptance these fields are null unless an observed returned_qid is recorded as exception evidence.
- lastrevid/modified: actual accepted source metadata, null otherwise. retrieved_at is actual response completion time, distinct from modified and discovery.
- source_response_id: accepted attempt ID; source_entity_key: exact map key. attempt_ids: unique reservation IDs in chronological reservation order, including failed/unknown attempts, at most three.
- membership_at_retrieval: `matches`, `changed`, `not_checked`. Accepted items require the first two with evidence; a changed result stays included. New unrecognized/malformed membership structure gets a finding for review rather than a fabricated match.
- next_eligible_at: UTC or null, persistent lower bound for an eligible unresolved retry. error is null for pending/accepted and otherwise uses the common error object. Saving errors that prevent a row checkpoint remain an explicitly reported durability limitation.

Historical failures remain in attempts even when the final accepted row has error null. Count attempts from the journal links rather than trusting a mutable cached count.

## attempts.jsonl

One record per reserved collection request, ordered by reservation sequence. Keys: `attempt_id`, `requested_qids`, `reserved_at`, `dispatch_started_at`, `headers_received_at`, `headers_observed`, `response_received_at`, `response_elapsed_ms`, `receipt_complete`, `finished_at`, `recovered_at`, `request`, `http`, `encoded`, `decoded`, `diagnostics`, `api_error`, `warnings`, `outcome`, `item_results`, `next_eligible_at`, `error`.

- attempt_id: monotonically allocated unique A-prefixed ID within the run; requested_qids: distinct eligible IDs, at most50, in frozen-list order.
- reserved_at precedes network I/O. dispatch_started_at is null if unconfirmed after crash, not proof a server received the request. headers_received_at is actual header receipt UTC/null; headers_observed is true/false/null (null means uncertain), durably recorded before body consumption. response_received_at is clean encoded-body completion UTC/null, and an accepted item's retrieved_at must equal it. response_elapsed_ms is nonnegative integer monotonic response duration/null, excluding later local decoding/classification. receipt_complete is true/false/null even for a clean zero-byte response without a body file. finished_at means overall attempt completion after local processing, null if unknown; recovered_at is a separate later observation.
- request: `{method, url, parameters, headers}` with GET, actual fixed parameters and ids. http: null or `{status_code, headers}`. Response-header allowlist: content-type/content-encoding/content-length/retry-after/date/etag/last-modified/location/x-database-lag; values are lists retaining repeated values. Never retain cookies/tokens/auth headers. Relevant unexpected header conditions are findings.
- encoded/decoded: B/null. For identity both may reference the same file; gzip has separate encoded/decoded files. Decoded is null when decoding never completed; retained decoded fragments, if any, are diagnostics. An empty received body creates no invented body file. Completeness comes from capture/framing/decode evidence, not parseability.
- diagnostics: zero or more `{role, file: B, explanation}` for captured/recovered/partial byte artifacts, including any retained item-writing fragment. Every retained non-item evidence file has one owning attempt or an explicit finding; encoded/decoded descriptors can share the one identity-encoded file without duplicating payload membership.
- api_error: null or preserved `{code, message}`; warnings: null or the complete returned warning JSON. Unknown top-level API fields are retained in the source and assessed explicitly.
- outcome: `reserved`, `succeeded`, `mixed`, `transient_failure`, `review_required`, `interrupted`, `saving_failure`. Only succeeded/mixed can support accepted item results; a complete usable wrapper requires success to be JSON integer1 alongside all item-level checks, not a sufficient success marker by itself.
- item_results: one entry for each requested QID, `{qid, outcome, returned_qid, error}`, with outcome accepted/transient_failure/review_required/unknown. During a still-active reservation, unknown results are explicit. error uses the same object as inventory. Missing/redirect, omitted, key/inner-ID and metadata errors have distinct codes.
- next_eligible_at and error describe any batch-level retry/hold. Per-item eligibility remains authoritative for mixed outcomes. The most restrictive valid server delay is respected when multiple headers are present.

All attempts, including reservations with unknown dispatch/result after crash, remain in the public final record and consume quota. A body published before completion was committed is retained as incomplete/unknown diagnostic evidence on recovery, not retroactively claimed complete.

Durable header receipts restore the most restrictive server wait before dispatch, even without complete body/outcome evidence. Uncertain lost receipt after possible dispatch produces server_wait_unknown and an automatic-retry hold, rather than claiming no server delay. Exact byte/header loss outside durable recording is reported as a limitation.

## README.md

The required UTF-8 run-scope document identifies the immutable run and frozen population using exactly one of each line: `Run ID: <run_id>`, `Run kind: <run_kind>`, `Frozen QIDs: <selected_count>`, and `Frozen QID list SHA-256: <qid_list.sha256>`. It explains complete extracted item JSON versus preserved response-body layers, the collection-period limitation and excluded media/history/recursive retrieval, public records and local-only .state/ recovery. Actual progress/retrieval times remain in the records; documentation alone never claims successful collection, deposit or publication.

Implementation correction reviewed 2026-11-07: new runs create this stable document during initialization. Independent verification accounts for it, checks safe regular UTF-8 text and unique matching identity lines, and rejects terminal runs missing it. Older stopped runs can add a missing document only with the explicit offline write-readme action; existing different text and finalized/pending-publication state require review. No public JSON record keys changed. Finalization includes README in its input fingerprint, and the later external package inventory hashes its final bytes.

## Verification reports

verification.json keys: `format_version`, `run_id`, `checked_at`, `inputs`, `status`, `checks`, `counts`, `findings`.

inputs identifies the selection and inventory/attempt snapshot descriptors. checks contains exactly `scope`, `source_content`, `provenance`, `files`, each `{check_id, status, findings}`. Findings use `{code, qid, path, message}` with null where unavailable; lists are empty only when no findings. Known failure dominates not_checked; counts reconcile frozen IDs. The verifier does not depend on internal SQLite, call extraction, fetch remote data or replace baseline hashes. A stale snapshot/in-progress run is unfinished; a detected corruption is failed. Whole report/manifest hashes are not embedded in each other.

## External package records

package-inventory.json keys: `format`, `format_version`, `package_id`, `run_id`, `run_kind`, `created_at`, `profile`, `payload`, `archives`.

- profile: `{format, max_members, max_payload_bytes_per_part, gzip_level, gzip_mtime, tar_header_policy, retention_evidence}`. Candidate profile values are in Plan; retention_evidence stays null until an actual requested test identifies Yale dataset/version, uploaded part IDs, download observations and result. A local candidate package can pass local checks without claiming Yale retention/deposit.
- payload: all finalized payload descriptors, each `{path, size_bytes, sha256, archive_path}`. Every intended item and non-item evidence/metadata file occurs exactly once. .state is explicitly excluded internal recovery state; unexplained files/staging are not implicitly excluded.
- archives: each `{path, size_bytes, sha256, members}`; members is the exact unique payload-path list. External inventory, archive outputs and package/deposit reports are outside payload, avoiding circularity.

The archive profile is tar.gz, gzip level 6/mtime 0 with no stored gzip filename, regular payload header uid/gid/mtime 0, empty uname/gname and mode 0644. Its tar_header_policy is `uid=0,gid=0,uname=,gname=,mode=0644,mtime=0`. Bounded PAX path extensions support Unicode/long paths; extension metadata has zero owner/time/mode, while regular payload members use 0644. Limits may be lowered but cannot exceed 5,000 members or 268,435,456 summed uncompressed payload bytes per part. The original local candidate retains null retention_evidence unchanged. An evidence-bearing profile still requires its own review; carrying a record does not approve that profile or establish Yale maximum limits.

### Historical retention evidence contract (2026-11-08)

retention_evidence is null for existing candidate compatibility, or embeds exactly the eight-key deposit-verification object specified below. Require format_version1.0.0, a valid generated package_id/calendar time, valid UTC checked_at, byte_status passed and publication null. The operator_recorded acquisition must provide dataset URL, persistent ID, version, recorded_by and every file's ID/URL/path. Paths cover exactly package-inventory.json and contiguous unique part-00001.tar.gz-style archive names; IDs are unique and preserved as strings. Only download times may be unknown/null. All URLs pass the same credential/private-link guards as acquisition receipts.

If receipt completeness passes, require deposit_status passed and empty findings. If download times are missing, require deposit_status not_checked and exactly the existing canonical acquisition_incomplete finding. Reject failed bytes, missing source identity, inconsistent results, malformed/extra keys, unsafe URLs and publication claims. Validation is pure and does not change the embedded report. Producer and independent verifier use a neutral schema validator; the independent verifier does not call the producer or deposit checker.

This embeds a historical operator-supplied verification record. Checking its schema does not re-observe the transfer, independently verify the old archive without its bytes, establish tested maximum sizes, approve profile limits, verify the new package's deposit or publish anything. Missing historical observations remain null. The separate collection/deposit/publication outcomes and deposit completeness criteria are unchanged.

Successful local output contains package-inventory.json, part-00001.tar.gz-style archives and an external package-verification.json. Publication retains pending inventory/partial archives on failure and never overwrites an existing package. The report writer binds the producer's exact inventory bytes and stable archive inputs; a failed report may retain genuine missing/unsafe/damaged evidence but cannot confer success. A fresh read-only verify-package independently checks saved bytes and safely roundtrips the entire finalized collection in temporary storage.

package-verification.json: `{format_version, package_id, checked_at, status, checks, findings}`. checks names are `inventory`, `archive_integrity`, `payload_roundtrip`, with the common check shape. Compare exact path sets, sizes and hashes after safe extraction. Reports never modify finalized collection bytes.

## Acquisition and deposit record

Operator-supplied acquisition.json keys: `dataset_url`, `persistent_id`, `dataset_version`, `downloaded_at`, `files`, `recorded_by`, `evidence_kind`. files covers the downloaded external inventory and every part with `{remote_file_id, download_url, local_path, downloaded_at}`. evidence_kind is `operator_recorded`; do not claim the offline checker independently observed an HTTP transfer. Do not include credentials or signed-secret query strings in public evidence.

deposit-verification.json: `{format_version, package_id, checked_at, acquisition, byte_status, deposit_status, findings, publication}`. byte_status can pass for exact supplied files. deposit_status stays not_checked without complete actual dataset/version/acquisition evidence; with it, report byte comparisons plus explicitly operator-recorded provenance. publication is null until a separately requested actual publication, then `{persistent_id, dataset_version, published_at, recorded_by}`. Neither collection nor deposit verification sets publication automatically.

This record is a verification result, not a substitute for uploading/downloading the actual files. The actual target collection, depositor access and metadata must be resolved before the separately requested deposit.

Implemented diagnostic behavior: omitting acquisition evidence or supplying safe null unknowns can establish byte equivalence while deposit_status remains not_checked. Malformed/unsafe receipts fail without echoing supplied secret URLs; stable public identifiers and leading zeros remain exact. The receipt and optional report must be external to both input directories. Downloaded files contain exactly the external inventory and every archive part, without the local package-verification.json. The checker compares inventory bytes against the preserved local original before trusting downloaded archive metadata. Exit1 covers either failed outcome; exit2 means provenance remains incomplete; exit0 requires both outcomes passed. Publication remains null in every offline result.
