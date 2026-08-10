#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from _common import (
    OBJECT_ID_RE,
    cache_directory_name,
    exclusive_file_lock,
    load_config,
    load_state,
    repository_id,
    repository_name,
    run_git,
    run_git_stdout_limited,
    utc_now,
    write_json,
    write_json_atomic,
)
from _finalize import recover_finalization


INITIAL_BACKFILL_HOURS = 24
MAX_PATCH_BYTES = 120_000
MAX_COMMIT_MESSAGE_BYTES = 128_000
MAX_PARENT_METADATA_BYTES = 64_000
MAX_IDENTITY_METADATA_BYTES = 16_000
MAX_NUMSTAT_BYTES = 2_000_000
MAX_REWRITE_COMMITS = 10_000


def ensure_initial_subscriptions(
    state_path: str | Path,
    urls: list[str],
    run_started_at: datetime,
) -> tuple[dict[str, Any], dict[str, str]]:
    with exclusive_file_lock(state_path):
        state = load_state(state_path)
        new_urls: set[str] = set()
        changed = False
        for url in urls:
            if url not in state["repositories"]:
                state["repositories"][url] = {
                    "initial_since": (
                        run_started_at - timedelta(hours=INITIAL_BACKFILL_HOURS)
                    ).isoformat()
                }
                new_urls.add(url)
                changed = True
        if changed:
            write_json_atomic(state_path, state)
        errors: dict[str, str] = {}
        for url in urls:
            entry = state["repositories"][url]
            if entry.get("head") or entry.get("initial_head"):
                continue
            try:
                branch, head = detect_default_branch(url)
                if not head:
                    raise ValueError("remote default branch did not advertise a HEAD commit")
                entry.update(
                    {
                        "initial_branch": branch,
                        "initial_head": head,
                    }
                )
                if url not in new_urls:
                    entry["initial_full_scan"] = True
                write_json_atomic(state_path, state)
            except Exception as exc:
                errors[url] = str(exc)
        return state, errors


def detect_default_branch(url: str) -> tuple[str, str]:
    result = run_git(["ls-remote", "--symref", url, "HEAD"])
    head_sha = ""
    for line in result.stdout.splitlines():
        if line.startswith("ref: ") and line.endswith("\tHEAD"):
            ref = line[len("ref: ") : -len("\tHEAD")]
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                branch = ref[len(prefix) :]
                break
        fields = line.split("\t", 1)
        if len(fields) == 2 and fields[1] == "HEAD":
            head_sha = fields[0]
    else:
        heads = run_git(["ls-remote", "--heads", url]).stdout.splitlines()
        choices: list[tuple[str, str]] = []
        for line in heads:
            fields = line.split("\t", 1)
            if len(fields) != 2 or not fields[1].startswith("refs/heads/"):
                continue
            choices.append((fields[1][len("refs/heads/") :], fields[0]))
        if not choices:
            raise ValueError("remote has no branches and HEAD is not a branch symbolic ref")
        by_name = {branch: sha for branch, sha in choices}
        if OBJECT_ID_RE.fullmatch(head_sha):
            matching_heads = [choice for choice in choices if choice[1].lower() == head_sha.lower()]
            if len(matching_heads) == 1:
                return matching_heads[0]
        if "main" in by_name:
            return "main", by_name["main"]
        if "master" in by_name:
            return "master", by_name["master"]
        if len(choices) == 1:
            return choices[0]
        raise ValueError("cannot determine the remote default branch")

    if not head_sha:
        for line in result.stdout.splitlines():
            fields = line.split("\t", 1)
            if (
                len(fields) == 2
                and fields[1] == "HEAD"
                and OBJECT_ID_RE.fullmatch(fields[0])
            ):
                head_sha = fields[0]
                break
    return branch, head_sha


