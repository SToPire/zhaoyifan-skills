#!/usr/bin/env python3
"""Fetch a lore.kernel.org thread mbox and extract per-message reading files."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import mailbox
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path


DEFAULT_LIST = "linux-erofs"
USER_AGENT = "linux-erofs-thread-skill/1.0"


def decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def clean_message_id(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    return value


def slugify(value: str) -> str:
    value = clean_message_id(value)
    value = re.sub(r"[^A-Za-z0-9._+-]+", "-", value).strip("-")
    if len(value) > 80:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
        value = f"{value[:69]}-{digest}"
    return value or "thread"


def parse_locator(locator: str, default_list: str) -> tuple[str, str, str]:
    locator = locator.strip()
    parsed = urllib.parse.urlparse(locator)
    if parsed.scheme and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        list_name = parts[0] if parts else default_list
        message_id = ""
        for part in parts[1:]:
            if part in {"T", "t", "raw"} or part.startswith("#"):
                break
            message_id = part
            break
        if not message_id:
            raise SystemExit(f"could not find Message-ID in URL path: {locator}")
        message_id = urllib.parse.unquote(message_id)
        canonical = f"https://lore.kernel.org/{list_name}/{urllib.parse.quote(message_id, safe='@:+._%-')}/T/#u"
        return list_name, clean_message_id(message_id), canonical

    message_id = clean_message_id(locator)
    canonical = f"https://lore.kernel.org/{default_list}/{urllib.parse.quote(message_id, safe='@:+._%-')}/T/#u"
    return default_list, message_id, canonical


def thread_mbox_url(list_name: str, message_id: str) -> str:
    quoted = urllib.parse.quote(clean_message_id(message_id), safe="@:+._%-")
    return f"https://lore.kernel.org/{list_name}/{quoted}/t.mbox.gz"


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def text_parts(message: Message) -> list[str]:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = (part.get("Content-Disposition") or "").lower()
            if content_type != "text/plain" or "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="replace"))
    else:
        payload = message.get_payload(decode=True)
        if payload is None:
            raw = message.get_payload()
            if isinstance(raw, str):
                parts.append(raw)
        else:
            charset = message.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="replace"))
    return parts


def normalize_body(body: str, limit: int) -> str:
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"\n{4,}", "\n\n\n", body).strip()
    if limit > 0 and len(body) > limit:
        return body[:limit] + "\n\n[truncated by fetch_lore_thread.py]"
    return body


def is_patch_message(subject: str, body: str) -> bool:
    subject_l = subject.lower()
    return "[patch" in subject_l or "diff --git " in body or "\n@@ " in body


def classify_message(subject: str, body: str) -> str:
    subject_l = subject.lower()
    if "cover" in subject_l or re.search(r"\[patch[^\]]*\s0+/\d+\]", subject_l):
        return "cover"
    if is_patch_message(subject, body):
        return "patch"
    if subject_l.startswith("re:"):
        return "reply"
    return "message"


def extract_headers(message: Message, index: int, body_limit: int) -> dict[str, object]:
    subject = decode_mime(message.get("Subject"))
    body = normalize_body("\n\n".join(text_parts(message)), body_limit)
    msgid = clean_message_id(decode_mime(message.get("Message-ID")))
    return {
        "index": index,
        "message_id": msgid,
        "subject": subject,
        "from": decode_mime(message.get("From")),
        "date": decode_mime(message.get("Date")),
        "to": decode_mime(message.get("To")),
        "cc": decode_mime(message.get("Cc")),
        "in_reply_to": clean_message_id(decode_mime(message.get("In-Reply-To"))),
        "references": decode_mime(message.get("References")),
        "role_hint": classify_message(subject, body),
        "has_patch": is_patch_message(subject, body),
        "body": body,
    }


def write_markdown(path: Path, canonical_url: str, messages: list[dict[str, object]]) -> None:
    lines = [
        f"# Lore Thread Messages",
        "",
        f"- canonical: {canonical_url}",
        f"- messages: {len(messages)}",
        "",
    ]
    for item in messages:
        body = str(item["body"])
        excerpt = body[:1200].strip()
        if len(body) > len(excerpt):
            excerpt += "\n[excerpt truncated]"
        lines.extend(
            [
                f"## {item['index']}. {item['subject']}",
                "",
                f"- From: {item['from']}",
                f"- Date: {item['date']}",
                f"- Message-ID: {item['message_id']}",
                f"- Role hint: {item['role_hint']}",
                f"- Has patch: {str(item['has_patch']).lower()}",
                "",
                "```text",
                excerpt,
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", "--message-id", dest="locator", required=True)
    parser.add_argument("--list", dest="list_name", default=DEFAULT_LIST)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--basename")
    parser.add_argument("--body-limit", type=int, default=60000)
    args = parser.parse_args()

    list_name, message_id, canonical = parse_locator(args.locator, args.list_name)
    url = thread_mbox_url(list_name, message_id)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = args.basename or slugify(message_id)

    compressed = fetch_url(url)
    try:
        mbox_bytes = gzip.decompress(compressed)
    except gzip.BadGzipFile:
        mbox_bytes = compressed

    mbox_path = output_dir / f"{basename}.mbox"
    json_path = output_dir / f"{basename}.messages.json"
    md_path = output_dir / f"{basename}.messages.md"
    if mbox_path.exists() or json_path.exists() or md_path.exists():
        raise SystemExit(f"refusing to overwrite existing files with basename {basename!r}")

    mbox_path.write_bytes(mbox_bytes)

    messages: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_mbox = Path(tmpdir) / "thread.mbox"
        tmp_mbox.write_bytes(mbox_bytes)
        box = mailbox.mbox(tmp_mbox)
        for index, message in enumerate(box, start=1):
            messages.append(extract_headers(message, index, args.body_limit))

    payload = {
        "source": {
            "locator": args.locator,
            "list": list_name,
            "message_id": message_id,
            "canonical_url": canonical,
            "mbox_url": url,
        },
        "message_count": len(messages),
        "messages": messages,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, canonical, messages)

    print(json.dumps({
        "canonical_url": canonical,
        "mbox": str(mbox_path),
        "json": str(json_path),
        "markdown": str(md_path),
        "message_count": len(messages),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
