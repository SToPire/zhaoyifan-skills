#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from _common import load_json, write_json, write_json_atomic


DEFAULT_MAX_COMMITS = 8
DEFAULT_MAX_CHARS = 90_000
MAX_BATCH_PATCH_CHARS = 60_000


def compact_commit(commit: dict[str, Any]) -> dict[str, Any]:
    compact = copy.deepcopy(commit)
    patch = str(compact.get("patch") or "")
    if compact.get("merge_context_only") and not patch:
        compact["patch_omitted_reason"] = "merge commit has no combined resolution diff"
    elif len(patch) > MAX_BATCH_PATCH_CHARS:
        compact["patch"] = patch[:MAX_BATCH_PATCH_CHARS].rstrip() + "\n\n[patch truncated for analysis batch]"
        compact["patch_truncated_for_batch"] = True
    return compact


def serialized_size(repo: dict[str, Any], commits: list[dict[str, Any]]) -> int:
    payload = {
        "repository": repo,
        "commits": commits,
    }
    return len(json.dumps(payload, ensure_ascii=False, indent=2)) + 1


def truncate_text_field_to_fit(
    repo: dict[str, Any],
    commit: dict[str, Any],
    field: str,
    flag: str,
    marker: str,
    max_chars: int,
) -> None:
    original = str(commit.get(field) or "")
    if not original:
        return
    commit[flag] = True
    commit[field] = ""
    if serialized_size(repo, [commit]) > max_chars:
        return
    low = 0
    high = len(original)
    best = ""
    while low <= high:
        midpoint = (low + high) // 2
        candidate = original[:midpoint].rstrip()
        if midpoint < len(original):
            candidate += marker
        commit[field] = candidate
        if serialized_size(repo, [commit]) <= max_chars:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    commit[field] = best


def truncate_files_to_fit(
    repo: dict[str, Any],
    commit: dict[str, Any],
    max_chars: int,
) -> None:
    original = commit.get("files")
    if not isinstance(original, list) or not original:
        return
    total = len(original)
    commit["files"] = []
    commit["files_truncated_for_batch"] = {"shown": 0, "total": total}
    if serialized_size(repo, [commit]) > max_chars:
        return
    low = 0
    high = total
    best = 0
    while low <= high:
        midpoint = (low + high) // 2
        commit["files"] = original[:midpoint]
        commit["files_truncated_for_batch"]["shown"] = midpoint
        if serialized_size(repo, [commit]) <= max_chars:
            best = midpoint
            low = midpoint + 1
        else:
            high = midpoint - 1
    commit["files"] = original[:best]
    commit["files_truncated_for_batch"]["shown"] = best


def fit_single_commit(
    repo: dict[str, Any],
    commit: dict[str, Any],
    max_chars: int,
) -> dict[str, Any]:
    fitted = copy.deepcopy(commit)
    if serialized_size(repo, [fitted]) <= max_chars:
        return fitted

    truncate_text_field_to_fit(
        repo,
        fitted,
        "patch",
        "patch_truncated_for_batch",
        "\n\n[patch truncated for analysis batch]",
        max_chars,
    )
    if not fitted.get("patch") and commit.get("patch"):
        fitted["patch_omitted_reason"] = "omitted to satisfy analysis batch size limit"
    if serialized_size(repo, [fitted]) <= max_chars:
        return fitted

    truncate_files_to_fit(repo, fitted, max_chars)
    if serialized_size(repo, [fitted]) <= max_chars:
        return fitted

    truncate_text_field_to_fit(
        repo,
        fitted,
        "message",
        "message_truncated_for_batch",
        "\n\n[commit message truncated for analysis batch]",
        max_chars,
    )
    if serialized_size(repo, [fitted]) <= max_chars:
        return fitted

    if fitted.get("trailers"):
        fitted["trailers"] = {}
        fitted["trailers_omitted_for_batch"] = True
    for field in ("author", "committer"):
        identity = fitted.get(field)
        if isinstance(identity, dict):
            fitted[field] = {"date": identity.get("date")}
            fitted["identities_truncated_for_batch"] = True
    if serialized_size(repo, [fitted]) <= max_chars:
        return fitted

    truncate_text_field_to_fit(
        repo,
        fitted,
        "subject",
        "subject_truncated_for_batch",
        " [subject truncated]",
        max_chars,
    )
    if serialized_size(repo, [fitted]) <= max_chars:
        return fitted
    raise ValueError(
        f"commit {commit.get('id', '<unknown>')} cannot fit within --max-chars={max_chars}"
    )


