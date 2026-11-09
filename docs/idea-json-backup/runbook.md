# IDEA JSON backup: production roadmap runbook

Updated 2026-11-08. The frozen production selection has33,709 QIDs and the parent-linked three-item pilot is finalized, independently verified and reviewed. The latest suite passed314 tests after the historical profile-evidence increment; the earlier separate33,000-item synthetic scale exercise passed. Local pilot packaging and its separate check passed. Yale draft identity/access are operator-reported and the saved downloaded-package audit has byte_status passed; deposit_status remains not_checked because download times were not recorded. Danu reports12Gi free on the project filesystem. The [readiness packet](production-readiness.md) supplies the next one-batch guided production start and review gate. Unattended full expansion, complete deposit verification and publication remain later stages. The [MVP runbook](mvp-runbook.md) remains historical prototype documentation.

Danu runs operational commands with guidance. The assistant runs invented offline TDD tests and makes small commits. Do not infer a live discovery or full backup from passing unit tests. No phase starts another phase automatically.

## Completed guided discovery

The following command already completed for `backup/idea-selection-001`; retain that frozen selection and do not rerun it into the existing directory.

From `/Users/danu/Documents/ChatGPT/Dura-Europos`, Danu runs:

```bash
python3 -B -m scripts.export_idea_json discover \
  --output backup/idea-selection-001
```

The output directory must not exist. The command queries the main and scholarly graphs sequentially using the approved explicit normal/preferred `P5008 = Q114241199` query, preserves request/response evidence, deduplicates the union and sorts QIDs numerically. It automatically runs the independent selection audit. It retrieves identifiers, not full entity JSON, and performs no Wikidata edit or Dataverse upload.

There is at least one second between completed attempts and later dispatches, a 60-second supervised response deadline, and at most three attempts per graph. Known transient failures wait at least 5/10 seconds or the longer observed Retry-After. Saving failures, uncertain header receipt, complete malformed responses and non-transient outcomes stop for review. A real Retry-After can make the command take longer than the per-response deadline. Do not interrupt a legitimate cooldown merely because the command has not printed a final report.

Success prints JSON with `status: passed`, no findings, the actual `selected_count`, and the output path, and exits 0. Approximately 33,000 is an expectation, not a required count or a completion threshold. Stop after this command and return its exact output for review.

If it fails, retain the directory and report the output. Failed/incomplete graph evidence never creates a consumable frozen list. This milestone has no discovery-resume command; do not reuse the directory or automatically start a fresh attempt before reviewing the previous server-wait/error evidence.

## Separate persisted selection check

After reviewing the discovery command's result, Danu performs the separate read-only audit:

```bash
python3 -B -m scripts.export_idea_json verify-selection backup/idea-selection-001
```

Expected success is `{"status": "passed", "findings": []}`. The check reads public files only, does not query Wikidata, repair data or rewrite checksums. Exit 1 means a known failure; exit 2 means an unfinished pending selection or a handled interruption. No item collection is started by discovery or verification.

## Saved evidence and limitations

- `query.rq`: exact approved explicit-rank query, with no label service or LIMIT.
- `sources/`: immutable encoded/decoded response bodies, including failed/partial attempts where bytes were received. Original duplicate bindings remain in the saved results.
- `qids.txt`: nonempty, distinct canonical QIDs, one per UTF-8/LF line in numeric order. It is published only after both graphs succeed.
- `selection.json`: production format `idea-json-backup` version `1.0.0`, criterion, both graph sources, exact requests, timing/elapsed/header/completeness evidence, all attempts, body/list/query descriptors, frozen count and time. An incomplete selection keeps unavailable fields null.
- `.state/`: internal durable dispatch/worker receipts and spool files, explicitly outside the public payload. Retain them on failure for diagnosis; the public verifier does not use them as expected evidence.

An empty scholarly graph is valid if the combined union is nonempty. A failed graph, ambiguous receipt or empty union prevents a complete selection. WDQS graphs update asynchronously; the frozen list is the observed two-graph result, not a claim that all records describe one historical instant.

