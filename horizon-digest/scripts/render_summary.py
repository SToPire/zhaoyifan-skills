#!/usr/bin/env python3
import argparse
import html
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from _common import load_config, load_items, load_json


CJK = r"[\u4e00-\u9fff\u3400-\u4dbf]"
ASCII = r"[A-Za-z0-9]"


LABELS = {
    "en": {
        "header": "Horizon Daily",
        "selected_items": "From {total} items, {selected} important content pieces were selected.",
        "source": "Source",
        "background": "Background",
        "discussion": "Discussion",
        "references": "References",
        "tags": "Tags",
        "empty": "No significant developments met the selected threshold.",
    },
    "zh": {
        "header": "Horizon 每日速递",
        "selected_items": "从 {total} 条内容中筛选出 {selected} 条重要资讯。",
        "source": "来源",
        "background": "背景",
        "discussion": "社区讨论",
        "references": "参考链接",
        "tags": "标签",
        "empty": "今日暂无达到阈值的重要动态。",
    },
}


def pangu(text: str) -> str:
    text = re.sub(rf"({CJK})({ASCII})", r"\1 \2", text)
    text = re.sub(rf"({ASCII})({CJK})", r"\1 \2", text)
    return text


def safe_url(value: Any) -> str:
    url = str(value or "").strip().replace("\r", "").replace("\n", "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return url.replace("<", "%3C").replace(">", "%3E")


def markdown_link(label: str, url: Any) -> str:
    cleaned = safe_url(url)
    if not cleaned:
        return label
    return f"[{label}](<{cleaned}>)"


def source_line(item: dict[str, Any], language: str, labels: dict[str, str]) -> str:
    meta = item.get("metadata") or {}
    parts = [str(item.get("source_type") or "source")]
    if meta.get("subreddit"):
        parts.append(f"r/{meta['subreddit']}")
    elif meta.get("feed_name"):
        parts.append(str(meta["feed_name"]))
    elif meta.get("repo"):
        parts.append(str(meta["repo"]))
    elif item.get("author"):
        parts.append(str(item["author"]))
    published = str(item.get("published_at") or "")
    if published:
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(timezone.utc)
            if language == "zh":
                parts.append(f"{dt.month}月{dt.day}日 {dt:%H:%M}")
            else:
                parts.append(f"{dt:%b} {dt.day}, {dt:%H:%M}")
        except Exception:
            pass
    line = " · ".join(parts)
    discussion_url = meta.get("discussion_url")
    if discussion_url and str(discussion_url) != str(item.get("url")):
        link = markdown_link(labels["discussion"], discussion_url)
        if link != labels["discussion"]:
            line += f" · {link}"
    return line


def item_title(item: dict[str, Any], language: str) -> str:
    meta = item.get("metadata") or {}
    title = str(meta.get(f"title_{language}") or item.get("title") or "Untitled")
    title = title.replace("[", "(").replace("]", ")")
    return pangu(title) if language == "zh" else title


def format_item(item: dict[str, Any], index: int, language: str, labels: dict[str, str]) -> str:
    meta = item.get("metadata") or {}
    title = item_title(item, language)
    url = str(item.get("url") or "")
    score = item.get("ai_score")
    score_text = "?" if score is None else f"{float(score):g}"
    summary = str(
        meta.get(f"detailed_summary_{language}")
        or meta.get("detailed_summary")
        or item.get("ai_summary")
        or ""
    )
    background = str(meta.get(f"background_{language}") or meta.get("background") or "")
    discussion = str(
        meta.get(f"community_discussion_{language}")
        or meta.get("community_discussion")
        or ""
    )
    if language == "zh":
        summary = pangu(summary)
        background = pangu(background)
        discussion = pangu(discussion)

    lines = [
        f"## {markdown_link(title, url)} ⭐ {score_text}/10",
        "",
        summary,
        "",
        source_line(item, language, labels),
    ]
    if background:
        lines.extend(["", f"**{labels['background']}**: {background}"])
    sources = meta.get("sources") or []
    if sources:
        ref_lines = []
        for source in sources:
            ref_url = source.get("url")
            ref_title = source.get("title") or ref_url
            cleaned_url = safe_url(ref_url)
            if cleaned_url:
                ref_lines.append(
                    f'<li><a href="{html.escape(cleaned_url, quote=True)}">{html.escape(str(ref_title))}</a></li>'
                )
        if ref_lines:
            lines.extend(
                [
                    "",
                    f'<details><summary>{labels["references"]}</summary>',
                    "<ul>",
                    *ref_lines,
                    "</ul>",
                    "</details>",
                ]
            )
    if discussion:
        lines.extend(["", f"**{labels['discussion']}**: {discussion}"])
    tags = item.get("ai_tags") or []
    if tags:
        tag_text = ", ".join(f"`#{str(tag).lstrip('#')}`" for tag in tags)
        lines.extend(["", f"**{labels['tags']}**: {tag_text}"])
    lines.extend(["", "---", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Markdown digest from enriched items.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--items", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--meta")
    parser.add_argument("--language", default=None)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    language = args.language or (config.get("languages") or ["zh"])[0]
    labels = LABELS.get(language, LABELS["en"])
    items = load_items(args.items)
    meta = load_json(args.meta) if args.meta else {}
    total = int(meta.get("raw_count") or meta.get("total_fetched") or len(items))
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    header = (
        f"# {labels['header']} - {date}\n\n"
        f"> {labels['selected_items'].format(total=total, selected=len(items))}\n\n"
        "---\n\n"
    )
    if not items:
        body = labels["empty"] + "\n"
    else:
        toc = []
        for i, item in enumerate(items, start=1):
            title = item_title(item, language)
            score = item.get("ai_score")
            score_text = "?" if score is None else f"{float(score):g}"
            toc.append(f"{i}. {title} ⭐ {score_text}/10")
        body = "\n".join(toc) + "\n\n---\n\n"
        body += "\n".join(format_item(item, i, language, labels) for i, item in enumerate(items, start=1))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(header + body)
    print(args.out)


if __name__ == "__main__":
    main()
