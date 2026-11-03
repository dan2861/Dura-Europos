# Production roadmap: implementation checkpoints

Started 2026-11-03 after Danu's three-item MVP pilot and separate persisted verification both reported passed. Separate saved-evidence review found no hold. This is technical pilot evidence, not full-population or service-feasibility proof.

Authorization: assistant runs offline TDD and makes small local commits; Danu executes operational discovery/collection/Dataverse commands in guided runs. No automatic live calls, uploads, publication, Wikidata edits or pushes.

| Increment | RED observed | GREEN evidence |
| --- | --- | --- |
| Numeric discovery union | Selection module absent | Invented main Q10/Q2 + scholarly Q2/Q1 freezes Q1/Q2/Q10 and preserves exact source bytes |
| Strict graph results | Invalid/malformed binding schemas, non-item URIs and padded IDs were accepted or raised KeyError | Four selection tests pass; empty scholarly/60-item/no-overwrite cases are honest already-green regressions |
| Generic HTTP capture | New client absent | Ten offline tests pass; full header lists, clean encoded receipt, framing/decode/saving distinctions retained |
| Serial discovery orchestration | Discovery module absent | Three fake-clock tests pass: both graphs, numeric union, Retry-After seconds/date, bounded retries and no freeze on incomplete graph |
| Independent synthetic selection audit | New verifier absent | Seven hand-built fixture tests pass, including altered union with refreshed hashes, schema/path/query corruption and >50 QIDs |
| Generic capture supervision | Missing fetch entry point; known process-start failure initially mislabeled as saving | Eighteen offline tests pass; parentdeadline, durable dispatch/header receipt, lost-header holds, partial/empty capture and process cleanup |
| Consistent generated selection time | Frozen timestamp ignored injected discovery clock | Three discovery tests pass with one clock across dispatch, receipts and freeze |
| Verifiable cooldown boundary | Advancing UTC clock exposed cooldown shorter than one second after recorded completion | Four discovery tests pass; completion timestamp is captured once before deriving the next-dispatch floor |
| Saving-first discovery stop | Capture saving failure raised generic ValueError/review outcome | Five discovery tests pass; saving_failure is explicit, nonretryable and stops even alongside transient HTTP503 |
| Selection directory durability review fix | Parent directory fsync failure was never reached before requests | Six discovery tests pass; parent-sync failure prevents every dispatch |
| Unsuccessful worker review fix | Nonzero worker exit after published success metadata was classified as retryable transport | Nineteen client tests pass; nonzero exit remains saving/uncertain, retains bytes and is nonretryable |
| Observed selection receipt audit | Synthetic-only verifier rejected valid production/injected receipts and retry history | Eleven independent verifier tests pass; strict timing, header lists, decode linkage, scope and cross-graph cooldown checked |
| Selection hardlink rule | A checksummed public source hardlinked outside the bundle still passed | Twelve independent selection tests pass; public payload requires one regular-file link |
| Production discovery commands | New production CLI absent | Two CLI tests pass with mocked discovery and real independent read-only selection audits; no live query executed |
| Unfinished CLI outcome | Pending selection returned known-failure exit1 | Three CLI tests pass; unfinished selection is not_checked/exit2 without mutation or fetching |
| Integrated capture/union regression | Already GREEN: composed previously tested pieces without manufacturing a failure | Seven discovery tests pass, including real spawned worker with streamed invented gzip and network connections blocked |

Discovery milestone validation: full `python3 -B -m unittest discover -s tests -q` passed 150 tests (45 discovery-stage + prior 105). No live discovery/collection or deposit command was run by the assistant. The next guided gate is discovery into a fresh selection directory; production item collection/resume/archives remain unimplemented.
| Known-failure precedence review fix | CLI downgraded corrupt initialized format/criterion/query to unfinished | Four CLI and fourteen selection-verifier tests pass; verifier audits initialized state independently and CLI maps its result directly |

