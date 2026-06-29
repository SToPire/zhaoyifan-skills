#!/usr/bin/env python3
import argparse
import math
from pathlib import Path

from _common import clamp_text, load_items, write_json


def compact_item(item: dict, index: int) -> dict:
    content = item.get("content") or ""
    main = content
    comments = ""
    if "--- Top Comments ---" in content:
        main, comments = content.split("--- Top Comments ---", 1)
    return {
        "index": index,
        "id": item["id"],
        "title": item.get("title"),
        "url": item.get("url"),
        "source_type": item.get("source_type"),
        "published_at": item.get("published_at"),
        "ai_score": item.get("ai_score"),
        "ai_reason": item.get("ai_reason"),
        "ai_summary": item.get("ai_summary"),
        "ai_tags": item.get("ai_tags") or [],
        "content": clamp_text(main.strip(), 4000),
        "comments": clamp_text(comments.strip(), 2000),
        "metadata": item.get("metadata") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack filtered items for enrichment.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")

    items = load_items(args.items)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_count = math.ceil(len(items) / args.batch_size) if items else 0
    batches = []
    for i in range(batch_count):
        start = i * args.batch_size
        chunk = items[start : start + args.batch_size]
        payload = {
            "batch_index": i + 1,
            "batch_count": batch_count,
            "items": [compact_item(item, start + offset) for offset, item in enumerate(chunk)],
        }
        path = out_dir / f"batch-{i + 1:03d}.json"
        write_json(path, payload)
        batches.append({"path": str(path), "count": len(chunk)})
    write_json(out_dir / "manifest.json", {"item_count": len(items), "batch_count": batch_count, "batches": batches})
    print(f"wrote {batch_count} enrichment batches for {len(items)} items")


if __name__ == "__main__":
    main()
