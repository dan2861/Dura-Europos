from pathlib import Path

from scripts.sample_backup.jsoncodec import dumps, loads


def preserve_batch(response_body, requested_qids, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True)

    (output_dir / "source.json").write_bytes(response_body)

    response = loads(response_body)
    items_dir = output_dir / "items"
    items_dir.mkdir()

    for qid in requested_qids:
        if qid not in response["entities"]:
            raise ValueError(f"Requested {qid} is missing from response entities")

        entity = response["entities"][qid]
        if not isinstance(entity, dict):
            raise ValueError(f"Requested {qid} must be an item object")
        returned_qid = entity.get("id")

        if returned_qid != qid:
            raise ValueError(
                f"Requested {qid}, but entity ID is {returned_qid!r}"
            )

        if "missing" in entity:
            raise ValueError(f"Requested {qid} is unavailable: missing_or_redirect")

        if entity.get("type") != "item":
            raise ValueError(f"Requested {qid} must have type=item")

        (items_dir / f"{qid}.json").write_text(
            dumps(entity),
            encoding="utf-8",
        )