Before accepting the selection, review the actual count, endpoints, graph outcomes, attempts and query. Its checksum fixes the population for later collection. Any subsequent membership change will be recorded without silently changing that list.

## Next guided gate

Current active step2026-11-08: redirect-record-only was approved and the separate release workflow now passes342 offline tests and separate/final reviews. Follow [redirect-release-runbook.md](redirect-release-runbook.md), starting with the original strict source audit to review/idea-json-backup-production-strict-001.json. Expect original scope failed for Q134471369, accurate33,708accepted/1unresolved counts, and all three non-scope checks passed. Do not repeat collection or use --write. The earlier awaiting-choice/completion instructions below are historical.

Earlier decision checkpoint2026-11-08: the completion attempt ended with33,708 accepted and one nonretryable unavailable item, Q134471369. Danu reported a redirect to the already-accepted Q122677115 and subsequently approved explicit redirect accounting. That implementation is now delivered as the distinct release workflow above; the earlier resume600/completion expectations remain completed history.

Latest checkpoint2026-11-08: Danu reports289M allocated after5,550 accepted items (responses85M/.state101M/selection4.3M/items88M), with12Gi free/94%. Review is clear for a bounded same-run attempt to finish: resume --max-batches600. The28,159 pending IDs need564 requests if all batches succeed; the collector stops early at full acceptance. Return its complete report and pause. All-clean expected outcome is33,709 accepted/0 pending/0 unresolved, status passed, phase collected; explicit finalization remains separate. See [production-readiness.md](production-readiness.md). Earlier du/df instructions are completed history.

Latest checkpoint2026-11-08: the100-attempt resume completed with5,550 accepted/28,159 pending/0 unresolved, no findings; paused generation5994,111 complete successful HTTP200 attempts, all memberships matching. Next refresh du+df after5,000 additional accepts using [production-readiness.md](production-readiness.md), then review before setting the next resume bound. The earlier resume100 instruction below is completed history.

Current guided step2026-11-08: updated allocated size is65M (responses13M/.state26M/selection4.3M/items13M), with df still reporting12Gi free/94%. Review is clear for same-run resume --max-batches100, then stop/return the complete report. All-clean expected counts are5,550 accepted/28,159 pending/0 unresolved. The earlier du/df instruction is completed; no unbounded full expansion is cleared. See [production-readiness.md](production-readiness.md).

Latest checkpoint2026-11-08: the ten-attempt resume completed cleanly,550 accepted/33,159 pending/0 unresolved, generation594, no findings. All11 saved attempts succeeded, all550 membership checks match, and the frozen scope is unchanged. Next obtain updated du and df outputs as shown in [production-readiness.md](production-readiness.md), then review actual growth/free space before increasing the resume bound. The earlier ten-batch instruction below is completed history.

Current checkpoint2026-11-08: Danu completed the first production batch;50 accepted/33,659 pending/0 unresolved, no findings, paused generation54. Danu's allocated-space check subsequently reports35M total, including15M .state. The next guided command is same-run resume --max-batches10 in [production-readiness.md](production-readiness.md), followed by a report/size review before expanding further. If all ten batches succeed, expect550 accepted/33,159 pending/0 unresolved; overall not_checked remains expected. The creation and first allocated-size commands are completed history; never repeat collect into the existing run.

Discovery, saved selection review, three-item pilot collection/finalization, local packaging and the supplied-download byte audit are complete. Dataset/version/file IDs and downloads001 are settled; unrecorded times stay null and deposit_status stays not_checked. The profile increment and separate/final reviews are complete. The capacity check is complete with12Gi available; no whole-workflow capacity claim is made. Follow [production-readiness.md](production-readiness.md) for one guided production batch, then stop to review real size/timing/errors before any expansion. Publication remains a separate request.

Implementation/review evidence: [production-log.md](production-log.md); full approved roadmap: [plan.md](plan.md) and [record-layouts.md](record-layouts.md).
