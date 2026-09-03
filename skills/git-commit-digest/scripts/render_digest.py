#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from _common import load_json


def safe_text(value: Any) -> str:
    normalized = " ".join(str(value or "").split())
    escaped = html.escape(normalized, quote=False)
    return re.sub(r"([\\`*_[\]|])", r"\\\1", escaped)


def safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value.replace(" ", "%20").replace(")", "%29")


def status_label(repository: dict[str, Any]) -> str:
    if repository.get("status") != "success":
        return "失败"
    if not repository.get("commits"):
        return "无变化"
    return "成功"


def repository_label(repository: dict[str, Any]) -> str:
    return safe_text(
        repository.get("project_name") or repository.get("name") or "repository"
    )


def coverage_boundary(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("initial_since coverage requires a since timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("initial_since coverage has an invalid since timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("initial_since coverage requires a timezone-aware since timestamp")
    return parsed.isoformat(timespec="minutes")


def repository_range(repository: dict[str, Any], include_name: bool = False) -> str:
    coverage = repository.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("every successful repository requires coverage metadata")
    mode = coverage.get("mode")
    if mode == "incremental":
        label = "上次成功状态"
    elif mode == "initial_since":
        label = f"自 {coverage_boundary(coverage.get('since'))}"
    elif mode == "initial_full_history":
        label = "完整历史"
    else:
        raise ValueError(f"unsupported repository coverage mode: {mode!r}")
    if include_name:
        return f"{repository_label(repository)}：{label}"
    return label


def range_label(repositories: list[dict[str, Any]]) -> str:
    successful = [repo for repo in repositories if repo.get("status") == "success"]
    if not successful:
        if repositories and all(repo.get("first_run") for repo in repositories):
            return "首次运行（尚未建立成功状态）"
        return "各仓库上次成功状态 → 本次运行（本次未抓取成功）"
    ranges = [repository_range(repository) for repository in successful]
    if len(set(ranges)) == 1:
        only = ranges[0]
        if only == "上次成功状态":
            return "上次成功运行 → 本次运行"
        if only == "完整历史":
            return "首次订阅完整历史 → 本次运行"
        return f"首次订阅{only} → 本次运行"
    details = "；".join(
        repository_range(repository, include_name=True) for repository in successful
    )
    return f"{details} → 本次运行"


def render(raw: dict[str, Any], digest: dict[str, Any], date: str | None = None) -> str:
    repositories = raw.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("raw commits must contain a repositories array")
    digest_repositories = {
        item["id"]: item for item in digest.get("repositories", []) if isinstance(item, dict) and item.get("id")
    }
    generated_raw = raw.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(generated_raw).replace("Z", "+00:00")).astimezone()
    except ValueError:
        generated = datetime.now().astimezone()
    report_date = date or generated.strftime("%Y-%m-%d")
    lines = [
        f"# Git Commit Digest · {report_date}",
        "",
        f"生成时间：{generated.strftime('%Y-%m-%d %H:%M')}",
        f"范围：{range_label(repositories)}",
        "",
        "| 项目 | 分支 | 新增 Commit | 变更主题 | 状态 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for repository in repositories:
        grouped = digest_repositories.get(repository.get("id"), {})
        group_count = len(grouped.get("groups", [])) if isinstance(grouped, dict) else 0
        lines.append(
            "| {name} | {branch} | {commits} | {groups} | {status} |".format(
                name=repository_label(repository),
                branch=safe_text(repository.get("branch") or "—"),
                commits=len(repository.get("commits", [])),
                groups=group_count,
                status=status_label(repository),
            )
        )

    lines.extend(["", "## 今日概览", ""])
    overview = digest.get("overview")
    if isinstance(overview, list) and overview:
        lines.extend(f"- {safe_text(item)}" for item in overview)
    else:
        lines.append("- 订阅仓库没有新增 Commit。")

    for repository in repositories:
        commits = repository.get("commits", [])
        repo_digest = digest_repositories.get(repository.get("id"))
        if repository.get("status") != "success" or not commits or not repo_digest:
            continue
        commit_by_id = {commit["id"]: commit for commit in commits}
        groups = repo_digest["groups"]
        lines.extend(
            [
                "",
                f"## {repository_label(repository)}",
                "",
                f"新增 {len(commits)} 个 Commit，归纳为 {len(groups)} 个变更主题。{safe_text(repo_digest['overview'])}",
            ]
        )
        for group in groups:
            lines.extend(
                [
                    "",
                    f"### {safe_text(group['title'])}",
                    "",
                    "**目的**",
                    "",
                    safe_text(group["purpose"]),
                    "",
                    "**修改内容**",
                    "",
                ]
            )
            lines.extend(f"- {safe_text(change)}" for change in group["changes"])
            lines.extend(["", "**影响**", "", safe_text(group["impact"]), "", "**相关 Commit**", ""])
            for commit_id in group["commit_ids"]:
                commit = commit_by_id[commit_id]
                short_sha = safe_text(commit.get("short_sha") or str(commit.get("sha", ""))[:12])
                subject = safe_text(commit.get("subject"))
                url = safe_url(commit.get("url"))
                if url:
                    lines.append(f"- [`{short_sha}`]({url}) {subject}")
                else:
                    lines.append(f"- `{short_sha}` {subject}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the validated Chinese Git commit digest.")
    parser.add_argument("--commits", required=True, help="analyzed_commits.json path")
    parser.add_argument("--digest", required=True, help="validated_digest.json path")
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", help="Optional YYYY-MM-DD report label")
    args = parser.parse_args()

    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        raise ValueError("--date must use YYYY-MM-DD")
    rendered = render(load_json(args.commits), load_json(args.digest), args.date)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(str(target))


if __name__ == "__main__":
    main()
