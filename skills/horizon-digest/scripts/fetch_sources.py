#!/usr/bin/env python3
import argparse
import calendar
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from _common import count_by_source, load_config, make_item, strip_html, utc_now, write_json


USER_AGENT = "horizon-digest/0.1 (+local agent workflow)"


def request(url: str, *, headers: dict[str, str] | None = None, timeout: int = 25) -> bytes:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    return json.loads(request(url, headers=headers).decode("utf-8"))


def get_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    return request(url, headers=headers).decode("utf-8", errors="replace")


def parse_http_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def stable_id(*parts: str) -> str:
    raw = ":".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def tag_name(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def first_text(node: ET.Element, names: tuple[str, ...]) -> str:
    wanted = {n.lower() for n in names}
    for child in list(node):
        if tag_name(child) in wanted and child.text:
            return child.text.strip()
    return ""


def first_link(node: ET.Element) -> str:
    for child in list(node):
        if tag_name(child) == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
            if child.text:
                return child.text.strip()
    return ""


def parse_rss_date(node: ET.Element) -> datetime | None:
    for field in ("published", "updated", "pubdate", "created", "date"):
        text = first_text(node, (field,))
        if text:
            parsed = parse_http_date(text)
            if parsed:
                return parsed
            try:
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                pass
    return None


def fetch_rss(config: dict[str, Any], since: datetime, warnings: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source in config.get("sources", {}).get("rss", []) or []:
        if not source.get("enabled", True):
            continue
        name = source.get("name") or "RSS"
        url = source.get("url")
        if not url:
            continue
        try:
            root = ET.fromstring(get_text(url))
        except Exception as exc:
            warnings.append(f"rss:{name}: {exc}")
            continue

        entries = root.findall(".//{*}entry") or root.findall(".//item")
        for entry in entries:
            published = parse_rss_date(entry)
            if published and published < since:
                continue
            title = first_text(entry, ("title",)) or "Untitled"
            link = first_link(entry) or first_text(entry, ("link",)) or url
            entry_id = first_text(entry, ("id", "guid")) or link
            content = (
                first_text(entry, ("summary", "description", "content", "encoded"))
                or ""
            )
            author = first_text(entry, ("author", "creator")) or name
            if not published:
                published = utc_now()
            items.append(
                make_item(
                    item_id=f"rss:{stable_id(str(url), str(entry_id))}",
                    source_type="rss",
                    title=strip_html(title),
                    url=link,
                    content=strip_html(content),
                    author=strip_html(author),
                    published_at=published,
                    metadata={
                        "feed_name": name,
                        "category": source.get("category"),
                    },
                )
            )
    return items


def fetch_hackernews(config: dict[str, Any], since: datetime, warnings: list[str]) -> list[dict[str, Any]]:
    hn = config.get("sources", {}).get("hackernews", {}) or {}
    if not hn.get("enabled", False):
        return []
    base = "https://hacker-news.firebaseio.com/v0"
    try:
        story_ids = get_json(f"{base}/topstories.json")[: int(hn.get("fetch_top_stories", 30))]
    except Exception as exc:
        warnings.append(f"hackernews: {exc}")
        return []

    items: list[dict[str, Any]] = []
    min_score = int(hn.get("min_score", 0))
    comment_limit = int(hn.get("top_comments", 5))
    for sid in story_ids:
        try:
            story = get_json(f"{base}/item/{sid}.json")
        except Exception:
            continue
        if not isinstance(story, dict) or story.get("score", 0) < min_score:
            continue
        published = datetime.fromtimestamp(int(story.get("time", 0)), tz=timezone.utc)
        if published < since:
            continue
        comments: list[str] = []
        for cid in (story.get("kids") or [])[:comment_limit]:
            try:
                comment = get_json(f"{base}/item/{cid}.json")
            except Exception:
                continue
            if isinstance(comment, dict) and comment.get("text") and not comment.get("deleted"):
                comments.append(f"[{comment.get('by', 'anon')}]: {strip_html(comment.get('text'))[:500]}")
        parts = []
        if story.get("text"):
            parts.append(strip_html(story.get("text")))
        if comments:
            parts.append("--- Top Comments ---\n" + "\n".join(comments))
        discussion_url = f"https://news.ycombinator.com/item?id={sid}"
        items.append(
            make_item(
                item_id=f"hackernews:story:{sid}",
                source_type="hackernews",
                title=story.get("title") or "Untitled",
                url=story.get("url") or discussion_url,
                content="\n\n".join(parts),
                author=story.get("by"),
                published_at=published,
                metadata={
                    "score": story.get("score", 0),
                    "descendants": story.get("descendants", 0),
                    "discussion_url": discussion_url,
                    "comment_count": len(comments),
                },
            )
        )
    return items


def github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_github(config: dict[str, Any], since: datetime, warnings: list[str]) -> list[dict[str, Any]]:
    sources = config.get("sources", {}).get("github", []) or []
    items: list[dict[str, Any]] = []
    for source in sources:
        if not source.get("enabled", True):
            continue
        kind = source.get("type")
        try:
            if kind == "user_events" and source.get("username"):
                items.extend(fetch_github_user_events(source["username"], since))
            elif kind == "repo_releases" and source.get("owner") and source.get("repo"):
                items.extend(fetch_github_releases(source["owner"], source["repo"], since))
        except Exception as exc:
            warnings.append(f"github:{kind}: {exc}")
    return items


def fetch_github_user_events(username: str, since: datetime) -> list[dict[str, Any]]:
    url = f"https://api.github.com/users/{urllib.parse.quote(username)}/events/public"
    events = get_json(url, headers=github_headers())
    items: list[dict[str, Any]] = []
    for event in events:
        created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
        if created < since:
            continue
        event_type = event.get("type")
        if event_type not in {"PushEvent", "CreateEvent", "ReleaseEvent", "PublicEvent", "WatchEvent"}:
            continue
        repo = event.get("repo", {}).get("name", "")
        repo_url = f"https://github.com/{repo}" if repo else f"https://github.com/{username}"
        payload = event.get("payload", {})
        if event_type == "PushEvent":
            commits = payload.get("commits", [])
            title = f"{username} pushed {len(commits)} commit(s) to {repo}"
            content = "\n".join(c.get("message", "") for c in commits[:3])
        elif event_type == "CreateEvent":
            ref_type = payload.get("ref_type", "repository")
            title = f"{username} created {ref_type} in {repo}"
            content = payload.get("description", "")
        elif event_type == "ReleaseEvent":
            release = payload.get("release", {})
            title = f"{username} released {release.get('tag_name', '')} in {repo}"
            content = release.get("body", "")
            repo_url = release.get("html_url") or repo_url
        elif event_type == "PublicEvent":
            title = f"{username} made {repo} public"
            content = ""
        else:
            title = f"{username} starred {repo}"
            content = ""
        items.append(
            make_item(
                item_id=f"github:event:{event.get('id')}",
                source_type="github",
                title=title,
                url=repo_url,
                content=content or "",
                author=username,
                published_at=created,
                metadata={"event_type": event_type, "repo": repo},
            )
        )
    return items


def fetch_github_releases(owner: str, repo: str, since: datetime) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/releases"
    releases = get_json(url, headers=github_headers())
    items: list[dict[str, Any]] = []
    for release in releases:
        published_raw = release.get("published_at")
        if not published_raw:
            continue
        published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        if published < since:
            continue
        author = (release.get("author") or {}).get("login")
        items.append(
            make_item(
                item_id=f"github:release:{release.get('id')}",
                source_type="github",
                title=f"{owner}/{repo} released {release.get('tag_name')}",
                url=release.get("html_url") or f"https://github.com/{owner}/{repo}/releases",
                content=release.get("body") or "",
                author=author,
                published_at=published,
                metadata={
                    "repo": f"{owner}/{repo}",
                    "tag": release.get("tag_name"),
                    "prerelease": release.get("prerelease", False),
                },
            )
        )
    return items


def fetch_reddit(config: dict[str, Any], since: datetime, warnings: list[str]) -> list[dict[str, Any]]:
    reddit = config.get("sources", {}).get("reddit", {}) or {}
    if not reddit.get("enabled", False):
        return []
    items: list[dict[str, Any]] = []
    for sub in reddit.get("subreddits", []) or []:
        if not sub.get("enabled", True):
            continue
        name = sub.get("subreddit")
        if not name:
            continue
        sort = sub.get("sort", "hot")
        limit = int(sub.get("fetch_limit", 25))
        min_score = int(sub.get("min_score", 0))
        t = sub.get("time_filter", "day")
        url = f"https://www.reddit.com/r/{urllib.parse.quote(name)}/{sort}.json?limit={limit}&t={urllib.parse.quote(t)}&raw_json=1"
        try:
            payload = get_json(url, headers={"Accept": "application/json"})
        except Exception as exc:
            warnings.append(f"reddit:r/{name}: {exc}")
            continue
        for child in payload.get("data", {}).get("children", []):
            try:
                data = child.get("data", {}) or {}
                post_id = str(data.get("id") or "")
                score = int(data.get("score") or 0)
                if score < min_score:
                    continue
                published = datetime.fromtimestamp(float(data.get("created_utc") or 0), tz=timezone.utc)
                if published < since:
                    continue
                permalink = "https://www.reddit.com" + str(data.get("permalink") or "")
                content_parts = []
                if data.get("selftext"):
                    content_parts.append(strip_html(data.get("selftext")))
                comments = fetch_reddit_comments(name, post_id, int(reddit.get("fetch_comments") or 0))
                if comments:
                    content_parts.append("--- Top Comments ---\n" + "\n".join(comments))
                items.append(
                    make_item(
                        item_id=f"reddit:post:{post_id}",
                        source_type="reddit",
                        title=data.get("title") or "Untitled",
                        url=data.get("url") or permalink,
                        content="\n\n".join(content_parts),
                        author=data.get("author"),
                        published_at=published,
                        metadata={
                            "subreddit": name,
                            "score": score,
                            "num_comments": data.get("num_comments", 0),
                            "upvote_ratio": data.get("upvote_ratio"),
                            "discussion_url": permalink,
                            "comment_count": len(comments),
                        },
                    )
                )
            except Exception as exc:
                post_id = ""
                if isinstance(child, dict):
                    post_id = str((child.get("data") or {}).get("id") or "")
                suffix = f" {post_id}" if post_id else ""
                warnings.append(f"reddit:r/{name}: skipped malformed item{suffix}: {exc}")
    return items


def fetch_reddit_comments(subreddit: str, post_id: str | None, limit: int) -> list[str]:
    if not post_id or limit <= 0:
        return []
    url = f"https://www.reddit.com/r/{urllib.parse.quote(subreddit)}/comments/{urllib.parse.quote(post_id)}.json?limit={limit}&sort=top&raw_json=1"
    try:
        payload = get_json(url, headers={"Accept": "application/json"})
    except Exception:
        return []
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    out: list[str] = []
    for child in payload[1].get("data", {}).get("children", [])[:limit]:
        data = child.get("data", {})
        body = strip_html(data.get("body"))
        if body:
            out.append(f"[{data.get('author', 'anon')} ({data.get('score', 0)} pts)]: {body[:500]}")
    return out


def fetch_ossinsight(config: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    cfg = config.get("sources", {}).get("ossinsight", {}) or {}
    if not cfg.get("enabled", False):
        return []
    period = cfg.get("period", "past_24_hours")
    languages = cfg.get("languages", ["All"])
    keywords = [str(x).lower() for x in cfg.get("keywords", []) if x]
    min_stars = int(cfg.get("min_stars", 0))
    max_items = int(cfg.get("max_items", 30))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for language in languages:
        qs = urllib.parse.urlencode({"period": period, "language": language})
        url = f"https://api.ossinsight.io/v1/trends/repos?{qs}"
        try:
            payload = get_json(url, headers={"Accept": "application/json"})
        except Exception as exc:
            warnings.append(f"ossinsight:{language}: {exc}")
            continue
        rows = ((payload.get("data") or {}).get("rows") or [])
        for row in rows:
            repo_name = row.get("repo_name")
            repo_id = row.get("repo_id")
            if not repo_name or not repo_id:
                continue
            stars = int(row.get("stars") or 0)
            if stars < min_stars:
                continue
            haystack = " ".join(
                str(row.get(k) or "").lower()
                for k in ("repo_name", "description", "collection_names")
            )
            if keywords and not any(k in haystack for k in keywords):
                continue
            item_id = f"ossinsight:trending:{repo_id}"
            if item_id in seen:
                continue
            seen.add(item_id)
            desc = row.get("description") or ""
            primary_language = row.get("primary_language") or language
            content = "\n".join(
                [
                    f"Trending GitHub repo: {repo_name}",
                    f"Stars gained ({period}): {stars}",
                    f"Forks gained: {row.get('forks', 0)}",
                    f"Pushes: {row.get('pushes', 0)}",
                    f"Pull requests: {row.get('pull_requests', 0)}",
                    f"Language: {primary_language}",
                    "",
                    desc,
                ]
            ).strip()
            items.append(
                make_item(
                    item_id=item_id,
                    source_type="ossinsight",
                    title=f"{repo_name} (+{stars} stars {period})",
                    url=f"https://github.com/{repo_name}",
                    content=content,
                    author=repo_name.split("/")[0] if "/" in repo_name else None,
                    published_at=utc_now(),
                    metadata={
                        "repo": repo_name,
                        "stars_gained": stars,
                        "forks_gained": int(row.get("forks") or 0),
                        "pushes": int(row.get("pushes") or 0),
                        "pull_requests": int(row.get("pull_requests") or 0),
                        "primary_language": primary_language,
                        "period": period,
                        "collection_names": row.get("collection_names"),
                        "description": desc,
                    },
                )
            )
    items.sort(key=lambda x: x.get("metadata", {}).get("stars_gained", 0), reverse=True)
    return items[:max_items]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch configured sources into normalized JSON items.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--meta-out")
    parser.add_argument("--hours", type=int)
    args = parser.parse_args()

    config = load_config(args.config)
    hours = args.hours or int(config.get("filtering", {}).get("time_window_hours", 24))
    since = utc_now() - timedelta(hours=hours)
    warnings: list[str] = []

    items: list[dict[str, Any]] = []
    for source_name, fn in (
        ("rss", fetch_rss),
        ("hackernews", fetch_hackernews),
        ("github", fetch_github),
        ("reddit", fetch_reddit),
    ):
        try:
            items.extend(fn(config, since, warnings))
        except Exception as exc:
            warnings.append(f"{source_name}: {exc}")
    try:
        items.extend(fetch_ossinsight(config, warnings))
    except Exception as exc:
        warnings.append(f"ossinsight: {exc}")
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    write_json(args.out, items)
    meta = {
        "generated_at": utc_now().isoformat(),
        "since": since.isoformat(),
        "hours": hours,
        "raw_count": len(items),
        "source_counts": count_by_source(items),
        "warnings": warnings,
    }
    if args.meta_out:
        write_json(args.meta_out, meta)
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
