def read_requested_qids(path):
    with path.open(encoding="utf-8", newline=None) as source:
        qids = [line.removesuffix("\n") for line in source]

    seen = set()

    for line_number, qid in enumerate(qids, start=1):
        if qid == "":
            raise ValueError(f"Line {line_number}: blank QID line")

        # prefix check
        if not qid.startswith("Q"):
            raise ValueError(
                f"Line {line_number}: expected uppercase Q prefix, got {qid!r}"
            )

        # numeric part check
        numeric_part = qid[1:]
        if not (numeric_part.isascii() and numeric_part.isdigit()):
            raise ValueError(
                f"Line {line_number}: expected digits after Q, got {qid!r}"
            )

        # duplicate qid check
        if qid in seen:
            raise ValueError(
                f"Line {line_number}: duplicate QID {qid!r}"
            )
        seen.add(qid)

    return qids