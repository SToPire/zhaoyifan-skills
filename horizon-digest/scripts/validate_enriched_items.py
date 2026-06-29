#!/usr/bin/env python3
import argparse
from typing import Any

from _common import extract_items, load_items, load_json, write_json


FIELDS = [
    "title_zh",
    "detailed_summary_zh",
    "background_zh",
    "community_discussion_zh",
    "title_en",
    "detailed_summary_en",
    "background_en",
    "community_discussion_en",
]


def normalize_sources(value: Any) -> list[dict[str, str]]:
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("sources must be a list")
    out = []
    for row in value:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or url).strip()
        if url:
            out.append({"title": title, "url": url})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and merge agent-written enrichment into items.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--enrichment", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--language", choices=("en", "zh"))
    args = parser.parse_args()

    items = load_items(args.items)
    rows = extract_items(load_json(args.enrichment))
    by_id = {item["id"]: dict(item) for item in items}
    seen: set[str] = set()
    errors: list[str] = []

    for row in rows:
        item_id = row.get("id")
        if item_id not in by_id:
            errors.append(f"unknown id: {item_id}")
            continue
        if item_id in seen:
            errors.append(f"duplicate enrichment id: {item_id}")
            continue
        seen.add(item_id)
        if args.language:
            required_pairs = [(f"title_{args.language}", f"detailed_summary_{args.language}")]
        else:
            required_pairs = [("title_zh", "detailed_summary_zh"), ("title_en", "detailed_summary_en")]
        if not any(
            str(row.get(title_field) or "").strip() and str(row.get(summary_field) or "").strip()
            for title_field, summary_field in required_pairs
        ):
            if args.language:
                title_field, summary_field = required_pairs[0]
                if not str(row.get(title_field) or "").strip():
                    errors.append(f"{item_id}: missing {title_field}")
                if not str(row.get(summary_field) or "").strip():
                    errors.append(f"{item_id}: missing {summary_field}")
            else:
                errors.append(f"{item_id}: missing a complete zh or en title/summary pair")
        item = by_id[item_id]
        metadata = dict(item.get("metadata") or {})
        for field in FIELDS:
            if field in row:
                metadata[field] = str(row.get(field) or "").strip()
        try:
            sources = normalize_sources(row.get("sources"))
        except ValueError as exc:
            errors.append(f"{item_id}: {exc}")
            sources = []
        if sources:
            metadata["sources"] = sources
        item["metadata"] = metadata

    missing = sorted(set(by_id) - seen)
    if missing:
        errors.append(f"missing enrichment for {len(missing)} items: {', '.join(missing[:10])}")
    if errors:
        raise SystemExit("\n".join(errors))

    enriched = [by_id[item["id"]] for item in items]
    write_json(args.out, enriched)
    print(f"validated {len(enriched)} enriched items")


if __name__ == "__main__":
    main()
