from collections import Counter, defaultdict

RowType = dict[str, str | int | float | None]


def count_item_occurrences(
    normalized_rows: list[RowType],
    row_indices: list[int] | None = None,
) -> Counter[object]:
    counts: Counter[object] = Counter()
    indices = row_indices if row_indices is not None else list(range(len(normalized_rows)))

    for idx in indices:
        item_value = normalized_rows[idx].get("item")
        if item_value is not None:
            counts[item_value] += 1

    return counts


def group_duplicate_item_row_indices(
    normalized_rows: list[RowType],
    row_indices: list[int] | None = None,
) -> list[list[int]]:
    item_rows: dict[object, list[int]] = defaultdict(list)
    indices = row_indices if row_indices is not None else list(range(len(normalized_rows)))

    for idx in indices:
        item_value = normalized_rows[idx].get("item")
        if item_value is not None:
            item_rows[item_value].append(idx)

    return [indices for indices in item_rows.values() if len(indices) > 1]


def get_duplicate_item_row_indices(
    normalized_rows: list[RowType],
    row_indices: list[int] | None = None,
) -> list[int]:
    duplicate_indices = {
        idx
        for group_indices in group_duplicate_item_row_indices(
            normalized_rows,
            row_indices=row_indices,
        )
        for idx in group_indices
    }
    return sorted(duplicate_indices)
