#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from typing import Any

from _common import extract_items, load_json, write_json


CATEGORIES = {
    "feature",
    "fix",
    "refactor",
    "performance",
    "test",
    "docs",
    "build",
    "dependency",
    "cleanup",
    "merge",
    "other",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}


def require_text(item: dict[str, Any], field: str, item_id: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"analysis {item_id!r} requires non-empty {field}")
    return value.strip()


def normalize_analysis(item: dict[str, Any]) -> dict[str, Any]:
    item_id = require_text(item, "id", "<unknown>")
    purpose = require_text(item, "purpose", item_id)
    impact = require_text(item, "impact", item_id)
    category = require_text(item, "category", item_id).lower()
    if category not in CATEGORIES:
        raise ValueError(f"analysis {item_id!r} has unsupported category {category!r}")
    subsystem = item.get("subsystem", "")
    if not isinstance(subsystem, str):
        raise ValueError(f"analysis {item_id!r} subsystem must be a string")
    confidence = require_text(item, "confidence", item_id).lower()
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"analysis {item_id!r} has unsupported confidence {confidence!r}")
    changes = item.get("changes")
    if (
        not isinstance(changes, list)
        or not changes
        or not all(isinstance(value, str) and value.strip() for value in changes)
    ):
        raise ValueError(f"analysis {item_id!r} changes must be a non-empty string array")
    return {
        "purpose": purpose,
        "changes": [value.strip() for value in changes],
        "impact": impact,
        "category": category,
        "subsystem": subsystem.strip(),
        "confidence": confidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate agent-written per-commit analyses.")
    parser.add_argument("--commits", required=True, help="raw_commits.json path")
    parser.add_argument("--analyses", required=True, help="Agent-written analyses.json path")
    parser.add_argument("--out", required=True, help="Output analyzed_commits.json path")
    args = parser.parse_args()

    raw = load_json(args.commits)
    if not isinstance(raw, dict) or not isinstance(raw.get("repositories"), list):
        raise ValueError("commits input must contain a repositories array")
    expected: dict[str, dict[str, Any]] = {}
    for repository in raw["repositories"]:
        for commit in repository.get("commits", []):
            commit_id = commit.get("id")
            if not isinstance(commit_id, str) or commit_id in expected:
                raise ValueError("raw commits contain a missing or duplicate commit id")
            expected[commit_id] = commit

    analyses = extract_items(load_json(args.analyses))
    normalized: dict[str, dict[str, Any]] = {}
    for analysis in analyses:
        item_id = analysis.get("id")
        if not isinstance(item_id, str):
            raise ValueError("every analysis requires an id")
        if item_id in normalized:
            raise ValueError(f"duplicate analysis id: {item_id}")
        if item_id not in expected:
            raise ValueError(f"analysis references unknown commit id: {item_id}")
        normalized[item_id] = normalize_analysis(analysis)

    missing = sorted(set(expected) - set(normalized))
    if missing:
        raise ValueError(f"missing analyses for {len(missing)} commits: {', '.join(missing[:5])}")

    output = copy.deepcopy(raw)
    for repository in output["repositories"]:
        for commit in repository.get("commits", []):
            commit["analysis"] = normalized[commit["id"]]
    write_json(args.out, output)
    print(json.dumps({"validated_commit_count": len(normalized)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
