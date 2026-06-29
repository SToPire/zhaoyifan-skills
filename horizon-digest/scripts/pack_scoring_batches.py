#!/usr/bin/env python3
import argparse
import math
from pathlib import Path
from typing import Any

from _common import clamp_text, load_items, write_json


def engagement(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "score",
        "descendants",
        "num_comments",
        "comment_count",
        "upvote_ratio",
        "stars_gained",
        "forks_gained",
        "pushes",
        "pull_requests",
        "discussion_url",
        "subreddit",
        "feed_name",
        "repo",
        "category",
    ]
    return {k: metadata[k] for k in keys if k in metadata and metadata[k] not in (None, "", [])}


def compact_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    content = item.get("content") or ""
    main = content
    comments = ""
    if "--- Top Comments ---" in content:
        main, comments = content.split("--- Top Comments ---", 1)
    return {
        "index": index,
        "id": item["id"],
        "title": item.get("title"),
        "source_type": item.get("source_type"),
        "author": item.get("author"),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "content_preview": clamp_text(main.strip(), 1200),
        "comments_preview": clamp_text(comments.strip(), 1500),
        "engagement": engagement(item.get("metadata") or {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack item scoring batches for agent judgment.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    items = load_items(args.items)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    batches = []
    total_batches = math.ceil(len(items) / args.batch_size) if items else 0
    for batch_index in range(total_batches):
        start = batch_index * args.batch_size
        chunk = items[start : start + args.batch_size]
        payload = {
            "batch_index": batch_index + 1,
            "batch_count": total_batches,
            "items": [compact_item(item, start + i) for i, item in enumerate(chunk)],
        }
        path = out_dir / f"batch-{batch_index + 1:03d}.json"
        write_json(path, payload)
        batches.append({"path": str(path), "count": len(chunk)})

    write_json(out_dir / "manifest.json", {"item_count": len(items), "batch_count": total_batches, "batches": batches})
    print(f"wrote {total_batches} scoring batches for {len(items)} items")


if __name__ == "__main__":
    main()
