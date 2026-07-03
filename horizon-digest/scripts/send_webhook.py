#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _common import default_digest_date, load_config, load_items, load_json, write_json


PLACEHOLDER_RE = re.compile(r"#\{([A-Za-z_][A-Za-z0-9_]*)\}")
SENSITIVE_KEY_PARTS = ("auth", "code", "key", "password", "secret", "token")
USER_AGENT = "horizon-digest-webhook/0.1"


def is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(part in lower for part in SENSITIVE_KEY_PARTS)


def render(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return PLACEHOLDER_RE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    return value


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = [
        (key, "***" if is_sensitive_key(key) else value)
        for key, value in query
    ]
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(redacted_query))
    )


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: "***" if is_sensitive_key(key) else value
        for key, value in headers.items()
    }


def parse_headers(value: Any, variables: dict[str, Any]) -> dict[str, str]:
    if not value:
        return {}
    rendered = render(value, variables)
    if isinstance(rendered, dict):
        return {str(key): str(item) for key, item in rendered.items()}
    headers: dict[str, str] = {}
    for line in str(rendered).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            raise ValueError(f"invalid webhook header line: {stripped}")
        key, item = stripped.split(":", 1)
        headers[key.strip()] = item.strip()
    return headers


def resolve_url(webhook: dict[str, Any], variables: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_url = webhook.get("url")
    url_env = webhook.get("url_env")
    if not raw_url and url_env:
        raw_url = os.getenv(str(url_env))
        if raw_url is None:
            return None, f"env var {url_env} is not set"
    if raw_url is None:
        return None, "webhook.url or webhook.url_env is not configured"
    url = str(render(str(raw_url), variables)).strip()
    if not url:
        raise ValueError("webhook URL is empty")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"invalid webhook URL: {url}")
    return url, None


def build_variables(
    *,
    config: dict[str, Any],
    webhook: dict[str, Any],
    summary: str,
    items: list[dict[str, Any]],
    meta: dict[str, Any],
    language: str,
    date: str,
) -> dict[str, Any]:
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    all_items = int(meta.get("raw_count") or meta.get("total_fetched") or len(items))
    variables: dict[str, Any] = {
        "date": date,
        "language": language,
        "summary": summary,
        "important_items": len(items),
        "selected_items": len(items),
        "item_count": len(items),
        "all_items": all_items,
        "all_items_count": all_items,
        "raw_count": all_items,
        "result": "success",
        "message_kind": "summary",
        "timestamp": timestamp,
    }
    message_title = webhook.get("message_title")
    if not message_title:
        message_title = f"Horizon {date} 日报" if language == "zh" else f"Horizon {date} Daily"
    variables["message_title"] = render(str(message_title), variables)

    extra_vars = webhook.get("variables")
    if isinstance(extra_vars, dict):
        variables.update(render(extra_vars, variables))
    return variables


def build_request(
    webhook: dict[str, Any],
    variables: dict[str, Any],
) -> tuple[str, bytes | None, dict[str, str], str]:
    url, skip_reason = resolve_url(webhook, variables)
    if skip_reason:
        raise RuntimeError(skip_reason)
    assert url is not None

    body = webhook.get("request_body")
    headers = parse_headers(webhook.get("headers"), variables)
    method = "GET"
    body_bytes: bytes | None = None
    if body not in (None, "", {}):
        rendered_body = render(body, variables)
        if isinstance(rendered_body, (dict, list)):
            body_text = json.dumps(rendered_body, ensure_ascii=False)
            headers.setdefault("Content-Type", "application/json")
        else:
            body_text = str(rendered_body)
            try:
                json.loads(body_text)
                headers.setdefault("Content-Type", "application/json")
            except json.JSONDecodeError:
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        body_bytes = body_text.encode("utf-8")
        method = "POST"
    headers.setdefault("User-Agent", USER_AGENT)
    return url, body_bytes, headers, method


def body_contains_passed(response_body: str, expected: Any) -> bool:
    if expected in (None, "", []):
        return True
    if isinstance(expected, str):
        expected_values = [expected]
    else:
        expected_values = list(expected)
    return all(str(value) in response_body for value in expected_values)


def write_result(path: str | None, result: dict[str, Any]) -> None:
    if path:
        write_json(path, result)
    print(json.dumps(result, ensure_ascii=False))


def send_request(url: str, body: bytes | None, headers: dict[str, str], method: str) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        response_body = response.read().decode("utf-8", errors="replace")
        return int(response.status), response_body


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a rendered digest through an optional JSON-configured webhook.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--items")
    parser.add_argument("--meta")
    parser.add_argument("--out")
    parser.add_argument("--language")
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    webhook = config.get("webhook") or {}
    language = args.language or (config.get("languages") or ["zh"])[0]
    date = args.date or default_digest_date()

    if not webhook.get("enabled", False):
        result = {"enabled": False, "skipped": True, "reason": "webhook disabled"}
        write_result(args.out, result)
        return 0

    webhook_languages = webhook.get("languages")
    if webhook_languages and language not in webhook_languages:
        result = {
            "enabled": True,
            "skipped": True,
            "reason": f"language {language} filtered by webhook.languages",
        }
        write_result(args.out, result)
        return 0

    summary = Path(args.summary).read_text(encoding="utf-8")
    items = load_items(args.items) if args.items else []
    meta = load_json(args.meta) if args.meta else {}
    variables = build_variables(
        config=config,
        webhook=webhook,
        summary=summary,
        items=items,
        meta=meta,
        language=language,
        date=date,
    )

    request_url = ""
    try:
        resolved_url, skip_reason = resolve_url(webhook, variables)
        if skip_reason:
            result = {"enabled": True, "skipped": True, "reason": skip_reason}
            write_result(args.out, result)
            return 0
        request_url = resolved_url or ""
        request_url, body, headers, method = build_request(webhook, variables)
        preview = {
            "enabled": True,
            "skipped": False,
            "dry_run": args.dry_run,
            "method": method,
            "url": redact_url(request_url),
            "headers": redact_headers(headers),
        }
        if args.dry_run:
            write_result(args.out, preview)
            return 0

        status_code, response_body = send_request(request_url, body, headers, method)
        expected = webhook.get("success_body_contains")
        body_ok = body_contains_passed(response_body, expected)
        success = 200 <= status_code < 300 and body_ok
        result = {
            **preview,
            "dry_run": False,
            "success": success,
            "status_code": status_code,
            "body_contains_passed": body_ok,
            "response_body_preview": response_body[:2000],
        }
        write_result(args.out, result)
        return 0 if success else 1
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        result = {
            "enabled": True,
            "skipped": False,
            "success": False,
            "status_code": int(exc.code),
            "error": str(exc),
            "response_body_preview": response_body[:2000],
            "url": redact_url(request_url),
        }
        write_result(args.out, result)
        return 1
    except Exception as exc:
        result = {
            "enabled": True,
            "skipped": False,
            "success": False,
            "error": str(exc),
            "url": redact_url(request_url) if request_url else "",
        }
        write_result(args.out, result)
        return 1


if __name__ == "__main__":
    sys.exit(main())
