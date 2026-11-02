# IDEA JSON backup: brief

Started: 2026-10-28. Status: [Spec](design.md) and [Plan](plan.md) approved; the first [MVP](mvp.md) was completed and separately reviewed on 2026-11-02. Danu authorized automatic offline TDD and local commits for this slice. All 105 tests pass (54 MVP, 51 historical). See [runbook](mvp-runbook.md) and [increment log](implementation-log.md). No live execution has started.

## Central question

How should we preserve a complete, verifiable JSON export of all IDEA-tagged Wikidata items, approximately 33,000 according to Danu, and deposit it in Yale Dataverse before LUX-link edits?

## Established user requirements

- Back up all IDEA-tagged items as complete JSON files in Dataverse.
- Make one export before edits; recurring snapshots are outside the initial request.
- A documented collection period is acceptable (confirmed by Danu on 2026-10-28). Preserve each item's revision as retrieved and record its retrieval time; the items need not all reflect one shared historical instant. Record the overall collection start and finish.
- Include items with at least one **normal or preferred** P5008 = Q114241199 statement (confirmed by Danu on 2026-10-28). Exclude items whose only matching IDEA-tag statements are deprecated. This rule selects items; every selected item's complete JSON still retains all statements and ranks, including deprecated statements.
- Freeze the exact QID list selected at the start (confirmed by Danu on 2026-10-28). Account for every selected QID; report later tag/membership changes separately rather than silently changing the population. Later additions do not automatically enter this run.
- Deliver archive downloads containing separate per-item JSONs (confirmed by Danu on 2026-10-28). Individual listing of approximately 33,000 JSONs on Dataverse is not required. Archive format, part sizes and actual Yale retention/upload handling remain to be verified.
- Treat approximately 33,000 as the expected scale, not an independently verified count or a hard-coded completion target.
- Use QRSPI to develop the work in stages.
- The separate LUX task identifies candidate link additions/rank changes. Its matching work and any eventual Wikidata edits are not part of this backup implementation.

## Proposed deliverable for discussion

- Complete saved entity JSON for every item in an explicitly defined selection.
- The selection query, its execution time and exact QID list.
- An inventory associating each requested QID with its returned identity, saved revision, retrieval time, filename, size, checksum and outcome.
- Explicit failure/exception reporting and reconciliation of expected versus saved items.
- Documentation of scope, method, collection interval or source-dump date, limitations and verification results.
- A documented deposit package and a check that original JSON can be recovered intact from Dataverse.

The approved Spec and Plan govern the production requirements. Danu requested a small MVP first, before expanding through the full roadmap. The old sample's five CSVs and associated two-item table review are not prerequisites for the JSON-only goal. Preserve the earlier code, specifications, sample outputs and evidence unchanged.

Approved boundary: current structured item records, without media downloads, full revision history or recursive collection of linked items. The JSONs preserve identifiers/URLs, not the linked external resources themselves.

## Questions to resolve

1. The offline MVP and its reviews are complete. Review the [runbook](mvp-runbook.md) before deciding whether to request a small live pilot or a later production increment. Neither follows automatically from prototype completion.
2. Finalize archive format/part limits and actual Yale retention/upload handling through a separately requested draft test. The exact destination, depositor access and required metadata remain to be established before upload.
3. The proposed API route needs a separately requested pilot and current access-guidance check before full collection; no endpoint behavior, performance or service endorsement is assumed from the approximately 33,000 estimate.

## QRSPI progression

| Stage | Purpose | Planned record |
| --- | --- | --- |
| Questions / brief | Agree goal, boundaries and unresolved choices | This brief; confirmed decisions distinguished from proposals |
| Research | Check acquisition/deposit options and existing reusable code against the new scale | [research.md](research.md), initial findings recorded; empirical checks remain pending |
| Specification | Agree outputs, metadata, exception handling and completion criteria | [design.md](design.md), approved 2026-10-28 |
| Plan | Define implementation increments, tests, milestone reviews and execution steps | [plan.md](plan.md) and [record layouts](record-layouts.md), approved as roadmap with MVP-first delivery |
| Implementation | Build and test from the approved specification and plan | First MVP complete and reviewed; 54 MVP tests pass. Production expansion remains deferred |

Do not carry the old sample schema forward automatically. Preserve the adopted incremental TDD, separate milestone reviews and final integrated review when implementation is requested. Data collection and deposit remain explicit later execution steps.

## Organization and execution status

Use the existing Dura-Europos repository. This is a new task directory, not a new repository. The directory is under docs/idea-json-backup/ so the new brief is eligible for normal Git tracking under the current ignore rules, which exclude docs/tasks/. No ignore rule was changed.

The MVP code, tests, runbook and local commits are complete. Reviews and tests used invented responses, injected transports/workers and existing local regression fixtures. No exporter was run against a live service, no new entity data was retrieved, no Dataverse upload/publication occurred, and no external edit or push was performed.

## Existing context

- [Current project summary](../../SUMMARY.md).
- [Historical sample specification](../tasks/sample-backup/design.md), evidence of the prior scope rather than authority for this new format.
- [Historical sample implementation plan](../tasks/sample-backup/plan.md), including the adopted TDD/review process.
- [Sample runbook](../runbook.md), applicable to the old sample workflow.