def ensure_cache(
    url: str,
    branch: str,
    cache_dir: Path,
    expected_head: str,
) -> tuple[Path, str]:
    repo_dir = cache_dir / cache_directory_name(url)
    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        # Keep every reachable commit for non-monotonic date traversal while
        # deferring tree and blob transfer until selected commits are inspected.
        run_git(
            [
                "clone",
                "--bare",
                "--no-tags",
                "--single-branch",
                f"--branch={branch}",
                "--filter=tree:0",
                url,
                str(repo_dir),
            ]
        )
        cloned_head = run_git(
            ["rev-parse", f"refs/heads/{branch}"],
            cwd=repo_dir,
        ).stdout.strip()
        run_git(
            ["update-ref", f"refs/remotes/origin/{branch}", cloned_head],
            cwd=repo_dir,
        )
    else:
        bare = run_git(["rev-parse", "--is-bare-repository"], cwd=repo_dir).stdout.strip()
        if bare != "true":
            raise ValueError(f"cache path is not a bare Git repository: {repo_dir}")
        run_git(["remote", "set-url", "origin", url], cwd=repo_dir)

    expected_format = object_format_for_oid(expected_head)
    actual_format = run_git(
        ["rev-parse", "--show-object-format"],
        cwd=repo_dir,
    ).stdout.strip()
    if actual_format != expected_format:
        raise ValueError(
            f"cache object format is {actual_format}, but remote uses {expected_format}: {repo_dir}"
        )
    if (
        run_git(["rev-parse", "--is-shallow-repository"], cwd=repo_dir).stdout.strip()
        != "false"
    ):
        raise ValueError(f"cache does not contain a complete commit graph: {repo_dir}")

    remote_ref = f"refs/remotes/origin/{branch}"
    refspec = f"+refs/heads/{branch}:{remote_ref}"
    # Never make this fetch shallow: --since-as-filter must be able to walk
    # through old-dated commits to find newer ancestors.
    run_git(
        ["fetch", "--no-tags", "--filter=tree:0", "origin", refspec],
        cwd=repo_dir,
    )
    current_head = run_git(["rev-parse", remote_ref], cwd=repo_dir).stdout.strip()
    return repo_dir, current_head


def object_format_for_oid(oid: str) -> str:
    if not OBJECT_ID_RE.fullmatch(oid):
        raise ValueError(f"remote advertised an invalid object id: {oid!r}")
    return "sha1" if len(oid) == 40 else "sha256"


def object_exists(repo_dir: Path, revision: str) -> bool:
    result = run_git(["cat-file", "-e", f"{revision}^{{commit}}"], cwd=repo_dir, check=False)
    return result.returncode == 0


def fetch_missing_commit(repo_dir: Path, revision: str) -> None:
    if not object_exists(repo_dir, revision):
        run_git(["fetch", "--no-tags", "origin", revision], cwd=repo_dir, check=False)


def is_ancestor(repo_dir: Path, old: str, new: str) -> bool:
    result = run_git(["merge-base", "--is-ancestor", old, new], cwd=repo_dir, check=False)
    return result.returncode == 0


def list_commit_shas(
    repo_dir: Path,
    current_head: str,
    previous_head: str | None,
    backfill_since: datetime | None,
) -> list[str]:
    if previous_head:
        output = run_git(
            ["rev-list", "--reverse", "--topo-order", current_head, "--not", previous_head],
            cwd=repo_dir,
        ).stdout
    else:
        if backfill_since is None:
            raise ValueError("first-run commit listing requires a backfill boundary")
        output = run_git(
            [
                "rev-list",
                "--reverse",
                "--topo-order",
                f"--since-as-filter={backfill_since.isoformat()}",
                current_head,
            ],
            cwd=repo_dir,
        ).stdout
    return [line.strip() for line in output.splitlines() if line.strip()]


def list_rewritten_commit_shas(
    repo_dir: Path,
    current_head: str,
    previous_head: str | None,
) -> list[str]:
    arguments = [
        "rev-list",
        "--reverse",
        "--topo-order",
        f"--max-count={MAX_REWRITE_COMMITS + 1}",
        current_head,
    ]
    if previous_head:
        arguments.extend(["--not", previous_head])
    output = run_git(arguments, cwd=repo_dir).stdout
    shas = [line.strip() for line in output.splitlines() if line.strip()]
    if len(shas) > MAX_REWRITE_COMMITS:
        raise RuntimeError(
            "rewritten history exceeds the safe full-scan limit of "
            f"{MAX_REWRITE_COMMITS} commits; cursor was not advanced"
        )
    return shas


