# MVP implementation checkpoints

On 2026-11-02 Danu authorized automatic offline RED → GREEN → commit increments until the MVP is complete. This supersedes the earlier guided execution choice within the MVP only. No live retrieval, full discovery, production recovery, deposit or push is authorized.

Each checkpoint records the newly observed failure before implementation. Reused behavior that already passes is regression coverage, not a fabricated RED. Separate preservation/transport reviews and an integrated review precede MVP completion.

| Increment | RED observed | GREEN validation |
| --- | --- | --- |
| Item shape/type | Non-object values raised AttributeError; non-item types were accepted | Five focused preservation/contract tests pass |
| Revision metadata | Eleven invalid revision/time examples were accepted | Two contract tests pass, including all metadata cases |
