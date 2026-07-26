#!/usr/bin/env python3
import argparse
from typing import Any

from _common import extract_items, load_items, load_json, write_json


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("ai_tags must be a list")
    tags = []
    for tag in value:
        text = str(tag).strip().lower().lstrip("#")
        if text and text not in tags:
            tags.append(text)
    return tags


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and merge agent-written scores into items.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    items = load_items(args.items)
    score_rows = extract_items(load_json(args.scores))
    by_id = {item["id"]: dict(item) for item in items}
    seen: set[str] = set()
    errors: list[str] = []

    for row in score_rows:
        item_id = row.get("id")
        if item_id not in by_id:
            errors.append(f"unknown id: {item_id}")
            continue
        if item_id in seen:
            errors.append(f"duplicate score id: {item_id}")
            continue
        seen.add(item_id)
        try:
            score = float(row.get("ai_score"))
        except (TypeError, ValueError):
            errors.append(f"{item_id}: ai_score must be numeric")
            continue
        if not 0 <= score <= 10:
            errors.append(f"{item_id}: ai_score out of range")
            continue
        reason = str(row.get("ai_reason") or "").strip()
        summary = str(row.get("ai_summary") or "").strip()
        if not reason:
            errors.append(f"{item_id}: missing ai_reason")
        if not summary:
            errors.append(f"{item_id}: missing ai_summary")
        try:
            tags = normalize_tags(row.get("ai_tags"))
        except ValueError as exc:
            errors.append(f"{item_id}: {exc}")
            tags = []
        item = by_id[item_id]
        item["ai_score"] = score
        item["ai_reason"] = reason
        item["ai_summary"] = summary
        item["ai_tags"] = tags

    missing = sorted(set(by_id) - seen)
    if missing:
        errors.append(f"missing scores for {len(missing)} items: {', '.join(missing[:10])}")
    if errors:
        raise SystemExit("\n".join(errors))

    scored = [by_id[item["id"]] for item in items]
    write_json(args.out, scored)
    print(f"validated {len(scored)} scored items")


if __name__ == "__main__":
    main()
