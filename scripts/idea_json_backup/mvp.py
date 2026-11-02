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
        returned_qid = entity.get("id")

        if returned_qid != qid:
            raise ValueError(
                f"Requested {qid}, but entity ID is {returned_qid!r}"
            )

        (items_dir / f"{qid}.json").write_text(
            dumps(entity),
            encoding="utf-8",
        )
