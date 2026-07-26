#!/usr/bin/env python3
import argparse
from typing import Any

from _common import load_items, load_json, write_json


def resolve_ref(ref: Any, items: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> str | None:
    if isinstance(ref, int):
        if 0 <= ref < len(items):
            return str(items[ref]["id"])
        return None
    text = str(ref)
    return text if text in by_id else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply agent-written topic duplicate groups.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--duplicates", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    items = load_items(args.items)
    by_id = {str(item["id"]): item for item in items}
    payload = load_json(args.duplicates)
    groups = payload.get("duplicates", []) if isinstance(payload, dict) else []
    if not isinstance(groups, list):
        raise SystemExit("duplicates must be a list")

    drop: set[str] = set()
    for group in groups:
        if not isinstance(group, list) or len(group) < 2:
            continue
        primary_id = resolve_ref(group[0], items, by_id)
        if not primary_id:
            continue
        primary = by_id[primary_id]
        content = primary.get("content") or ""
        metadata = dict(primary.get("metadata") or {})
        merged_ids = set(metadata.get("topic_duplicate_ids") or [])
        for ref in group[1:]:
            dup_id = resolve_ref(ref, items, by_id)
            if not dup_id or dup_id == primary_id:
                continue
            dup = by_id[dup_id]
            drop.add(dup_id)
            merged_ids.add(dup_id)
            dup_content = dup.get("content") or ""
            if dup_content and dup_content not in content:
                label = dup.get("source_type") or "source"
                content = (content + f"\n\n--- Topic duplicate from {label} ---\n" + dup_content).strip()
        metadata["topic_duplicate_ids"] = sorted(merged_ids)
        primary["content"] = content
        primary["metadata"] = metadata

    out = [item for item in items if str(item["id"]) not in drop]
    write_json(args.out, out)
    print(f"topic dedup {len(items)} -> {len(out)}")


if __name__ == "__main__":
    main()
