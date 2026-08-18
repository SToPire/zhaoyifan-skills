import html
import json
import os
import re
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
DEFAULT_DIGEST_TZ = timezone(timedelta(hours=8), "UTC+08:00")


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def find_unresolved_env(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(ENV_RE.findall(value))
    if isinstance(value, list):
        names: set[str] = set()
        for item in value:
            names.update(find_unresolved_env(item))
        return names
    if isinstance(value, dict):
        names = set()
        for item in value.values():
            names.update(find_unresolved_env(item))
        return names
    return set()


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


OUTPUT_FILE_FIELDS = {"date", "run_id"}


def load_config(path: str | Path) -> dict[str, Any]:
    config = expand_env(load_json(path))
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    unresolved_env = sorted(find_unresolved_env(config))
    if unresolved_env:
        raise ValueError(f"unresolved environment variables: {', '.join(unresolved_env)}")
    output_value = config.get("output_file")
    if not isinstance(output_value, str) or not output_value.strip():
        raise ValueError("config.output_file must be a non-empty Markdown path string")
    fields = {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(output_value)
        if field_name is not None
    }
    unsupported = sorted(fields - OUTPUT_FILE_FIELDS)
    if unsupported:
        raise ValueError(f"config.output_file contains unsupported fields: {', '.join(unsupported)}")
    return config


def resolve_output_file(
    config_path: str | Path,
    config: dict[str, Any],
    *,
    run_id: str,
    date: str,
) -> Path:
    output_value = str(config["output_file"]).format(run_id=run_id, date=date)
    output = Path(output_value).expanduser()
    if not output.is_absolute():
        output = Path(config_path).resolve().parent / output
    output = output.resolve()
    if output.suffix.lower() != ".md":
        raise ValueError(f"config.output_file must resolve to a .md file: {output}")
    return output


def load_items(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        payload = payload["items"]
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array or an object with an items array")
    return payload


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        payload = payload["items"]
    if not isinstance(payload, list):
        raise ValueError("expected a JSON array or object with an items array")
    return payload


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_digest_date(now: datetime | None = None) -> str:
    current = now or datetime.now(DEFAULT_DIGEST_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=DEFAULT_DIGEST_TZ)
    return current.astimezone(DEFAULT_DIGEST_TZ).strftime("%Y-%m-%d")


def iso_now() -> str:
    return utc_now().isoformat()


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def strip_html(text: Any) -> str:
    raw = "" if text is None else str(text)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</p\s*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s+", "\n", raw)
    return raw.strip()


def clamp_text(text: Any, limit: int) -> str:
    raw = "" if text is None else str(text)
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


def make_item(
    *,
    item_id: str,
    source_type: str,
    title: str,
    url: str,
    content: str = "",
    author: str | None = None,
    published_at: datetime | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(published_at, datetime):
        published = published_at.astimezone(timezone.utc).isoformat()
    elif isinstance(published_at, str) and published_at:
        parsed = parse_datetime(published_at)
        published = (parsed or utc_now()).isoformat()
    else:
        published = utc_now().isoformat()
    return {
        "id": item_id,
        "source_type": source_type,
        "title": title.strip() or "Untitled",
        "url": url,
        "content": content or "",
        "author": author,
        "published_at": published,
        "fetched_at": iso_now(),
        "metadata": metadata or {},
        "ai_score": None,
        "ai_reason": None,
        "ai_summary": None,
        "ai_tags": [],
    }


def count_by_source(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get("source_type") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts
