#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pathlib import Path

from _common import (
    exclusive_file_lock,
    load_config,
    load_required_state,
    load_state,
    resolve_output_file,
    write_json_atomic,
)
from _finalize import (
    build_transaction,
    finalization_transaction_path,
    recover_finalization_locked,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a report and promote its pending state.")
    parser.add_argument("--pending", required=True, help="next_state.json produced by fetch_commits.py")
    parser.add_argument("--base-state", required=True, help="base_state.json captured by fetch_commits.py")
    parser.add_argument("--config", required=True, help="Digest config JSON path")
    parser.add_argument("--report", required=True, help="Staged report in the run directory")
    parser.add_argument("--run-id", required=True, help="Run ID used by output_file templates")
    parser.add_argument("--date", required=True, help="Report date used by output_file templates")
    args = parser.parse_args()

    config = load_config(args.config)
    state_path = Path(config["state_directory"]) / "state.json"
    output_file = resolve_output_file(
        args.config,
        config,
        run_id=args.run_id,
        date=args.date,
    )
    pending = load_required_state(args.pending)
    base_state = load_required_state(args.base_state)
    with exclusive_file_lock(state_path):
        recover_finalization_locked(state_path)
        current = load_state(state_path)
        if current != base_state:
            raise RuntimeError("state changed since fetch; refusing to overwrite a newer cursor")
        transaction = build_transaction(
            state_path=state_path,
            base_state=base_state,
            pending_state=pending,
            source_report=args.report,
            publish_report=output_file,
        )
        write_json_atomic(finalization_transaction_path(state_path), transaction)
        published = recover_finalization_locked(state_path)
        if published is None:
            raise RuntimeError("finalization transaction disappeared before completion")
    print(published)


if __name__ == "__main__":
    main()
