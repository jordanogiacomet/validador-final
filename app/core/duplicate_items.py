from collections import Counter, defaultdict
from collections.abc import Callable

RowType = dict[str, str | int | float | None]
CancellationCheckpoint = Callable[[], None]
CHECKPOINT_INTERVAL = 1000


def _maybe_run_checkpoint(
    checkpoint: CancellationCheckpoint | None,
    offset: int,
) -> None:
    if checkpoint is not None and offset % CHECKPOINT_INTERVAL == 0:
        checkpoint()


def count_item_occurrences(
    normalized_rows: list[RowType],
    row_indices: list[int] | None = None,
    checkpoint: CancellationCheckpoint | None = None,
) -> Counter[object]:
    counts: Counter[object] = Counter()
    indices = row_indices if row_indices is not None else list(range(len(normalized_rows)))

    for offset, idx in enumerate(indices):
        _maybe_run_checkpoint(checkpoint, offset)
        item_value = normalized_rows[idx].get("item")
        if item_value is not None:
            counts[item_value] += 1

    if checkpoint is not None:
        checkpoint()
    return counts


def group_duplicate_item_row_indices(
    normalized_rows: list[RowType],
    row_indices: list[int] | None = None,
    checkpoint: CancellationCheckpoint | None = None,
) -> list[list[int]]:
    item_rows: dict[object, list[int]] = defaultdict(list)
    indices = row_indices if row_indices is not None else list(range(len(normalized_rows)))

    for offset, idx in enumerate(indices):
        _maybe_run_checkpoint(checkpoint, offset)
        item_value = normalized_rows[idx].get("item")
        if item_value is not None:
            item_rows[item_value].append(idx)

    if checkpoint is not None:
        checkpoint()
    return [indices for indices in item_rows.values() if len(indices) > 1]


def get_duplicate_item_row_indices(
    normalized_rows: list[RowType],
    row_indices: list[int] | None = None,
    checkpoint: CancellationCheckpoint | None = None,
) -> list[int]:
    duplicate_indices = {
        idx
        for group_indices in group_duplicate_item_row_indices(
            normalized_rows,
            row_indices=row_indices,
            checkpoint=checkpoint,
        )
        for idx in group_indices
    }
    if checkpoint is not None:
        checkpoint()
    return sorted(duplicate_indices)