def parse_trailers(repo_dir: Path, message: str) -> dict[str, list[str]]:
    output = run_git(["interpret-trailers", "--parse"], cwd=repo_dir, input_text=message).stdout
    trailers: dict[str, list[str]] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            trailers.setdefault(key, []).append(value)
    return trailers


def parse_numstat(raw: str) -> tuple[list[dict[str, Any]], int, int]:
    tokens = raw.split("\0")
    files: list[dict[str, Any]] = []
    additions_total = 0
    deletions_total = 0
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        if not record:
            continue
        fields = record.split("\t", 2)
        if len(fields) != 3:
            continue
        additions_raw, deletions_raw, path = fields
        if not path:
            if index + 1 >= len(tokens) or not tokens[index + 1]:
                break
            old_path = tokens[index]
            new_path = tokens[index + 1]
            index += 2
            path = f"{old_path} => {new_path}"
        additions = int(additions_raw) if additions_raw.isdigit() else None
        deletions = int(deletions_raw) if deletions_raw.isdigit() else None
        if additions is not None:
            additions_total += additions
        if deletions is not None:
            deletions_total += deletions
        files.append(
            {
                "path": path,
                "additions": additions,
                "deletions": deletions,
                "binary": additions is None or deletions is None,
            }
        )
    return files, additions_total, deletions_total


