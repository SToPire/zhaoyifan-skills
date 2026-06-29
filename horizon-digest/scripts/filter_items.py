#!/usr/bin/env python3
import argparse
from collections import defaultdict
from typing import Any

from _common import load_config, load_items, write_json


def category_group(item: dict[str, Any], category_to_group: dict[str, str], default_group: str) -> str:
    category = (item.get("metadata") or {}).get("category")
    if isinstance(category, str) and category in category_to_group:
        return category_to_group[category]
    return default_group


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply score threshold, category quotas, and max item cap.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--items", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--max-items", type=int)
    args = parser.parse_args()

    config = load_config(args.config)
    filtering = config.get("filtering", {}) or {}
    threshold = args.threshold if args.threshold is not None else float(filtering.get("ai_score_threshold", 7.0))
    max_items = args.max_items if args.max_items is not None else filtering.get("max_items")
    max_items = int(max_items) if max_items is not None else None
    groups = filtering.get("category_groups", {}) or {}
    default_group = filtering.get("default_group", "other")
    default_limit = filtering.get("default_group_limit")
    default_limit = int(default_limit) if default_limit is not None else None

    category_to_group: dict[str, str] = {}
    for group_key, group in groups.items():
        for category in group.get("categories", []) or []:
            category_to_group.setdefault(str(category), str(group_key))

    candidates = [
        item
        for item in load_items(args.items)
        if item.get("ai_score") is not None and float(item.get("ai_score") or 0) >= threshold
    ]
    candidates.sort(key=lambda item: float(item.get("ai_score") or 0), reverse=True)

    selected: list[dict[str, Any]] = []
    group_counts: dict[str, int] = defaultdict(int)
    for item in candidates:
        group_key = category_group(item, category_to_group, default_group)
        if group_key in groups:
            limit_value = groups[group_key].get("limit", default_limit)
            limit = int(limit_value) if limit_value is not None else None
        else:
            limit = default_limit
        if limit is not None and group_counts[group_key] >= limit:
            continue
        selected.append(item)
        group_counts[group_key] += 1
        if max_items is not None and len(selected) >= max_items:
            break

    write_json(args.out, selected)
    print(f"filtered {len(candidates)} candidates >= {threshold} to {len(selected)} selected")


if __name__ == "__main__":
    main()
