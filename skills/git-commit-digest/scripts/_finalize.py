from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

from _common import (
    exclusive_file_lock,
    fsync_directory,
    load_json,
    load_state,
    write_json_atomic,
)


TRANSACTION_VERSION = 1


def finalization_transaction_path(state_path: str | Path) -> Path:
    state = Path(state_path)
    return state.with_name(f"{state.name}.transaction.json")


def file_identity(path: str | Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def remove_file_durable(path: str | Path) -> None:
    target = Path(path)
    try:
        target.unlink()
    except FileNotFoundError:
        return
    fsync_directory(target.parent)


def validate_transaction(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("version") != TRANSACTION_VERSION:
        raise ValueError("invalid finalization transaction")
    required_strings = (
        "source_report",
        "prepared_report",
        "publish_report",
        "report_sha256",
    )
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_strings):
        raise ValueError("invalid finalization transaction paths or digest")
    if not isinstance(payload.get("report_size"), int) or payload["report_size"] < 0:
        raise ValueError("invalid finalization transaction report size")
    for key in ("base_state", "pending_state"):
        state = payload.get(key)
        if not isinstance(state, dict) or not isinstance(state.get("repositories"), dict):
            raise ValueError(f"invalid finalization transaction {key}")
    return payload


def build_transaction(
    *,
    state_path: str | Path,
    base_state: dict[str, Any],
    pending_state: dict[str, Any],
    source_report: str | Path,
    publish_report: str | Path,
) -> dict[str, Any]:
    source = Path(source_report).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"staged report does not exist: {source}")
    destination = Path(publish_report).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"published report already exists: {destination}")
    report_size, report_sha256 = file_identity(source)
    transaction_path = finalization_transaction_path(state_path).resolve()
    prepared = destination.with_name(
        f".{destination.name}.{transaction_path.name}.{report_sha256[:12]}.tmp"
    )
    return {
        "version": TRANSACTION_VERSION,
        "base_state": base_state,
        "pending_state": pending_state,
        "source_report": str(source),
        "prepared_report": str(prepared),
        "publish_report": str(destination),
        "report_size": report_size,
        "report_sha256": report_sha256,
    }


def matches_report(path: Path, transaction: dict[str, Any]) -> bool:
    if not path.is_file():
        return False
    return file_identity(path) == (
        transaction["report_size"],
        transaction["report_sha256"],
    )


def prepare_report(transaction: dict[str, Any]) -> Path:
    source = Path(transaction["source_report"])
    prepared = Path(transaction["prepared_report"])
    if matches_report(prepared, transaction):
        return prepared
    prepared.unlink(missing_ok=True)
    if not matches_report(source, transaction):
        raise RuntimeError("staged report is missing or changed during finalization recovery")
    prepared.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(prepared, "xb") as target_handle:
            with open(source, "rb") as source_handle:
                shutil.copyfileobj(source_handle, target_handle)
                target_handle.flush()
                os.fsync(target_handle.fileno())
        if not matches_report(prepared, transaction):
            raise RuntimeError("staged report changed while it was being prepared")
        fsync_directory(prepared.parent)
    except BaseException:
        prepared.unlink(missing_ok=True)
        raise
    return prepared


def publish_prepared_report(transaction: dict[str, Any]) -> Path:
    destination = Path(transaction["publish_report"])
    if destination.exists():
        if matches_report(destination, transaction):
            return destination
        raise FileExistsError(f"published report path contains different content: {destination}")
    prepared = prepare_report(transaction)
    try:
        os.link(prepared, destination)
    except FileExistsError:
        if not matches_report(destination, transaction):
            raise FileExistsError(
                f"published report path contains different content: {destination}"
            )
    fsync_directory(destination.parent)
    return destination


def recover_finalization_locked(state_path: str | Path) -> Path | None:
    transaction_path = finalization_transaction_path(state_path)
    if not transaction_path.is_file():
        return None
    transaction = validate_transaction(load_json(transaction_path))
    current = load_state(state_path)
    base_state = transaction["base_state"]
    pending_state = transaction["pending_state"]
    if current not in (base_state, pending_state):
        raise RuntimeError("state conflicts with an incomplete finalization transaction")

    try:
        published = publish_prepared_report(transaction)
    except FileExistsError:
        if current == base_state:
            remove_file_durable(transaction["prepared_report"])
            remove_file_durable(transaction_path)
        raise

    if current == base_state:
        write_json_atomic(state_path, pending_state)
    remove_file_durable(transaction["prepared_report"])
    remove_file_durable(transaction_path)
    return published


def recover_finalization(state_path: str | Path) -> Path | None:
    with exclusive_file_lock(state_path):
        return recover_finalization_locked(state_path)
