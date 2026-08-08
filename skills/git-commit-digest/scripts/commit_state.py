#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _common import exclusive_file_lock, load_required_state, load_state, write_json_atomic
from _finalize import (
    build_transaction,
    finalization_transaction_path,
    recover_finalization_locked,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a report and promote its pending state.")
    parser.add_argument("--pending", required=True, help="next_state.json produced by fetch_commits.py")
    parser.add_argument("--base-state", required=True, help="base_state.json captured by fetch_commits.py")
    parser.add_argument("--state", required=True, help="Persistent state.json path")
    parser.add_argument("--report", required=True, help="Staged report in the run directory")
    parser.add_argument("--publish-report", required=True, help="Final unique report path")
    args = parser.parse_args()

    pending = load_required_state(args.pending)
    base_state = load_required_state(args.base_state)
    with exclusive_file_lock(args.state):
        recover_finalization_locked(args.state)
        current = load_state(args.state)
        if current != base_state:
            raise RuntimeError("state changed since fetch; refusing to overwrite a newer cursor")
        transaction = build_transaction(
            state_path=args.state,
            base_state=base_state,
            pending_state=pending,
            source_report=args.report,
            publish_report=args.publish_report,
        )
        write_json_atomic(finalization_transaction_path(args.state), transaction)
        published = recover_finalization_locked(args.state)
        if published is None:
            raise RuntimeError("finalization transaction disappeared before completion")
    print(published)


if __name__ == "__main__":
    main()
