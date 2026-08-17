#!/usr/bin/env python3
import argparse
import hashlib
import ipaddress
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


ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
PLACEHOLDER_RE = re.compile(r"#\{([A-Za-z_][A-Za-z0-9_]*)\}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SENSITIVE_KEY_PARTS = ("auth", "code", "key", "password", "secret", "token")
USER_AGENT = "send-webhook/1.0"
RESERVED_VARIABLES = {
    "message_id",
    "message_kind",
    "message_title",
    "date",
    "language",
    "content",
    "summary",
    "result",
    "timestamp",
}


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_RE.sub(lambda match: os.environ.get(match.group(1), match.group(0)), value)
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    return value


def find_pattern_names(value: Any, pattern: re.Pattern[str]) -> set[str]:
    if isinstance(value, str):
        return set(pattern.findall(value))
    if isinstance(value, list):
        names: set[str] = set()
        for item in value:
            names.update(find_pattern_names(item, pattern))
        return names
    if isinstance(value, dict):
        names = set()
        for item in value.values():
            names.update(find_pattern_names(item, pattern))
        return names
    return set()


def render(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        exact = PLACEHOLDER_RE.fullmatch(value)
        if exact:
            return variables[exact.group(1)]
        return PLACEHOLDER_RE.sub(lambda match: str(variables[match.group(1)]), value)
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    return value


def is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(part in lower for part in SENSITIVE_KEY_PARTS)


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = [(key, "***" if is_sensitive_key(key) else value) for key, value in query]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(redacted_query)))


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: "***" if is_sensitive_key(key) else value for key, value in headers.items()}


def load_config(path: str | Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("webhook config must be a JSON object")
    webhook = payload.get("webhook", payload)
    if not isinstance(webhook, dict):
        raise ValueError("webhook config must be a JSON object")
    if not webhook.get("enabled", False):
        return webhook
    expanded = expand_env(webhook)
    unresolved_env = sorted(find_pattern_names(expanded, ENV_RE))
    if unresolved_env:
        raise ValueError(f"unresolved environment variables: {', '.join(unresolved_env)}")
    return expanded


def validate_message(path: str | Path) -> dict[str, Any]:
    message = load_json(path)
    if not isinstance(message, dict):
        raise ValueError("message must be a JSON object")
    for key in ("id", "kind", "title", "date", "language"):
        value = message.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"message.{key} must be a non-empty string")
    if not DATE_RE.fullmatch(message["date"]):
        raise ValueError("message.date must use YYYY-MM-DD")
    try:
        datetime.strptime(message["date"], "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("message.date must use YYYY-MM-DD") from exc
    extra = message.get("variables", {})
    if not isinstance(extra, dict):
        raise ValueError("message.variables must be an object")
    conflicts = sorted(RESERVED_VARIABLES.intersection(extra))
    if conflicts:
        raise ValueError(f"message.variables cannot override built-ins: {', '.join(conflicts)}")
    return message


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


def build_variables(config: dict[str, Any], message: dict[str, Any], content: str) -> dict[str, Any]:
    variables: dict[str, Any] = {
        "message_id": message["id"],
        "message_kind": message["kind"],
        "message_title": message["title"],
        "date": message["date"],
        "language": message["language"],
        "content": content,
        "summary": content,
        "result": "success",
        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
    }
    variables.update(message.get("variables", {}))
    config_variables = config.get("variables", {})
    if not isinstance(config_variables, dict):
        raise ValueError("webhook.variables must be an object")
    conflicts = sorted(RESERVED_VARIABLES.intersection(config_variables))
    if conflicts:
        raise ValueError(f"webhook.variables cannot override built-ins: {', '.join(conflicts)}")
    unknown = sorted(find_pattern_names(config_variables, PLACEHOLDER_RE) - set(variables))
    if unknown:
        raise ValueError(f"unknown template variables: {', '.join(unknown)}")
    variables.update(render(config_variables, variables))
    return variables


def resolve_url(config: dict[str, Any], variables: dict[str, Any]) -> str:
    raw_url = config.get("url")
    url_env = config.get("url_env")
    if not raw_url and url_env:
        raw_url = os.getenv(str(url_env))
        if raw_url is None:
            raise ValueError(f"environment variable {url_env} is not set")
    if raw_url is None:
        raise ValueError("webhook.url or webhook.url_env is required when delivery is enabled")
    unknown = sorted(find_pattern_names(raw_url, PLACEHOLDER_RE) - set(variables))
    if unknown:
        raise ValueError(f"unknown template variables: {', '.join(unknown)}")
    url = str(render(str(raw_url), variables)).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"invalid webhook URL: {url}")
    return url


