#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit


ALLOWED_URL_SCHEMES = {"http", "https", "ssh", "git", "file"}
SCP_URL_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:.+$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
CACHE_FORMAT_VERSION = 2
OBJECT_ID_RE = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


class GitCommandError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args_list = args
        self.returncode = returncode
        self.stderr = stderr
        command = " ".join(args)
        detail = stderr.strip() or f"exit status {returncode}"
        super().__init__(f"{command}: {detail}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_json_atomic(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        fsync_directory(target.parent)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def fsync_directory(path: str | Path) -> None:
    """Persist directory-entry changes where the platform supports it."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(Path(path), os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)


def validate_remote_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("every config entry must be a non-empty Git remote URL string")
    url = value.strip()
    if any(ord(char) < 32 for char in url) or any(char.isspace() for char in url):
        raise ValueError(f"Git remote URL contains whitespace or control characters: {url!r}")
    if url.startswith("-"):
        raise ValueError(f"Git remote URL must not start with '-': {url!r}")

    parsed = urlsplit(url)
    if parsed.scheme:
        if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
            raise ValueError(f"unsupported Git remote URL scheme {parsed.scheme!r}: {url!r}")
        if parsed.scheme.lower() in {"http", "https"} and (parsed.username or parsed.password):
            raise ValueError("do not embed credentials in HTTP(S) repository URLs")
        return url

    if SCP_URL_RE.match(url):
        return url
    if Path(url).is_absolute():
        return url
    raise ValueError(f"unsupported Git remote URL: {url!r}")


def load_config(path: str | Path) -> list[str]:
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError("config.json must contain a JSON array of Git remote URL strings")
    urls = [validate_remote_url(value) for value in payload]
    if not urls:
        raise ValueError("config.json must contain at least one Git remote URL")
    duplicates = sorted({url for url in urls if urls.count(url) > 1})
    if duplicates:
        raise ValueError(f"config.json contains duplicate repositories: {', '.join(duplicates)}")
    return urls


def load_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"repositories": {}}
    payload = load_json(target)
    if not isinstance(payload, dict) or not isinstance(payload.get("repositories"), dict):
        raise ValueError("state.json must be an object with a repositories object")
    repositories: dict[str, Any] = {}
    for url, entry in payload["repositories"].items():
        if not isinstance(url, str) or not isinstance(entry, dict):
            raise ValueError("state.json contains an invalid repository entry")
        branch = entry.get("branch")
        head = entry.get("head")
        initial_since = entry.get("initial_since")
        initial_branch = entry.get("initial_branch")
        initial_head = entry.get("initial_head")
        initial_full_scan = entry.get("initial_full_scan")
        if head is not None:
            if not isinstance(branch, str) or not branch:
                raise ValueError(f"state entry for {url!r} has an invalid branch")
            if not isinstance(head, str) or not OBJECT_ID_RE.fullmatch(head):
                raise ValueError(f"state entry for {url!r} has an invalid head")
            if any(
                value is not None
                for value in (initial_since, initial_branch, initial_head, initial_full_scan)
            ):
                raise ValueError(f"state entry for {url!r} mixes a cursor with initial state")
            repositories[url] = {"branch": branch, "head": head.lower()}
            continue
        if branch is not None:
            raise ValueError(f"state entry for {url!r} has a branch without a head")
        if not isinstance(initial_since, str):
            raise ValueError(f"state entry for {url!r} has no cursor or initial_since")
        try:
            parsed_since = datetime.fromisoformat(initial_since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"state entry for {url!r} has an invalid initial_since") from exc
        if parsed_since.tzinfo is None:
            raise ValueError(f"state entry for {url!r} has an invalid initial_since")
        normalized_initial = {"initial_since": parsed_since.isoformat()}
        if initial_branch is not None or initial_head is not None:
            if not isinstance(initial_branch, str) or not initial_branch:
                raise ValueError(f"state entry for {url!r} has an invalid initial_branch")
            if not isinstance(initial_head, str) or not OBJECT_ID_RE.fullmatch(initial_head):
                raise ValueError(f"state entry for {url!r} has an invalid initial_head")
            normalized_initial.update(
                {"initial_branch": initial_branch, "initial_head": initial_head.lower()}
            )
            if initial_full_scan is not None:
                if not isinstance(initial_full_scan, bool):
                    raise ValueError(
                        f"state entry for {url!r} has an invalid initial_full_scan"
                    )
                normalized_initial["initial_full_scan"] = initial_full_scan
        elif initial_full_scan is not None:
            raise ValueError(f"state entry for {url!r} has initial_full_scan without a baseline")
        repositories[url] = normalized_initial
    return {"repositories": repositories}


def load_required_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"required state file does not exist: {target}")
    return load_state(target)


@contextmanager
def exclusive_file_lock(path: str | Path) -> Iterator[None]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f"{target.name}.lock")
    with open(lock_path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def git_command_and_env(args: list[str]) -> tuple[list[str], dict[str, str]]:
    command = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.ext.allow=never",
        *args,
    ]
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return command, env


def run_git(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    input_text: str | None = None,
    check: bool = True,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    command, env = git_command_and_env(args)
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if check and completed.returncode != 0:
        raise GitCommandError(command, completed.returncode, completed.stderr)
    return completed


def run_git_stdout_limited(
    args: list[str],
    *,
    max_bytes: int,
    cwd: str | Path | None = None,
    timeout: int = 600,
) -> tuple[str, bool]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    command, env = git_command_and_env(args)
    with tempfile.TemporaryFile() as stderr_buffer:
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=stderr_buffer,
            env=env,
        )
        if process.stdout is None:
            process.kill()
            process.wait()
            raise RuntimeError("failed to capture Git stdout")
        captured = bytearray()
        reader_done = threading.Event()
        reader_errors: list[BaseException] = []

        def read_bounded_prefix() -> None:
            try:
                while len(captured) < max_bytes + 1:
                    chunk = process.stdout.read(min(64 * 1024, max_bytes + 1 - len(captured)))
                    if not chunk:
                        break
                    captured.extend(chunk)
            except BaseException as exc:
                reader_errors.append(exc)
            finally:
                reader_done.set()

        started = time.monotonic()
        reader = threading.Thread(target=read_bounded_prefix, daemon=True)
        reader.start()
        if not reader_done.wait(timeout):
            process.kill()
            process.wait()
            process.stdout.close()
            reader.join(timeout=1)
            raise subprocess.TimeoutExpired(command, timeout)

        truncated = len(captured) > max_bytes
        terminated_for_limit = False
        if truncated and process.poll() is None:
            terminated_for_limit = True
            process.terminate()
        remaining = max(0.1, timeout - (time.monotonic() - started))
        try:
            returncode = process.wait(timeout=min(remaining, 5.0) if truncated else remaining)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait()
            if not truncated:
                process.stdout.close()
                reader.join(timeout=1)
                raise
        process.stdout.close()
        reader.join(timeout=1)
        stderr_buffer.seek(0)
        stderr = stderr_buffer.read().decode("utf-8", errors="replace")
        if reader_errors:
            raise RuntimeError("failed while reading bounded Git stdout") from reader_errors[0]
        if returncode != 0 and not terminated_for_limit:
            raise GitCommandError(command, returncode, stderr)
    encoded = bytes(captured)
    if truncated:
        encoded = encoded[:max_bytes]
    return encoded.decode("utf-8", errors="ignore"), truncated


def repository_name(url: str) -> str:
    if SCP_URL_RE.match(url):
        path = url.split(":", 1)[1]
    else:
        parsed = urlsplit(url)
        path = parsed.path if parsed.scheme else url
    name = Path(path.rstrip("/")).name
    if name.endswith(".git"):
        name = name[:-4]
    name = SAFE_NAME_RE.sub("-", name).strip("-._")
    return name or "repository"


def repository_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def cache_directory_name(url: str) -> str:
    return (
        f"{repository_name(url)}-{repository_id(url)[:10]}"
        f"-v{CACHE_FORMAT_VERSION}.git"
    )


def extract_items(payload: Any, key: str = "items") -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get(key)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"expected a JSON array or an object with a {key} array")
    return payload
