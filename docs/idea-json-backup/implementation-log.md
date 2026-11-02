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