Final discovery milestone review is clear after the known-failure precedence fix. Final full suite: **153 tests pass** (48 discovery-stage + prior 105). Separate client/selection review and final integration review records are in review/idea-json-backup-discovery-review-2026-11-03.md. Next action is Danu’s guided discover command from the [runbook](runbook.md); no live discovery was run automatically.
| Production batch/membership classifier | New classifier absent | Three tests pass: normal IDEA plus preferred other still matches, lost/deprecated-only tag is changed but retained, clean mixed missing/omitted neighbors held, maxlag retryable and malformed membership/warnings held |
| SQLite run/reservation journal | State module absent | Five offline state tests pass: verified frozen selection copy, DELETE/EXTRA/FK and lock, durable bounded reservations across reopen, explicit snapshots and missing/corrupt-journal stops |
| Parent-verified pilot scope | Pilot subset producer absent | Six tests pass: verified production parent copied unchanged, exact canonical subset, independent linkage audit, rejected synthetic/corrupt parent and no overwrite |
| Independent collection audit | Collection verifier absent | Four independent fixture tests pass for whole-source precision, metadata/scope/artifact corruption, rehashed bad item and stale-view precedence |
| Durable acceptance/source proof | Accept absent; completed source rewritable; finish transition blocked; nullable completeness lost; committed source eligible for refetch | Sixteen state tests pass; source-cache once per batch, orphan-item adoption, accepted/source audit, private intents and immutable accepted provenance |
| Collection receipt/history audit | Early retry/Retry-After evasion/non-maxlag retry/minimal finalized report were accepted; legitimate source-commit pause mislabeled failed | Seven independent collection tests pass with cooldowns, API summaries, finalized report shape and unfinished source transition |
| Production scheduler and local recovery | Production controller absent | Three real-journal synthetic tests pass: 55 QIDs in 50/5 batches with only init/end public snapshots, committed-source local recovery without refetch, and global lost-header hold for fresh QIDs |
| Recovered mixed server wait | Crash before global-cooldown commit let fresh QID dispatch at20s despite stronger HTTP-date30s | Four collector tests pass; every header becomes its own receipt-anchored deadline before taking the maximum |
| Graceful bounded pause/quota | max_batches pause waited through the retry cooldown before returning | Five controller tests pass; immediate pause retains persisted waits and the three-attempt quota survives repeated reopen |
| Finalization publication | Finalizer absent | Two tests pass: report-first/manifest-last, unchanged content sequence, passed-only immutable final phase, failed report remains collected |
| Collection outcome/recovery audit | Successful attempt could carry saving error; known-header recovered retry rejected | Eleven verifier tests pass, with recovered-at cooldown anchor, outcome/error coherence and membership/type regressions |
| Warning/error honesty | maxlag with warning retried; missing error message got invented fallback | Four classifier tests pass; warnings hold the whole batch and malformed API summary is retained as unresolved |
| Retry completion boundary | Advancing UTC exposed item/attempt retry eligibility before finished+5 seconds | Six controller tests pass; transient outcome is committed with one finish-based eligibility boundary while active reservation prevents early retries |
| Live monotonic cooldown | Collector had no monotonic guard/injection; wall-clock jump could skip relative server wait | Seven controller tests pass; live monotonic floor supplements persisted UTC deadline |
| Resume/finalization ordering | Resume ignored prepared report intent and left run collected | Eight controller tests pass; exact prepared finalization is completed before snapshots, acceptance or network |
| Explicit production commands | Pilot/collector/resume/finalizer handlers absent | Seven production CLI tests pass; parent-linked subset, explicit run kind, read-only audit vs --write and external-only report paths |
| Public payload ownership before resume | Fresh QID was dispatched despite unowned file in run | Nine controller tests pass; unexplained files/links hold before network, recovered attempt-owned diagnostic publications are registered without replacing bytes |
| Known-header interruption | Interrupted item was permanently held despite durable known receipt | Ten controller tests pass; operator resume may retry known-header incomplete capture after persisted floor, while lost-header global hold remains |
| Final independent audit guards | Symlinked .state, malformed nonvalue IDEA snak, warning retry and re-requested held QID were accepted | Sixteen collection audit tests pass; known-header interrupted history remains supported |
| Read-only status regression | Already GREEN, no manufactured failing test | Eight CLI tests pass; status reads authoritative pending counts without payload mutation or network handlers |
| Store review scope/path/source fixes | Internal staging symlink escaped; parent changed during copy split journal scope; distinct encoded-source corruption passed reopen | Nineteen state tests pass; anchored internal paths, chosen-copy byte match and once-per-batch encoded/framing/decode proof |