def commit_web_url(remote_url: str, sha: str) -> str | None:
    github_match = re.match(
        r"^(?:https?://github\.com/|ssh://git@github\.com/|git@github\.com:)([^/]+)/(.+?)(?:\.git)?$",
        remote_url.rstrip("/"),
    )
    if github_match:
        owner, repo = github_match.groups()
        if repo.endswith(".git"):
            repo = repo[:-4]
        return f"https://github.com/{owner}/{repo}/commit/{sha}"
    parsed = urlsplit(remote_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc == "git.kernel.org":
        return f"{remote_url.rstrip('/')}/commit/?id={sha}"
    return None


def read_commit(repo_dir: Path, remote_url: str, repo_id: str, sha: str) -> dict[str, Any]:
    core_metadata, parents_truncated = run_git_stdout_limited(
        [
            "show",
            "-s",
            "--format=%H%x00%aI%x00%cI%x00%P",
            sha,
        ],
        max_bytes=MAX_PARENT_METADATA_BYTES,
        cwd=repo_dir,
    )
    core_fields = core_metadata.rstrip("\n").split("\0", 3)
    if len(core_fields) != 4:
        raise ValueError(f"unexpected Git metadata format for commit {sha}")
    full_sha, author_date, committer_date, parents_raw = core_fields
    parents = [
        value
        for value in parents_raw.split()
        if OBJECT_ID_RE.fullmatch(value)
    ]

    identities, identities_truncated = run_git_stdout_limited(
        [
            "show",
            "-s",
            "--format=%an%x00%ae%x00%cn%x00%ce",
            sha,
        ],
        max_bytes=MAX_IDENTITY_METADATA_BYTES,
        cwd=repo_dir,
    )
    identity_fields = identities.rstrip("\n").split("\0", 3)
    if len(identity_fields) < 4:
        identity_fields.extend([""] * (4 - len(identity_fields)))
        identities_truncated = True
    author_name, author_email, committer_name, committer_email = identity_fields

    message, message_truncated = run_git_stdout_limited(
        ["show", "-s", "--format=%B", sha],
        max_bytes=MAX_COMMIT_MESSAGE_BYTES,
        cwd=repo_dir,
    )
    message = message.rstrip("\n")
    if message_truncated:
        message = message.rstrip() + "\n\n[commit message truncated]"
    combined_paths_args: list[str] | None = None
    if len(parents) > 1:
        numstat_args = [
            "show",
            "--format=",
            "--cc",
            "--numstat",
            "-z",
            "--find-renames",
            full_sha,
        ]
        combined_paths_args = [
            "diff-tree",
            "--cc",
            "--name-only",
            "-z",
            "-r",
            "--no-commit-id",
            full_sha,
        ]
        patch_args = [
            "show",
            "--format=",
            "--cc",
            "--no-ext-diff",
            "--no-color",
            "--find-renames",
            "--unified=3",
            full_sha,
        ]
        patch_kind = "combined"
    elif parents:
        numstat_args = ["diff", "--numstat", "-z", "--find-renames", parents[0], full_sha]
        patch_args = [
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--find-renames",
            "--unified=3",
            parents[0],
            full_sha,
        ]
        patch_kind = "first-parent"
    else:
        numstat_args = [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "-r",
            "--numstat",
            "-z",
            "--find-renames",
            full_sha,
        ]
        patch_args = [
            "show",
            "--format=",
            "--root",
            "--no-ext-diff",
            "--no-color",
            "--find-renames",
            "--unified=3",
            full_sha,
        ]
        patch_kind = "root"
    numstat, files_truncated = run_git_stdout_limited(
        numstat_args,
        max_bytes=MAX_NUMSTAT_BYTES,
        cwd=repo_dir,
    )
    if files_truncated and "\0" in numstat:
        numstat = numstat.rsplit("\0", 1)[0] + "\0"
    elif files_truncated:
        numstat = ""
    files, additions, deletions = parse_numstat(numstat)
    if combined_paths_args is not None:
        paths_output, paths_truncated = run_git_stdout_limited(
            combined_paths_args,
            max_bytes=MAX_NUMSTAT_BYTES,
            cwd=repo_dir,
        )
        if paths_truncated and "\0" in paths_output:
            paths_output = paths_output.rsplit("\0", 1)[0] + "\0"
        elif paths_truncated:
            paths_output = ""
        combined_paths = list(dict.fromkeys(path for path in paths_output.split("\0") if path))
        combined_path_set = set(combined_paths)
        files = [
            item
            for item in files
            if item["path"] in combined_path_set
            or any(item["path"].endswith(f" => {path}") for path in combined_path_set)
        ]
        represented_paths = {
            path
            for path in combined_paths
            if any(
                item["path"] == path or item["path"].endswith(f" => {path}")
                for item in files
            )
        }
        files.extend(
            {
                "path": path,
                "additions": None,
                "deletions": None,
                "binary": True,
            }
            for path in combined_paths
            if path not in represented_paths
        )
        additions = sum(item["additions"] or 0 for item in files)
        deletions = sum(item["deletions"] or 0 for item in files)
        files_truncated = files_truncated or paths_truncated
    patch, patch_truncated = run_git_stdout_limited(
        patch_args,
        max_bytes=MAX_PATCH_BYTES,
        cwd=repo_dir,
    )
    if patch_truncated:
        patch = patch.rstrip() + "\n\n[patch truncated]"
    subject = message.splitlines()[0].strip() if message.splitlines() else "Untitled commit"
    return {
        "id": f"{repo_id}:{full_sha}",
        "sha": full_sha,
        "short_sha": full_sha[:12],
        "subject": subject,
        "message": message,
        "message_truncated": message_truncated,
        "identities_truncated": identities_truncated,
        "parents_truncated": parents_truncated,
        "author": {"name": author_name, "email": author_email, "date": author_date},
        "committer": {"name": committer_name, "email": committer_email, "date": committer_date},
        "parents": parents,
        "is_merge": len(parents) > 1,
        "trailers": parse_trailers(repo_dir, message),
        "files": files,
        "files_truncated": files_truncated,
        "stats": {
            "files_changed": len(files),
            "additions": additions,
            "deletions": deletions,
        },
        "patch": patch,
        "patch_truncated": patch_truncated,
        "patch_kind": patch_kind,
        "merge_context_only": len(parents) > 1 and not patch.strip(),
        "url": commit_web_url(remote_url, full_sha),
    }


def coverage_from_state(
    entry: dict[str, Any] | None,
    run_started_at: datetime,
) -> dict[str, Any]:
    if entry and entry.get("head"):
        return {
            "mode": "incremental",
            "from_head": entry["head"],
        }
    if entry and entry.get("initial_full_scan"):
        return {"mode": "initial_full_history"}
    if entry and entry.get("initial_since"):
        since = datetime.fromisoformat(entry["initial_since"])
    else:
        since = run_started_at - timedelta(hours=INITIAL_BACKFILL_HOURS)
    return {
        "mode": "initial_since",
        "since": since.isoformat(),
    }


def fetch_repository(
    url: str,
    state: dict[str, Any],
    cache_dir: Path,
    run_started_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    if run_started_at is None:
        run_started_at = utc_now()
    repo_id = repository_id(url)
    name = repository_name(url)
    previous_entry = state["repositories"].get(url)
    previous_head = previous_entry.get("head") if previous_entry else None
    initial_head = previous_entry.get("initial_head") if previous_entry else None
    if previous_head:
        backfill_since = None
    elif previous_entry and previous_entry.get("initial_since"):
        backfill_since = datetime.fromisoformat(previous_entry["initial_since"])
    else:
        backfill_since = run_started_at - timedelta(hours=INITIAL_BACKFILL_HOURS)
    branch, advertised_head = detect_default_branch(url)
    repo_dir, current_head = ensure_cache(url, branch, cache_dir, advertised_head)

    comparison_head = previous_head or initial_head
    comparison_head_available = True
    if comparison_head:
        fetch_missing_commit(repo_dir, comparison_head)
        comparison_head_available = object_exists(repo_dir, comparison_head)
    if initial_head and not comparison_head_available:
        raise RuntimeError(
            "first-subscription baseline is no longer available; cursor was not advanced"
        )
    if previous_head and not comparison_head_available:
        raise RuntimeError(
            "previous cursor is no longer available; cursor was not advanced"
        )
    force_push = bool(
        comparison_head
        and not is_ancestor(repo_dir, comparison_head, current_head)
    )
    if initial_head:
        if previous_entry.get("initial_full_scan"):
            initial_shas = list_rewritten_commit_shas(repo_dir, initial_head, None)
        else:
            initial_shas = list_commit_shas(repo_dir, initial_head, None, backfill_since)
        if current_head == initial_head:
            newly_reachable_shas: list[str] = []
        elif force_push:
            newly_reachable_shas = list_rewritten_commit_shas(
                repo_dir,
                current_head,
                initial_head,
            )
        else:
            newly_reachable_shas = list_commit_shas(
                repo_dir,
                current_head,
                initial_head,
                None,
            )
        shas = list(dict.fromkeys([*initial_shas, *newly_reachable_shas]))
    elif force_push:
        shas = list_rewritten_commit_shas(repo_dir, current_head, previous_head)
    else:
        shas = list_commit_shas(repo_dir, current_head, previous_head, backfill_since)
    commits = [read_commit(repo_dir, url, repo_id, sha) for sha in shas]
    coverage = coverage_from_state(previous_entry, run_started_at)
    coverage["to_head"] = current_head
    result = {
        "id": repo_id,
        "name": name,
        "url": url,
        "branch": branch,
        "previous_head": previous_head,
        "initial_head": initial_head,
        "current_head": current_head,
        "first_run": previous_head is None,
        "coverage": coverage,
        "branch_changed": bool(
            comparison_head
            and (previous_entry.get("branch") or previous_entry.get("initial_branch")) != branch
        ),
        "force_push": force_push,
        "status": "success",
        "error": None,
        "commits": commits,
    }
    return result, {"branch": branch, "head": current_head}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch newly reachable commits from configured Git repositories.")
    parser.add_argument("--config", required=True, help="JSON array of Git remote URLs")
    parser.add_argument("--state", required=True, help="Persistent state.json path")
    parser.add_argument("--cache-dir", required=True, help="Directory for bare Git caches")
    parser.add_argument("--out", required=True, help="Output raw_commits.json path")
    parser.add_argument("--base-state-out", required=True, help="State snapshot used for compare-and-swap")
    parser.add_argument("--next-state-out", required=True, help="Pending state output path")
    parser.add_argument("--meta-out", required=True, help="Run metadata output path")
    args = parser.parse_args()

    recover_finalization(args.state)
    urls = load_config(args.config)
    run_started_at = utc_now()
    state, initialization_errors = ensure_initial_subscriptions(
        args.state,
        urls,
        run_started_at,
    )
    write_json(args.base_state_out, state)
    next_state: dict[str, Any] = {"repositories": {}}
    repositories: list[dict[str, Any]] = []
    warnings: list[str] = []
    fetch_truncations: list[dict[str, Any]] = []
    cache_dir = Path(args.cache_dir)

    for url in urls:
        try:
            if url in initialization_errors:
                raise RuntimeError(initialization_errors[url])
            repository, next_entry = fetch_repository(
                url,
                state,
                cache_dir,
                run_started_at,
            )
            repositories.append(repository)
            next_state["repositories"][url] = next_entry
            if repository["force_push"]:
                warnings.append(f"{repository['name']}: default branch history was rewritten")
            if repository["branch_changed"]:
                warnings.append(
                    f"{repository['name']}: default branch changed to {repository['branch']}"
                )
            truncated_count = sum(commit.get("patch_truncated", False) for commit in repository["commits"])
            if truncated_count:
                warnings.append(
                    f"{repository['name']}: {truncated_count} commit patch(es) were truncated"
                )
            for commit in repository["commits"]:
                truncated_fields = {
                    "message": bool(commit.get("message_truncated")),
                    "identities": bool(commit.get("identities_truncated")),
                    "parents": bool(commit.get("parents_truncated")),
                    "files": bool(commit.get("files_truncated")),
                    "patch": bool(commit.get("patch_truncated")),
                }
                if any(truncated_fields.values()):
                    fetch_truncations.append(
                        {
                            "repository_id": repository["id"],
                            "commit_id": commit["id"],
                            **truncated_fields,
                        }
                    )
            message_truncated_count = sum(
                commit.get("message_truncated", False) for commit in repository["commits"]
            )
            if message_truncated_count:
                warnings.append(
                    f"{repository['name']}: {message_truncated_count} commit message(s) were truncated"
                )
            metadata_truncated_count = sum(
                bool(commit.get("identities_truncated") or commit.get("parents_truncated"))
                for commit in repository["commits"]
            )
            if metadata_truncated_count:
                warnings.append(
                    f"{repository['name']}: {metadata_truncated_count} commit metadata record(s) were truncated"
                )
            files_truncated_count = sum(
                commit.get("files_truncated", False) for commit in repository["commits"]
            )
            if files_truncated_count:
                warnings.append(
                    f"{repository['name']}: {files_truncated_count} commit file list(s) were truncated"
                )
        except Exception as exc:
            state_entry = state["repositories"].get(url)
            if url in state["repositories"]:
                next_state["repositories"][url] = state_entry
            repositories.append(
                {
                    "id": repository_id(url),
                    "name": repository_name(url),
                    "url": url,
                    "branch": None,
                    "previous_head": (state_entry or {}).get("head"),
                    "initial_head": (state_entry or {}).get("initial_head"),
                    "current_head": None,
                    "first_run": not bool((state_entry or {}).get("head")),
                    "coverage": coverage_from_state(state_entry, run_started_at),
                    "branch_changed": False,
                    "force_push": False,
                    "status": "failed",
                    "error": str(exc),
                    "commits": [],
                }
            )
            warnings.append(f"{repository_name(url)}: {exc}")

    payload = {
        "generated_at": run_started_at.isoformat(),
        "repositories": repositories,
    }
    write_json(args.out, payload)
    write_json(args.next_state_out, next_state)

    commit_count = sum(len(repo["commits"]) for repo in repositories)
    meta = {
        "generated_at": payload["generated_at"],
        "repository_count": len(repositories),
        "successful_repositories": sum(repo["status"] == "success" for repo in repositories),
        "failed_repositories": sum(repo["status"] == "failed" for repo in repositories),
        "commit_count": commit_count,
        "warnings": warnings,
        "fetch_truncations": fetch_truncations,
    }
    write_json(args.meta_out, meta)
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
