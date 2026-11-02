# IDEA JSON backup: first MVP

**Completed 2026-11-02:** Danu authorized automatic offline RED → GREEN → commit increments. The MVP and its separate milestone/final reviews are complete; all 54 MVP tests and all 51 historical sample tests pass. See [mvp-runbook.md](mvp-runbook.md) and [implementation-log.md](implementation-log.md). No live retrieval was performed.

Danu requested an MVP before expanding through the approved production [Plan](plan.md). The delivered slice below preserves source/item correctness while keeping discovery, production recovery and deposit features deferred. Implementation history and review fixes are recorded in the increment log.

## Small working slice

For one supplied, frozen list of at most 50 QIDs and one batch response:

1. Preserve the unchanged response bytes.
2. Save each complete, identity-matched entity as its own QID.json, including unknown fields and exact numeric tokens.
3. Write a compact prototype manifest containing the input list, source provenance, per-item outcomes/revisions, file paths, sizes and checksums. Mark synthetic/saved/live provenance honestly; do not invent retrieval times for saved fixtures.
4. Independently compare every saved item with its original response object and verify the files' checksums. Fail visibly for missing, substituted or damaged data.

Start with saved/invented responses and temporary directories. Then add a one-batch retrieval adapter, tested offline. The adapter must still identify itself, enforce the request deadline, detect API errors and incomplete/undecodable bodies, and preserve partial/error evidence. No live run is part of implementing or testing it; an actual pilot needs its own request.

Use one attempt and a new output directory. No automatic retries, resume or overwriting of an earlier result. Failure/interruption retains whatever evidence was durably saved and leaves the result visibly incomplete; it cannot pass merely because some items were saved.

The output is explicitly a **prototype**, using a separate `idea-json-backup-mvp` format identity rather than claiming the complete production 1.0.0 schema. Its compact manifest is not a replacement for the approved final record layouts. MVP completion means verified preservation behavior and an offline-tested adapter, not a completed live IDEA backup or deposit.

## First test and review

First behavior: given an invented one-item batch, preserve its source bytes and the entire entity object, including an unfamiliar nested field with the string identifier `0007`. The first test checks those outputs; further tests add identity failures, precision, checksums and independent corruption detection in small increments. Explain each new behavior/test before execution and follow red–green–refactor. Existing codec coverage that already passes is regression evidence, not a manufactured failing test.

Deliver and review this MVP before expanding it. Its source/extraction/verification logic should remain separate from the later network scheduler and storage journal. A small separate assistant review checks data preservation and the adapter before presenting the result.

## Later deliverables

Add full-population discovery, batching across many requests, durable SQLite progress, resume/retry policy, 33,000-item checks, archive packaging and Dataverse verification in later reviewed increments. These remain requirements for the final system; they are not all part of the first MVP. The production [Spec](design.md) remains unchanged.

The earlier guided execution choice was superseded on 2026-11-02 by explicit authorization to finish this MVP automatically. That authorization covers offline implementation, tests and local commits only. Any live pilot, production expansion or deposit remains a separate requested scope.