def truncation_record(repository: dict[str, Any], commit: dict[str, Any]) -> dict[str, Any] | None:
    fields = {
        "patch": bool(commit.get("patch_truncated_for_batch")),
        "files": commit.get("files_truncated_for_batch"),
        "message": bool(commit.get("message_truncated_for_batch")),
        "trailers": bool(commit.get("trailers_omitted_for_batch")),
        "identities": bool(commit.get("identities_truncated_for_batch")),
        "subject": bool(commit.get("subject_truncated_for_batch")),
    }
    if not any(fields.values()):
        return None
    return {
        "repository_id": repository.get("id"),
        "commit_id": commit.get("id"),
        **fields,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack fetched commits into bounded analysis batches.")
    parser.add_argument("--input", required=True, help="raw_commits.json path")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--meta", required=True, help="meta.json path to update with analysis truncations")
    parser.add_argument("--max-commits", type=int, default=DEFAULT_MAX_COMMITS)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()

    if args.max_commits <= 0 or args.max_chars <= 0:
        raise ValueError("batch limits must be positive")
    payload = load_json(args.input)
    if not isinstance(payload, dict) or not isinstance(payload.get("repositories"), list):
        raise ValueError("input must be a raw_commits object with a repositories array")
    meta = load_json(args.meta)
    if not isinstance(meta, dict) or not isinstance(meta.get("warnings"), list):
        raise ValueError("meta.json must be an object with a warnings array")

    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"output directory must be empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    index: list[dict[str, Any]] = []
    batch_outputs: list[tuple[Path, dict[str, Any]]] = []
    analysis_truncations: list[dict[str, Any]] = []
    sequence = 1
    for repository in payload["repositories"]:
        if repository.get("status") != "success":
            continue
        repo_context = {
            "id": repository.get("id"),
            "name": repository.get("name"),
            "project_name": repository.get("project_name") or repository.get("name"),
            "url": repository.get("url"),
            "branch": repository.get("branch"),
            "first_run": repository.get("first_run", False),
            "force_push": repository.get("force_push", False),
        }
        commits = [
            fit_single_commit(repo_context, compact_commit(commit), args.max_chars)
            for commit in repository.get("commits", [])
        ]
        for commit in commits:
            record = truncation_record(repository, commit)
            if record:
                analysis_truncations.append(record)
        current: list[dict[str, Any]] = []
        for commit in commits:
            candidate = [*current, commit]
            if current and (
                len(candidate) > args.max_commits
                or serialized_size(repo_context, candidate) > args.max_chars
            ):
                filename = f"{sequence:04d}-{repository['name']}.json"
                batch_outputs.append(
                    (out_dir / filename, {"repository": repo_context, "commits": current})
                )
                index.append(
                    {
                        "file": filename,
                        "repository_id": repository["id"],
                        "commit_ids": [item["id"] for item in current],
                    }
                )
                sequence += 1
                current = [commit]
            else:
                current = candidate
        if current:
            filename = f"{sequence:04d}-{repository['name']}.json"
            batch_outputs.append(
                (out_dir / filename, {"repository": repo_context, "commits": current})
            )
            index.append(
                {
                    "file": filename,
                    "repository_id": repository["id"],
                    "commit_ids": [item["id"] for item in current],
                }
            )
            sequence += 1

    for path, batch in batch_outputs:
        write_json(path, batch)
    write_json(out_dir / "index.json", {"batches": index})
    meta["analysis_truncations"] = analysis_truncations
    if analysis_truncations:
        meta["warnings"].append(
            f"{len(analysis_truncations)} commit(s) had evidence truncated for analysis batches"
        )
    write_json_atomic(args.meta, meta)
    print(json.dumps({"batch_count": len(index)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
