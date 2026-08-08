#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from _common import load_json, write_json


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def text_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{label} must be a {'possibly empty ' if allow_empty else 'non-empty '}string array")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{label} must contain only non-empty strings")
    return [item.strip() for item in value]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate grouped repository digest JSON.")
    parser.add_argument("--commits", required=True, help="analyzed_commits.json path")
    parser.add_argument("--digest", required=True, help="Agent-written digest.json path")
    parser.add_argument("--out", required=True, help="Output validated_digest.json path")
    args = parser.parse_args()

    commits_payload = load_json(args.commits)
    digest_payload = load_json(args.digest)
    if not isinstance(commits_payload, dict) or not isinstance(commits_payload.get("repositories"), list):
        raise ValueError("commits input must contain a repositories array")
    if not isinstance(digest_payload, dict):
        raise ValueError("digest must be a JSON object")

    expected_by_repo: dict[str, set[str]] = {}
    for repository in commits_payload["repositories"]:
        if repository.get("status") != "success" or not repository.get("commits"):
            continue
        repo_id = repository.get("id")
        if not isinstance(repo_id, str):
            raise ValueError("repository is missing its id")
        for commit in repository["commits"]:
            if not isinstance(commit.get("analysis"), dict):
                raise ValueError(f"commit {commit.get('id')!r} is missing its validated analysis")
        expected_by_repo[repo_id] = {commit["id"] for commit in repository["commits"]}

    overview = text_list(digest_payload.get("overview", []), "overview", allow_empty=True)
    if expected_by_repo and not overview:
        raise ValueError("overview must not be empty when commits were fetched")
    repositories = digest_payload.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("digest repositories must be an array")

    normalized_repositories: list[dict[str, Any]] = []
    seen_repositories: set[str] = set()
    for repository in repositories:
        if not isinstance(repository, dict):
            raise ValueError("each digest repository must be an object")
        repo_id = text(repository.get("id"), "repository id")
        if repo_id in seen_repositories:
            raise ValueError(f"duplicate digest repository: {repo_id}")
        if repo_id not in expected_by_repo:
            raise ValueError(f"digest references an unknown or unchanged repository: {repo_id}")
        seen_repositories.add(repo_id)
        repo_overview = text(repository.get("overview"), f"repository {repo_id} overview")
        groups = repository.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"repository {repo_id} requires at least one change group")

        normalized_groups: list[dict[str, Any]] = []
        covered: list[str] = []
        for index, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                raise ValueError(f"repository {repo_id} group {index} must be an object")
            commit_ids = text_list(group.get("commit_ids"), f"repository {repo_id} group {index} commit_ids")
            unknown = sorted(set(commit_ids) - expected_by_repo[repo_id])
            if unknown:
                raise ValueError(f"repository {repo_id} group {index} references unknown commits: {unknown}")
            covered.extend(commit_ids)
            normalized_groups.append(
                {
                    "title": text(group.get("title"), f"repository {repo_id} group {index} title"),
                    "purpose": text(group.get("purpose"), f"repository {repo_id} group {index} purpose"),
                    "changes": text_list(group.get("changes"), f"repository {repo_id} group {index} changes"),
                    "impact": text(group.get("impact"), f"repository {repo_id} group {index} impact"),
                    "commit_ids": commit_ids,
                }
            )
        duplicates = sorted({item for item in covered if covered.count(item) > 1})
        if duplicates:
            raise ValueError(f"repository {repo_id} lists commits more than once: {duplicates}")
        missing = sorted(expected_by_repo[repo_id] - set(covered))
        if missing:
            raise ValueError(f"repository {repo_id} omits commits: {missing}")
        normalized_repositories.append(
            {"id": repo_id, "overview": repo_overview, "groups": normalized_groups}
        )

    missing_repositories = sorted(set(expected_by_repo) - seen_repositories)
    if missing_repositories:
        raise ValueError(f"digest omits repositories with commits: {missing_repositories}")
    write_json(args.out, {"overview": overview, "repositories": normalized_repositories})
    print(
        json.dumps(
            {
                "validated_repository_count": len(normalized_repositories),
                "validated_commit_count": sum(len(items) for items in expected_by_repo.values()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