def build_request(config: dict[str, Any], variables: dict[str, Any]) -> tuple[str, bytes | None, dict[str, str], str]:
    template_values = [config.get("request_body"), config.get("headers")]
    unknown: set[str] = set()
    for value in template_values:
        unknown.update(find_pattern_names(value, PLACEHOLDER_RE) - set(variables))
    if unknown:
        raise ValueError(f"unknown template variables: {', '.join(sorted(unknown))}")

    url = resolve_url(config, variables)
    body = config.get("request_body")
    headers = parse_headers(config.get("headers"), variables)
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

    configured_method = config.get("method")
    method = str(configured_method).upper() if configured_method else ("POST" if body_bytes is not None else "GET")
    if method not in {"GET", "POST"}:
        raise ValueError("webhook.method must be GET or POST")
    headers.setdefault("User-Agent", USER_AGENT)
    return url, body_bytes, headers, method


def body_contains_passed(response_body: str, expected: Any) -> bool:
    if expected in (None, "", []):
        return True
    values = [expected] if isinstance(expected, str) else list(expected)
    return all(str(value) in response_body for value in values)


def write_result(path: str | None, result: dict[str, Any]) -> None:
    if path:
        write_json(path, result)
    print(json.dumps(result, ensure_ascii=False))


def is_loopback_url(url: str) -> bool:
    hostname = urllib.parse.urlparse(url).hostname
    if not hostname:
        return False
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def send_request(url: str, body: bytes | None, headers: dict[str, str], method: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    if is_loopback_url(url):
        response_context = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            request,
            timeout=timeout,
        )
    else:
        response_context = urllib.request.urlopen(request, timeout=timeout)
    with response_context as response:
        response_body = response.read().decode("utf-8", errors="replace")
        return int(response.status), response_body


def main() -> int:
    parser = argparse.ArgumentParser(description="Send an existing artifact through a configured webhook.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument("--out")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    request_url = ""
    message_id = ""
    message_kind = ""
    try:
        config = load_config(args.config)
        if not config.get("enabled", False):
            write_result(args.out, {"enabled": False, "skipped": True, "reason": "webhook disabled"})
            return 0

        message = validate_message(args.message)
        message_id = message["id"]
        message_kind = message["kind"]
        allowed_languages = config.get("languages")
        if allowed_languages and message["language"] not in allowed_languages:
            write_result(
                args.out,
                {
                    "enabled": True,
                    "skipped": True,
                    "message_id": message["id"],
                    "reason": f"language {message['language']} filtered by webhook.languages",
                },
            )
            return 0

        content = Path(args.content).read_text(encoding="utf-8")
        variables = build_variables(config, message, content)
        request_url, body, headers, method = build_request(config, variables)
        preview = {
            "enabled": True,
            "skipped": False,
            "dry_run": args.dry_run,
            "message_id": message["id"],
            "message_kind": message["kind"],
            "method": method,
            "url": redact_url(request_url),
            "headers": redact_headers(headers),
            "body_size_bytes": len(body) if body is not None else 0,
            "body_sha256": hashlib.sha256(body).hexdigest() if body is not None else None,
        }
        timeout = float(config.get("timeout_seconds", 30))
        if not 1 <= timeout <= 300:
            raise ValueError("webhook.timeout_seconds must be between 1 and 300")
        if args.dry_run:
            write_result(args.out, preview)
            return 0

        status_code, response_body = send_request(request_url, body, headers, method, timeout)
        body_ok = body_contains_passed(response_body, config.get("success_body_contains"))
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
            "url": redact_url(request_url) if request_url else "",
        }
        if message_id:
            result["message_id"] = message_id
            result["message_kind"] = message_kind
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
        if message_id:
            result["message_id"] = message_id
            result["message_kind"] = message_kind
        write_result(args.out, result)
        return 1


if __name__ == "__main__":
    sys.exit(main())
