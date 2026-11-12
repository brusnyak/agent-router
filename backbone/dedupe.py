"""Drop duplicate rows by (kind, name.lower()), keeping within each group the row
with the longest body and, on ties, the row with the smallest id. Returns the set
of ids to drop."""

def drop_ids(rows):
    groups = {}
    for row in rows:
        key = (row["kind"], row["name"].lower())
        groups.setdefault(key, []).append(row)

    keep = set()
    for group in groups.values():
        best = min(group, key=lambda r: (-len(r["body"]), r["id"]))
        keep.add(best["id"])

    return {row["id"] for row in rows} - keep
