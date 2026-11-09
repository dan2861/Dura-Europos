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

## Next guided stop: one bounded production batch

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
