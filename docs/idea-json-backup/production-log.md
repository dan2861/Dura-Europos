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
