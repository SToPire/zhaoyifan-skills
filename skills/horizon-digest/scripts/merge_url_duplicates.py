#!/usr/bin/env python3
import argparse
import urllib.parse
from typing import Any

from _common import load_items, write_json


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url))
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    normalized = f"{host}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    if parsed.fragment:
        normalized += f"#{parsed.fragment}"
    return normalized


def merge_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(normalize_url(item.get("url", "")), []).append(item)

    merged: list[dict[str, Any]] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        primary = max(group, key=lambda x: len(str(x.get("content") or "")))
        metadata = dict(primary.get("metadata") or {})
        sources = set()
        content = primary.get("content") or ""
        for item in group:
            sources.add(str(item.get("source_type") or "unknown"))
            for key, value in (item.get("metadata") or {}).items():
                if key not in metadata or metadata[key] in (None, "", []):
                    metadata[key] = value
            if item is not primary and item.get("content") and item["content"] not in content:
                label = item.get("source_type") or "source"
                content = (content + f"\n\n--- From {label} ---\n" + item["content"]).strip()
        metadata["merged_sources"] = sorted(sources)
        clone = dict(primary)
        clone["content"] = content
        clone["metadata"] = metadata
        merged.append(clone)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge items that point to the same normalized URL.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    items = load_items(args.items)
    merged = merge_items(items)
    write_json(args.out, merged)
    print(f"merged {len(items)} -> {len(merged)}")


if __name__ == "__main__":
    main()
