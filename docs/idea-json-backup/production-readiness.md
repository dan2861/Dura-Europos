# Full collection: readiness review and next guided stop

Reviewed 2026-11-08; updated after Danu's capacity result and the profile TDD increments. Danu performs operational commands. Preparation does not start collection or change the frozen selection, pilot package, download receipt or saved verification report.

## Evidence and archive recommendation

The frozen production selection contains 33,709 QIDs; its list SHA-256 is `3cb327159086e9cf3486da865ce55e001ba6e7ecc94334b38eb5070f96d63f43`. The parent-linked three-item collection and local package passed their separate audits. Danu's saved downloaded-package audit records byte_status passed, deposit_status not_checked, acquisition_incomplete and publication null. Dataset doi:10.60600/YU/KPHJOF, DRAFT, inventoryID221111 and archiveID221110 are already recorded. Download times were not recorded and remain null. File location and byte checks are settled; do not repeat them.

Keep tar.gz, gzip level6 and normalized archive metadata as the recommended production format. Observed Yale retention evidence covers one 503,551-byte archive with 28 payload files /8,850,019 uncompressed payload bytes. It supports unchanged bytes for that actual file; it does not measure the proposed maximum part size or establish complete deposit verification.

The candidate's 5,000-member /268,435,456-byte uncompressed payload caps remain proposed local packaging limits. They are not Yale limits or limits exercised by this pilot. [Yale's FAQ](https://researchdata.yale.edu/yale-dataverse-faqs) describes ZIP-specific file-count/size guidance; it does not establish a tar.gz maximum. Do not alter the immutable pilot package's null retention_evidence to retrofit a final profile.

## Remaining profile implementation increment

The initial review found that the [producer](../../scripts/idea_json_backup/package.py) and [independent verifier](../../scripts/idea_json_backup/package_verify.py) required null retention_evidence. The offline increment is now complete: a neutral validator permits an exact historical byte-passed deposit-report object, retains explicitly unknown times/not_checked, and rejects missing identity, inconsistent outcomes and unsafe URLs. Existing null-evidence profiles remain compatible. The producer snapshots nested evidence before auditing so caller changes cannot replace the validated report.

RED→GREEN evidence and separate reviews are recorded in production-log.md. All314 offline tests passed26.353s. Separate contract and producer reviews plus the final independent invented CLI composition are clear. The [reviewable profile](../../changes/idea-json-backup/production-archive-profile.json) retains the candidate's local caps/compression and embeds saved report001 unchanged as historical evidence. It is proposed for later packaging, not a new deposit verification or evidence of Yale maximum limits. The immutable pilot/candidate files remain unchanged.

## Current service assessment

The current [Wikidata access guide](https://www.wikidata.org/wiki/Wikidata:Data_access#MediaWiki_Action_API) documents small groups of up to50 entities but cautions against large Action API result sets and suggests considering dumps. It gives no numeric threshold that establishes this particular full run as suitable. A successful three-item request and synthetic scale test do not settle that operational question. The approved pilot-gated route remains conditional; no switch to dumps or other service is made here.

The code uses batch50, concurrency1, a one-second minimum gap after each completed attempt, a60-second response deadline, maxlag5, three persistent attempts per QID, and Retry-After/backoff handling. Its identifying User-Agent is `IDEA-JSON-Backup/0.1.0 (https://github.com/dan2861/Dura-Europos)`. These controls follow the relevant [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette). Current [rate guidance](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits) lists200requests/minute for compliant unauthenticated User-Agent clients; the serial one-second completion gap implies at most about60dispatches/minute before response/I/O time. Being below a rate limit does not establish bulk-service suitability, and limits can change.

33,709 items require675 baseline requests:674 groups of50 and a final group of9. The674 one-second inter-request gaps exclude response time, saving, local audits, retries and server waits; they are not a duration estimate. Three attempts per QID allow at most101,127 item-attempt reservations.2,025 HTTP requests would describe an all-batches-retry-together scenario, not a general upper bound when partial outcomes regroup. Long Retry-After waits prevent a fixed overall runtime bound.

## Completed guided stop: available disk space

Danu ran the read-only capacity check:

```bash
df -h /Users/danu/Documents/ChatGPT/Dura-Europos
```

Operator-reported output:

```text
Filesystem      Size    Used   Avail Capacity iused ifree %iused  Mounted on
/dev/disk3s5   228Gi   185Gi    12Gi    94%    2.3M  128M    2%   /System/Volumes/Data
```

Record12Gi available and94% capacity from this observation. This neither proves that the full workflow fits nor proves that it cannot fit. No cleanup or drive purchase is inferred. Do not repeat the completed capacity command as a prerequisite to this checkpoint.

Capacity planning must include item JSONs, public encoded/decoded responses, retained capture copies under .state/, journal/logs, archives, downloaded copies and temporary extraction. The collector has no global byte/disk budget. The three-item pilot is not a representative size forecast, so no numeric free-space threshold is asserted. Use actual next-batch measurements before deciding whether to expand or change the working location.

## Completed guided stop: first production batch

Danu completed the creation command below. Report checked_at2026-11-09T01:26:44.760771Z gives50 accepted,33,659 pending,0 unresolved, no findings; overall/scope not_checked and source_content/provenance/files passed. Saved metadata agrees: run20261109T012636.715412Z-746d5d786f2f, paused, generation54. This command is completed history; do not repeat collect into the existing directory. The next guided action is the allocated-footprint check below.

Engineering assessment: one serial request of up to50 already-selected IDs fits the documented small-batch API route. The original three-item pilot established complete source preservation and recovery behavior; the next batch supplies more useful size/timing evidence. This clears only the bounded step below. It does not approve an unattended675-request expansion, establish a full storage allowance, override current server waits or claim service endorsement. Reassess from the actual result before another invocation.

Read-only preflight found backup/idea-production-run-001 absent, including no symlink. The following operator command starts a new production run against the unchanged33,709-QID selection, then stops after one batch attempt. Do not create the output directory beforehand. Run from /Users/danu/Documents/ChatGPT/Dura-Europos:

```bash
python3 -B -m scripts.export_idea_json collect \
  --selection /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-selection-001 \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --kind production \
  --max-batches 1
```

This makes a live read-only Wikidata request and creates local run state/source evidence; it does not modify Wikidata or deposit/publish anything. Return the complete report and pause. A successful first batch should accept up to50 items while overall status/scope remain not_checked because most frozen IDs are still pending. A maxlag/refusal may leave that batch unresolved; retain the response and review it without resetting quota or starting another run. The one-batch bound counts attempts, not guaranteed successes.

After the result, review actual response bytes/latency, item sizes, retained local overhead, findings and available capacity before expanding. Later bounded work resumes the same run with its original quotas; never repeat collect into the existing directory. Actual full collection, final packaging, deposit and publication remain distinct guided stages.

## Completed guided stop: measure the paused run's allocated space

The first batch's saved descriptors record481,921encoded /2,875,604decoded response bytes and2,874,987item bytes, with all50 membership checks matching. HTTP200 was complete and reported response elapsed was1,020ms. This is successful bounded collection evidence, not an estimate for all later items.

Danu ran this read-only command:

```bash
du -h -d 1 /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001
```

The directory breakdown includes .state/ capture/journal overhead as well as public items/responses/selection. It changes no files and makes no network request. Full-scope selection/inventory records already exist; do not multiply the entire directory total by33,709/50 to estimate completion.

Operator-reported result:

```text
3.2M    responses
  0B    diagnostics
 15M    .state
4.3M    selection
2.8M    items
 35M    total
```

These are rounded allocated-space readings for the current run; the full paths are preserved in the review record. The total also includes root-level files, including the full-scope inventory, so it need not equal only the listed child directories. The internal state contains full-scope journal setup as well as growing capture evidence. Its15M must not all be treated as a per-batch cost.

Same-first-batch-mix arithmetic gives about6.02GiB of items/public responses/retained capture bodies, excluding fixed records, retries, archives, downloaded copies and extraction. Adding a full public extraction copy alone gives about9.93GiB before those other components. This is not a forecast or upper bound; the previous12Gi free does not settle full-workflow capacity. Review actual allocated usage before increasing the invocation limit. [First-batch evidence](../../review/idea-json-backup-production-run-001.md).

## Completed guided stop: resume for ten batch attempts

Danu completed this invocation. Report checked_at2026-11-09T01:32:45.380736Z gives550 accepted/33,159 pending/0 unresolved, no findings, overall/scope not_checked and all three non-scope checks passed. Saved metadata agrees: same run, paused, generation594. All11 attempts so far succeeded with complete HTTP200 receipts; all550 accepted items have matching IDEA membership. The command below is completed history for this increment; do not repeat it merely to reproduce the report.

The first clean request and measured35M run footprint support a bounded next increment. They do not clear unrestricted completion or final packaging/storage. Ten additional same-mix batches would add roughly96MB of item/response/capture logical bytes, plus changing records, allocation and journal overhead; this is a scenario, not an enforced byte bound or forecast. Continue to retain server waits, quotas and the existing run.

From the project directory, Danu runs:

```bash
python3 -B -m scripts.export_idea_json resume \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --max-batches 10
```

This audits/reuses existing work and makes up to ten further serial batch attempts. It can accept at most500 additional items; retries/refusals can reduce that count. If all ten batches succeed cleanly, expect550 accepted/33,159 pending/0 unresolved. Overall/scope remain not_checked while work is pending. Return the complete JSON report and pause for findings, size/growth and capacity review before another expansion. Do not run collect again or remove/reset state. No automatic finalization, packaging, upload or publication occurs.

## Completed guided stop: updated growth and free space

At550 accepted items, saved descriptors total12,337,836item bytes,1,239,580encoded and12,345,213decoded response bytes. Ten new responses record648–957ms each, no errors or warnings. Updated mean item size is22,432.43bytes; the ordered early items remain unrepresentative. Same-mix variable storage including retained body captures is39,507,422bytes observed, or a2.26GiB full-population scenario before fixed records, retries, archives, downloaded copies and extraction. This is not a storage guarantee.

Danu ran both read-only measurements:

```bash
du -h -d 1 /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001
df -h /Users/danu/Documents/ChatGPT/Dura-Europos
```

du updates the first35M allocation observation after500 additional accepts; df refreshes the earlier12Gi free-space result. This is a new growth checkpoint, not a request to repeat unchanged evidence. Review both before increasing the next resume bound. No further collection, finalization or packaging is requested at this measurement stop.

The supplied result is65M total: responses13M, diagnostics0B, .state26M, selection4.3M, items13M. The filesystem reports12Gi available and94% capacity, /dev/disk3s5 mounted at /System/Volumes/Data. These are rounded operator observations; an unchanged12Gi display does not mean the500-item increment consumed zero space. The run grew approximately30M from the first50 to550 accepted items. Fixed selection and full-scope journal/inventory setup are not per-item growth.

## Completed guided stop: resume for100 batch attempts

Danu supplied the completed result at2026-11-09T01:44:25.347688Z:5,550 accepted/28,159 pending/0 unresolved, no findings. Saved metadata agrees on the same run, paused generation5994 and111 successful complete HTTP200 attempts; all5,550 IDEA memberships match. Overall/scope remain expected not_checked; source_content/provenance/files passed. The command below is completed history for this increment.

The clean11-attempt history,65M measured run and refreshed12Gi free-space reading support a larger bounded increment. A separate read-only capacity review agrees. Recent30M/500-item growth would suggest roughly300M more for5,000 similar items, but later sizes/retries can differ; this is not a forecast or byte limit. Final archive/download/extraction capacity still needs review later.

From the project directory, Danu runs:

```bash
python3 -B -m scripts.export_idea_json resume \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --max-batches 100
```

The existing run, accepted revisions, frozen population, serial pacing, server waits and persistent quotas remain in force. This invocation permits up to100 additional physical batch attempts /5,000 new accepts; retries or refusals can reduce that number. If all succeed fully, expect5,550 accepted/28,159 pending/0 unresolved, with overall/scope still not_checked. Return the complete JSON report and pause for progress/findings/growth review before another invocation. This does not clear unrestricted completion, finalization, packaging, upload or publication.

## Completed guided stop: growth after5,000 more accepted items

Recorded cumulative sizes are81,239,179item bytes,6,837,221encoded and81,318,923decoded response bytes. The latest100 requests all succeeded, recorded407–1,016ms response elapsed and no API errors/warnings. Their first dispatch to last completion interval was about4m42s; it is not a duration guarantee for later requests.

Public variable bytes total169,395,323; with retained body captures,257,551,467. The same-mix full-population scenario is about1.457GiB before fixed records/retries/archives/download/extraction. This remains scenario arithmetic, not allocated disk usage or a forecast. A separate reviewer agrees with the arithmetic and recommends measuring current allocation/free space before the next bound.

Danu ran both read-only commands:

```bash
du -h -d 1 /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001
df -h /Users/danu/Documents/ChatGPT/Dura-Europos
```

Compare against the prior65M run and12Gi free observations. No repeated content audit or code change is needed for the already-passed result. Continue using the same run; no further resume is requested until these growth measurements are reviewed.

The returned allocation is289M total: responses85M, diagnostics0B, .state101M, selection4.3M and items88M. df reports /dev/disk3s5,228Gi size/186Gi used/12Gi available,94% capacity. These are rounded operator observations. The run grew about224M for5,000 more accepted items; fixed setup must still not be scaled per batch. Same-mix scenarios remain estimates, not byte limits or full-workflow guarantees.

## Completed guided stop: collection stopped with one unavailable item

Danu returned a failed scope report at2026-11-09T02:20:44.840683Z for Q134471369. Saved metadata records33,708 accepted/0 pending/1 unresolved, phase collected, generation36409. All675 planned request batches completed:674 succeeded and A000623 was mixed, accepting49 neighbors while preserving the unavailable stub. This is not a verified complete collection. The verifier stopped at that unresolved row, explaining null report counts and other checks not_checked; no finalization is permitted from this result.

The111 clean requests, matching memberships, no findings and current289M/12Gi measurements support attempting the remainder in this same run. A separate read-only capacity review agrees that a600-attempt bound is reasonable; no observed constraint specifically requires300. There are28,159 pending IDs, requiring564 requests if every batch succeeds cleanly (563 groups of50 and one group of9).600 is36 attempts beyond that clean minimum, not a guaranteed retry allowance: partial outcomes and regrouping can change request count. The limit bounds physical attempts, not time or bytes; existing server waits and three-attempt-per-QID quotas remain unchanged.

From the project directory, Danu runs:

```bash
python3 -B -m scripts.export_idea_json resume \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --max-batches 600
```

The collector stops early once all frozen IDs are accepted; it does not issue extra requests to exhaust600. A clean completion should report status passed, all four checks passed,33,709 accepted/0 pending/0 unresolved, phase collected. This prints a fresh independent collection audit but leaves explicit finalization for the next guided step. If it pauses incomplete or reports a failure, retain the same run and return the entire report before any further action; do not reset quota or start a replacement run.

Return the complete JSON when the command completes or pauses. Server waits can extend runtime; the attempt cap is not a wall-clock deadline. Finalization, final capacity/package review, deposit and publication remain later guided steps. The assistant has not run this command.

## Current decision: confirmed redirect to an already-saved target

The preserved response has `{"id":"Q134471369","missing":""}` under redirects=no. Danu subsequently inspected the page and reports Q134471369→Q122677115. The target is already accepted in this run (items/Q122677115.json, revision2506727154, A000372); the mapping remains operator-reported, not independently retrieved by the assistant.

Normal resume does not retry this nonretryable identity exception. Danu approved the [redirect-record-only outcome](../../changes/idea-json-backup/redirect-resolution-proposal.md), and the separately versioned [release addendum](redirect-release.md) is now implemented/reviewed offline with342 passing tests. The original run and its strict completion outcome stay unchanged. Follow [redirect-release-runbook.md](redirect-release-runbook.md): first audit every original item/source to a new external strict report, then capacity/copy/release checks/package in separate guided stops. No historical retrieval, source mutation, actual release or deposit is claimed.
