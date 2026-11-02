# MVP implementation checkpoints

On 2026-11-02 Danu authorized automatic offline RED → GREEN → commit increments until the MVP is complete. This supersedes the earlier guided execution choice within the MVP only. No live retrieval, full discovery, production recovery, deposit or push is authorized.

Each checkpoint records the newly observed failure before implementation. Reused behavior that already passes is regression coverage, not a fabricated RED. Separate preservation/transport reviews and an integrated review precede MVP completion.

| Increment | RED observed | GREEN validation |
| --- | --- | --- |
| Item shape/type | Non-object values raised AttributeError; non-item types were accepted | Five focused preservation/contract tests pass |
| Revision metadata | Eleven invalid revision/time examples were accepted | Two contract tests pass, including all metadata cases |
| One HTTP capture | New transport module absent (import failure) | Ten offline tests pass for request settings, gzip, framing, errors and redirects |
| Scope and response preflight | Invalid lists created output; API/error/warning wrappers were accepted or raised wrong exceptions | Four contract tests pass; rejected responses retained, invalid scope creates no output |
| Independent verifier | New verifier module absent (import failure) | Seven tests pass with independently built artifacts, including changed content with recomputed hashes, token/type changes and unsafe paths |
| Prototype manifest | New provenance argument/manifest absent (three TypeErrors) | Synthetic complete and partial runs independently checked; all 33 MVP tests pass including number-token regression |
| Interruption/no-overwrite regression | Already GREEN: existing durable manifest/fresh-directory behavior reused; no fabricated failure | Five manifest tests pass; interruption retains accepted item and full unfinished scope, repeat invocation changes no bytes |
| Supervised total deadline | Missing capture_batch import, missing persistent capture argument, and close error masked evidence | Seventeen offline transport tests pass; blocked worker terminated, timeout/interruption evidence retained in caller-owned folder |
| Single-batch orchestration | Collector module absent; decimal deadline metadata also exposed entity-codec float rejection | Three collection tests pass for compressed success, HTTP/API/incomplete failure and retained interruption evidence; entity JSON still uses lossless codec |
| Receipt verification review fix | Arbitrary live evidence and nineteen receipt/body tamper examples were accepted | Twelve verifier tests pass; live/synthetic transport receipts independently checked against request, encoded bytes and decoded source |
| Usable prototype commands | New command module absent (import failure) | Two offline CLI tests pass: saved/synthetic preservation + verification, and collect wiring with mocked capture only |
| Transport review fixes | Duplicate framing headers and exited worker finishing after parent deadline were accepted | Twenty-one transport tests pass; duplicate headers retained/rejected and parent deadline rechecked after join |
| Exact QID line boundaries | Vertical-tab and Unicode-line-separator suffixes were silently stripped and accepted | Three CLI tests pass; only ordinary file line terminators delimit QIDs |
| Structured gzip verification failures | Truncated trailer raised EOFError; damaged deflate raised zlib.error after refreshed descriptors | Thirteen verifier tests pass; decoder errors return structured failed findings |
| Integrated worker regression | Already GREEN: composed existing capture/preservation/verification behavior without fabricating a failure | Spawned synthetic worker, gzip spool, collector and independent verifier pass together |

Separate preservation and transport milestone reviews and a final integrated review are clear. The final integrated review independently exercised streamed gzip, supplied QID order and exact numeric preservation. Final full validation: `python3 -B -m unittest discover -s tests -q` passed **105 tests** (54 MVP, 51 historical sample). See [runbook](mvp-runbook.md) and [local review record](../../review/idea-json-backup-mvp-review-2026-11-02.md). MVP complete; no live data, deposit, production expansion or push performed.
