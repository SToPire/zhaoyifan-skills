#!/usr/bin/env python3
from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_commits  # noqa: E402
import _finalize  # noqa: E402
import _common  # noqa: E402
import commit_state  # noqa: E402
from _common import load_config, run_git_stdout_limited  # noqa: E402
from render_digest import range_label  # noqa: E402


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, check=True, text=True, capture_output=True)


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(SCRIPTS / name), *args])


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def commit(
    repo: Path,
    filename: str,
    content: str,
    message: str,
    *,
    date: str | None = None,
) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    run(["git", "add", filename], cwd=repo)
    env = os.environ.copy()
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    run(["git", "commit", "-m", message], cwd=repo, env=env)
    return run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()


class GitCommitDigestWorkflowTests(unittest.TestCase):
    def test_config_is_only_a_url_array(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid.json"
            invalid = root / "invalid.json"
            write_json(valid, ["https://github.com/example/project.git"])
            write_json(invalid, {"repositories": ["https://github.com/example/project.git"]})

            self.assertEqual(load_config(valid), ["https://github.com/example/project.git"])
            with self.assertRaisesRegex(ValueError, "JSON array"):
                load_config(invalid)

    def test_first_run_backfill_is_not_clipped_by_initial_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            expected = [
                commit(source, "history.txt", "\n".join(str(value) for value in range(index + 1)), f"core: step {index}")
                for index in range(5)
            ]

            with mock.patch.object(fetch_commits, "INITIAL_FETCH_DEPTH", 2):
                repository, _next_state = fetch_commits.fetch_repository(
                    source.as_uri(),
                    {"repositories": {}},
                    root / "mirrors",
                )

            self.assertEqual([item["sha"] for item in repository["commits"]], expected)

    def test_first_run_reuses_its_persisted_boundary_after_a_late_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            first_start = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
            expected = commit(
                source,
                "history.txt",
                "kept\n",
                "core: keep across retry",
                date="2026-08-07T00:00:00+00:00",
            )
            state_path = root / "state.json"
            url = source.as_uri()
            initial_state, initial_errors = fetch_commits.ensure_initial_subscriptions(
                state_path,
                [url],
                first_start,
            )
            self.assertEqual(initial_errors, {})
            late_retry = first_start + timedelta(hours=30)
            retry_state, retry_errors = fetch_commits.ensure_initial_subscriptions(
                state_path,
                [url],
                late_retry,
            )

            self.assertEqual(retry_errors, {})
            self.assertEqual(retry_state, initial_state)
            repository, _next_state = fetch_commits.fetch_repository(
                url,
                retry_state,
                root / "mirrors",
                late_retry,
            )
            self.assertTrue(repository["first_run"])
            self.assertEqual([item["sha"] for item in repository["commits"]], [expected])

    def test_first_run_includes_old_dated_commits_reachable_after_initial_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            commit(
                source,
                "history.txt",
                "base\n",
                "core: old baseline",
                date="2020-01-01T00:00:00+00:00",
            )
            first_start = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
            url = source.as_uri()
            state, errors = fetch_commits.ensure_initial_subscriptions(
                root / "state.json",
                [url],
                first_start,
            )
            self.assertEqual(errors, {})
            expected = commit(
                source,
                "history.txt",
                "base\nnewly reachable\n",
                "core: old-dated new reachability",
                date="2020-01-02T00:00:00+00:00",
            )

            repository, _next_state = fetch_commits.fetch_repository(
                url,
                state,
                root / "mirrors",
                first_start + timedelta(hours=1),
            )

            self.assertTrue(repository["first_run"])
            self.assertEqual([item["sha"] for item in repository["commits"]], [expected])

    def test_interrupted_initial_discovery_full_scans_beyond_the_shallow_tip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            expected = [
                commit(
                    source,
                    "history.txt",
                    "\n".join(str(value) for value in range(index + 1)) + "\n",
                    f"core: old step {index}",
                    date=f"2020-01-0{index + 1}T00:00:00+00:00",
                )
                for index in range(3)
            ]
            url = source.as_uri()
            state_path = root / "state.json"
            write_json(
                state_path,
                {
                    "repositories": {
                        url: {"initial_since": "2026-08-06T12:00:00+00:00"}
                    }
                },
            )
            state, errors = fetch_commits.ensure_initial_subscriptions(
                state_path,
                [url],
                datetime(2026, 8, 8, tzinfo=timezone.utc),
            )
            self.assertEqual(errors, {})
            self.assertTrue(state["repositories"][url]["initial_full_scan"])

            repository, _next_state = fetch_commits.fetch_repository(
                url,
                state,
                root / "mirrors",
                datetime(2026, 8, 8, tzinfo=timezone.utc),
            )

            self.assertEqual([item["sha"] for item in repository["commits"]], expected)

    def test_first_run_materializes_parent_beyond_shallow_time_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            parent = commit(
                source,
                "history.txt",
                "old\n",
                "core: old base",
                date="2020-01-01T00:00:00+00:00",
            )
            current = commit(
                source,
                "history.txt",
                "old\nnew\n",
                "core: recent follow-up",
            )

            repository, _next_state = fetch_commits.fetch_repository(
                source.as_uri(),
                {"repositories": {}},
                root / "mirrors",
            )

            self.assertEqual([item["sha"] for item in repository["commits"]], [current])
            fetched = repository["commits"][0]
            self.assertEqual(fetched["parents"], [parent])
            self.assertEqual(fetched["patch_kind"], "first-parent")
            self.assertEqual(fetched["stats"]["additions"], 1)
            self.assertNotIn("/dev/null", fetched["patch"])

    def test_default_branch_rename_reuses_the_saved_sha_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "master", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            previous = commit(source, "history.txt", "base\n", "core: add base")
            run(["git", "branch", "-m", "main"], cwd=source)
            current = commit(
                source,
                "history.txt",
                "base\nold-dated change\n",
                "core: add old-dated change",
                date="2020-01-02T00:00:00+00:00",
            )
            state = {
                "repositories": {
                    source.as_uri(): {"branch": "master", "head": previous}
                }
            }

            repository, _next_state = fetch_commits.fetch_repository(
                source.as_uri(),
                state,
                root / "mirrors",
            )

            self.assertTrue(repository["branch_changed"])
            self.assertFalse(repository["first_run"])
            self.assertEqual([item["sha"] for item in repository["commits"]], [current])

    def test_missing_cache_deepens_until_the_saved_cursor_is_connected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            previous = commit(source, "history.txt", "0\n", "core: step 0")
            expected = []
            for index in range(1, 7):
                expected.append(
                    commit(
                        source,
                        "history.txt",
                        "\n".join(str(value) for value in range(index + 1)) + "\n",
                        f"core: step {index}",
                    )
                )
            state = {
                "repositories": {
                    source.as_uri(): {"branch": "main", "head": previous}
                }
            }
            with (
                mock.patch.object(fetch_commits, "INITIAL_FETCH_DEPTH", 2),
                mock.patch.object(fetch_commits, "MAX_DEEPEN_ATTEMPTS", 1),
            ):
                repository, _next_state = fetch_commits.fetch_repository(
                    source.as_uri(),
                    state,
                    root / "new-mirrors",
                )
            self.assertEqual([item["sha"] for item in repository["commits"]], expected)

    def test_pruned_force_push_does_not_advance_without_the_saved_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            remote = root / "remote.git"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            commit(source, "history.txt", "a\n", "core: A")
            shared = commit(source, "history.txt", "a\nb\n", "core: B")
            previous = commit(source, "history.txt", "a\nb\nc\n", "core: C")
            run(["git", "clone", "--bare", str(source), str(remote)])

            run(["git", "reset", "--hard", shared], cwd=source)
            commit(source, "history.txt", "a\nb\nd\n", "core: D")
            run(["git", "remote", "add", "origin", str(remote)], cwd=source)
            run(["git", "push", "--force", "origin", "main:main"], cwd=source)
            run(["git", "reflog", "expire", "--expire=now", "--all"], cwd=remote)
            run(["git", "gc", "--prune=now"], cwd=remote)
            missing = subprocess.run(
                ["git", "cat-file", "-e", f"{previous}^{{commit}}"],
                cwd=remote,
                capture_output=True,
            )
            self.assertNotEqual(missing.returncode, 0)

            state = {"repositories": {remote.as_uri(): {"branch": "main", "head": previous}}}
            with self.assertRaisesRegex(RuntimeError, "previous cursor is no longer available"):
                fetch_commits.fetch_repository(
                    remote.as_uri(),
                    state,
                    root / "new-mirrors",
                )

    def test_oversized_rewritten_history_does_not_return_an_advanced_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            commit(source, "history.txt", "one\n", "core: one")
            shared = commit(source, "history.txt", "one\ntwo\n", "core: two")
            previous = commit(source, "history.txt", "one\ntwo\nthree\n", "core: three")
            cache = root / "mirrors"
            fetch_commits.ensure_cache(source.as_uri(), "main", cache, None)
            run(["git", "reset", "--hard", shared], cwd=source)
            commit(source, "history.txt", "one\ntwo\nrewritten\n", "core: rewritten")
            state = {"repositories": {source.as_uri(): {"branch": "main", "head": previous}}}

            with (
                mock.patch.object(fetch_commits, "MAX_REWRITE_COMMITS", 0),
                self.assertRaisesRegex(RuntimeError, "cursor was not advanced"),
            ):
                fetch_commits.fetch_repository(
                    source.as_uri(),
                    state,
                    cache,
                )

    def test_missing_pending_state_is_rejected_without_clearing_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state.json"
            base = root / "base.json"
            payload = {
                "repositories": {
                    "https://example.com/project.git": {
                        "branch": "main",
                        "head": "a" * 40,
                    }
                }
            }
            write_json(state, payload)
            write_json(base, payload)
            staged_report = root / "report.md"
            staged_report.write_text("report\n", encoding="utf-8")
            published_report = root / "reports" / "run.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "commit_state.py"),
                    "--pending",
                    str(root / "missing.json"),
                    "--base-state",
                    str(base),
                    "--state",
                    str(state),
                    "--report",
                    str(staged_report),
                    "--publish-report",
                    str(published_report),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), payload)
            self.assertFalse(published_report.exists())

    def test_state_compare_and_swap_rejects_a_stale_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state.json"
            base = root / "base.json"
            pending = root / "pending.json"
            url = "https://example.com/project.git"
            base_payload = {"repositories": {url: {"branch": "main", "head": "a" * 40}}}
            newer_payload = {"repositories": {url: {"branch": "main", "head": "c" * 40}}}
            stale_pending = {"repositories": {url: {"branch": "main", "head": "b" * 40}}}
            write_json(base, base_payload)
            write_json(state, newer_payload)
            write_json(pending, stale_pending)
            staged_report = root / "report.md"
            staged_report.write_text("report\n", encoding="utf-8")
            published_report = root / "reports" / "run.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "commit_state.py"),
                    "--pending",
                    str(pending),
                    "--base-state",
                    str(base),
                    "--state",
                    str(state),
                    "--report",
                    str(staged_report),
                    "--publish-report",
                    str(published_report),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("state changed since fetch", completed.stderr)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), newer_payload)
            self.assertFalse(published_report.exists())

    def test_report_publish_collision_does_not_advance_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state.json"
            base = root / "base.json"
            pending = root / "pending.json"
            staged_report = root / "report.md"
            published_report = root / "reports" / "run.md"
            url = "https://example.com/project.git"
            base_payload = {"repositories": {url: {"branch": "main", "head": "a" * 40}}}
            pending_payload = {"repositories": {url: {"branch": "main", "head": "b" * 40}}}
            write_json(state, base_payload)
            write_json(base, base_payload)
            write_json(pending, pending_payload)
            staged_report.write_text("new report\n", encoding="utf-8")
            published_report.parent.mkdir(parents=True)
            published_report.write_text("existing report\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "commit_state.py"),
                    "--pending",
                    str(pending),
                    "--base-state",
                    str(base),
                    "--state",
                    str(state),
                    "--report",
                    str(staged_report),
                    "--publish-report",
                    str(published_report),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), base_payload)
            self.assertEqual(published_report.read_text(encoding="utf-8"), "existing report\n")

    def test_incomplete_finalization_is_recovered_after_abrupt_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state.json"
            base = root / "base.json"
            pending = root / "pending.json"
            staged_report = root / "run" / "report.md"
            published_report = root / "reports" / "run.md"
            url = "https://example.com/project.git"
            base_payload = {"repositories": {url: {"branch": "main", "head": "a" * 40}}}
            pending_payload = {"repositories": {url: {"branch": "main", "head": "b" * 40}}}
            write_json(state, base_payload)
            write_json(base, base_payload)
            write_json(pending, pending_payload)
            staged_report.parent.mkdir(parents=True)
            staged_report.write_text("recoverable report\n", encoding="utf-8")

            arguments = [
                "commit_state.py",
                "--pending",
                str(pending),
                "--base-state",
                str(base),
                "--state",
                str(state),
                "--report",
                str(staged_report),
                "--publish-report",
                str(published_report),
            ]
            with (
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(_finalize, "write_json_atomic", side_effect=KeyboardInterrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                commit_state.main()

            self.assertTrue(published_report.is_file())
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), base_payload)
            self.assertTrue(_finalize.finalization_transaction_path(state).is_file())

            recovered = _finalize.recover_finalization(state)
            self.assertEqual(recovered, published_report.resolve())
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), pending_payload)
            self.assertFalse(_finalize.finalization_transaction_path(state).exists())

    def test_git_patch_capture_returns_only_the_bounded_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            sha = commit(source, "large.txt", "line\n" * 5000, "core: add large file")
            patch, truncated = run_git_stdout_limited(
                ["show", "--format=", "--root", sha],
                max_bytes=1024,
                cwd=source,
            )
            self.assertTrue(truncated)
            self.assertLessEqual(len(patch.encode("utf-8")), 1024)

    def test_bounded_git_capture_terminates_after_reaching_the_limit(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"x" * 4096)
                self.returncode: int | None = None
                self.terminated = False

            def poll(self) -> int | None:
                return self.returncode

            def terminate(self) -> None:
                self.terminated = True
                self.returncode = -15

            def kill(self) -> None:
                self.returncode = -9

            def wait(self, timeout: float | None = None) -> int:
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

        process = FakeProcess()
        with mock.patch.object(_common.subprocess, "Popen", return_value=process):
            output, truncated = run_git_stdout_limited(
                ["show", "HEAD"],
                max_bytes=128,
            )

        self.assertTrue(truncated)
        self.assertEqual(len(output.encode("utf-8")), 128)
        self.assertTrue(process.terminated)

    def test_commit_message_and_numstat_are_bounded_before_batching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            sha = commit(
                source,
                "bounded.txt",
                "bounded\n",
                "core: bounded evidence\n\n" + "detail " * 1000,
            )
            with (
                mock.patch.object(fetch_commits, "MAX_COMMIT_MESSAGE_BYTES", 512),
                mock.patch.object(fetch_commits, "MAX_NUMSTAT_BYTES", 8),
            ):
                fetched = fetch_commits.read_commit(
                    source,
                    source.as_uri(),
                    "repo",
                    sha,
                )

            self.assertTrue(fetched["message_truncated"])
            self.assertIn("[commit message truncated]", fetched["message"])
            self.assertTrue(fetched["files_truncated"])
            self.assertEqual(fetched["files"], [])

    def test_oversized_identity_metadata_is_truncated_without_blocking_the_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            (source / "identity.txt").write_text("identity\n", encoding="utf-8")
            run(["git", "add", "identity.txt"], cwd=source)
            env = os.environ.copy()
            env["GIT_AUTHOR_NAME"] = "A" * 4096
            env["GIT_AUTHOR_EMAIL"] = "author@example.com"
            env["GIT_COMMITTER_NAME"] = "C" * 4096
            env["GIT_COMMITTER_EMAIL"] = "committer@example.com"
            run(["git", "commit", "-m", "core: bounded identity"], cwd=source, env=env)
            sha = run(["git", "rev-parse", "HEAD"], cwd=source).stdout.strip()

            with mock.patch.object(fetch_commits, "MAX_IDENTITY_METADATA_BYTES", 64):
                fetched = fetch_commits.read_commit(
                    source,
                    source.as_uri(),
                    "repo",
                    sha,
                )

            self.assertEqual(fetched["sha"], sha)
            self.assertEqual(fetched["subject"], "core: bounded identity")
            self.assertTrue(fetched["identities_truncated"])

    def test_batches_enforce_max_chars_and_record_analysis_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.json"
            meta = root / "meta.json"
            out_dir = root / "batches"
            files = [
                {"path": f"path/{index}.txt", "additions": 1, "deletions": 0, "binary": False}
                for index in range(150)
            ]
            write_json(
                raw,
                {
                    "repositories": [
                        {
                            "id": "repo",
                            "name": "project",
                            "url": "https://example.com/project.git",
                            "branch": "main",
                            "status": "success",
                            "commits": [
                                {
                                    "id": "repo:" + "a" * 40,
                                    "sha": "a" * 40,
                                    "short_sha": "a" * 12,
                                    "subject": "large commit",
                                    "message": "purpose\n" * 500,
                                    "author": {"name": "A", "email": "a@example.com", "date": "2026-08-07T00:00:00Z"},
                                    "committer": {"name": "C", "email": "c@example.com", "date": "2026-08-07T00:00:00Z"},
                                    "trailers": {},
                                    "files": files,
                                    "stats": {"files_changed": len(files), "additions": len(files), "deletions": 0},
                                    "patch": "diff line\n" * 10000,
                                    "patch_truncated": False,
                                    "merge_context_only": False,
                                }
                            ],
                        }
                    ]
                },
            )
            write_json(meta, {"warnings": []})
            run_script(
                "pack_analysis_batches.py",
                "--input",
                str(raw),
                "--out-dir",
                str(out_dir),
                "--meta",
                str(meta),
                "--max-chars",
                "3000",
            )
            index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index["batches"]), 1)
            batch_text = (out_dir / index["batches"][0]["file"]).read_text(encoding="utf-8")
            self.assertLessEqual(len(batch_text), 3000)
            updated_meta = json.loads(meta.read_text(encoding="utf-8"))
            self.assertEqual(len(updated_meta["analysis_truncations"]), 1)
            self.assertTrue(updated_meta["analysis_truncations"][0]["patch"])
            self.assertTrue(updated_meta["warnings"])

    def test_detect_default_branch_matches_a_raw_head_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            remote = root / "remote.git"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            commit(source, "main.txt", "main\n", "core: add main")
            run(["git", "checkout", "-b", "develop"], cwd=source)
            develop = commit(source, "develop.txt", "develop\n", "core: add develop")
            run(["git", "clone", "--bare", str(source), str(remote)])
            run(["git", "update-ref", "--no-deref", "HEAD", develop], cwd=remote)

            branch, head = fetch_commits.detect_default_branch(remote.as_uri())

            self.assertEqual((branch, head), ("develop", develop))

    def test_remote_advancement_between_discovery_and_fetch_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            previous = commit(source, "history.txt", "one\n", "core: add one")
            current = commit(source, "history.txt", "one\ntwo\n", "core: add two")
            state = {
                "repositories": {
                    source.as_uri(): {"branch": "main", "head": previous}
                }
            }
            with mock.patch.object(
                fetch_commits,
                "detect_default_branch",
                return_value=("main", previous),
            ):
                repository, _next_state = fetch_commits.fetch_repository(
                    source.as_uri(),
                    state,
                    root / "mirrors",
                )
            self.assertEqual([item["sha"] for item in repository["commits"]], [current])

    def test_all_failed_first_run_has_an_accurate_range_label(self) -> None:
        repositories = [
            {"status": "failed", "first_run": True},
            {"status": "failed", "first_run": True},
        ]
        self.assertEqual(range_label(repositories, 24), "首次运行（尚未建立成功状态）")

    def test_end_to_end_incremental_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            first_sha = commit(source, "feature.txt", "first\n", "core: add first behavior")

            work = root / "work"
            config = work / "config.json"
            state = work / "state.json"
            cache = work / "mirrors"
            first_run = work / "runs" / "first"
            write_json(config, [source.as_uri()])

            run_script(
                "fetch_commits.py",
                "--config",
                str(config),
                "--state",
                str(state),
                "--cache-dir",
                str(cache),
                "--out",
                str(first_run / "raw_commits.json"),
                "--base-state-out",
                str(first_run / "base_state.json"),
                "--next-state-out",
                str(first_run / "next_state.json"),
                "--meta-out",
                str(first_run / "meta.json"),
            )
            raw = json.loads((first_run / "raw_commits.json").read_text(encoding="utf-8"))
            repository = raw["repositories"][0]
            self.assertEqual(repository["status"], "success", repository.get("error"))
            self.assertEqual(repository["branch"], "main")
            self.assertEqual([item["sha"] for item in repository["commits"]], [first_sha])
            self.assertTrue(repository["first_run"])

            batches = first_run / "analysis-batches"
            run_script(
                "pack_analysis_batches.py",
                "--input",
                str(first_run / "raw_commits.json"),
                "--out-dir",
                str(batches),
                "--meta",
                str(first_run / "meta.json"),
            )
            batch_index = json.loads((batches / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(batch_index["batches"]), 1)

            commit_ids = [item["id"] for item in repository["commits"]]
            write_json(
                first_run / "analyses.json",
                [
                    {
                        "id": item_id,
                        "purpose": "增加第一项行为。",
                        "changes": ["新增功能文件。"],
                        "impact": "提供新的内部行为。",
                        "category": "feature",
                        "subsystem": "core",
                        "confidence": "high",
                    }
                    for item_id in commit_ids
                ],
            )
            run_script(
                "validate_commit_analyses.py",
                "--commits",
                str(first_run / "raw_commits.json"),
                "--analyses",
                str(first_run / "analyses.json"),
                "--out",
                str(first_run / "analyzed_commits.json"),
            )
            write_json(
                first_run / "digest.json",
                {
                    "overview": ["source 仓库增加了一项核心行为。"],
                    "repositories": [
                        {
                            "id": repository["id"],
                            "overview": "本次只有一项功能更新。",
                            "groups": [
                                {
                                    "title": "core：增加第一项行为",
                                    "purpose": "提供新的核心行为。",
                                    "changes": ["新增功能文件。"],
                                    "impact": "影响内部核心模块。",
                                    "commit_ids": commit_ids,
                                }
                            ],
                        }
                    ],
                },
            )
            run_script(
                "validate_digest.py",
                "--commits",
                str(first_run / "analyzed_commits.json"),
                "--digest",
                str(first_run / "digest.json"),
                "--out",
                str(first_run / "validated_digest.json"),
            )
            report = first_run / "report.md"
            published_report = work / "reports" / "first.md"
            run_script(
                "render_digest.py",
                "--commits",
                str(first_run / "analyzed_commits.json"),
                "--digest",
                str(first_run / "validated_digest.json"),
                "--out",
                str(report),
                "--date",
                "2026-08-07",
            )
            rendered = report.read_text(encoding="utf-8")
            self.assertIn("# Git Commit Digest · 2026-08-07", rendered)
            self.assertIn("## 今日概览", rendered)
            self.assertIn("### core：增加第一项行为", rendered)
            self.assertNotIn("异常与限制", rendered)

            run_script(
                "commit_state.py",
                "--pending",
                str(first_run / "next_state.json"),
                "--base-state",
                str(first_run / "base_state.json"),
                "--state",
                str(state),
                "--report",
                str(report),
                "--publish-report",
                str(published_report),
            )
            saved_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved_state["repositories"][source.as_uri()]["head"], first_sha)
            self.assertEqual(published_report.read_text(encoding="utf-8"), rendered)

            second_sha = commit(source, "feature.txt", "first\nsecond\n", "core: add second behavior")
            second_run = work / "runs" / "second"
            run_script(
                "fetch_commits.py",
                "--config",
                str(config),
                "--state",
                str(state),
                "--cache-dir",
                str(cache),
                "--out",
                str(second_run / "raw_commits.json"),
                "--base-state-out",
                str(second_run / "base_state.json"),
                "--next-state-out",
                str(second_run / "next_state.json"),
                "--meta-out",
                str(second_run / "meta.json"),
            )
            second_raw = json.loads((second_run / "raw_commits.json").read_text(encoding="utf-8"))
            second_repository = second_raw["repositories"][0]
            self.assertFalse(second_repository["first_run"])
            self.assertEqual([item["sha"] for item in second_repository["commits"]], [second_sha])

    def test_digest_validation_rejects_omitted_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commits = root / "commits.json"
            digest = root / "digest.json"
            write_json(
                commits,
                {
                    "repositories": [
                        {
                            "id": "repo",
                            "status": "success",
                            "commits": [
                                {"id": "repo:a", "analysis": {}},
                                {"id": "repo:b", "analysis": {}},
                            ],
                        }
                    ]
                },
            )
            write_json(
                digest,
                {
                    "overview": ["概览"],
                    "repositories": [
                        {
                            "id": "repo",
                            "overview": "仓库概览",
                            "groups": [
                                {
                                    "title": "主题",
                                    "purpose": "目的",
                                    "changes": ["修改"],
                                    "impact": "影响",
                                    "commit_ids": ["repo:a"],
                                }
                            ],
                        }
                    ],
                },
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_digest.py"),
                    "--commits",
                    str(commits),
                    "--digest",
                    str(digest),
                    "--out",
                    str(root / "out.json"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("omits commits", completed.stderr)

    def test_merge_commit_is_kept_as_context_without_a_duplicate_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            commit(source, "base.txt", "base\n", "core: add base")
            run(["git", "checkout", "-b", "topic"], cwd=source)
            commit(source, "topic.txt", "topic\n", "core: add topic")
            run(["git", "checkout", "main"], cwd=source)
            commit(source, "main.txt", "main\n", "core: update main")
            run(["git", "merge", "--no-ff", "topic", "-m", "Merge topic changes"], cwd=source)

            work = root / "work"
            config = work / "config.json"
            write_json(config, [source.as_uri()])
            run_script(
                "fetch_commits.py",
                "--config",
                str(config),
                "--state",
                str(work / "state.json"),
                "--cache-dir",
                str(work / "mirrors"),
                "--out",
                str(work / "raw.json"),
                "--base-state-out",
                str(work / "base.json"),
                "--next-state-out",
                str(work / "next.json"),
                "--meta-out",
                str(work / "meta.json"),
            )
            raw = json.loads((work / "raw.json").read_text(encoding="utf-8"))
            commits = raw["repositories"][0]["commits"]
            merges = [item for item in commits if item["is_merge"]]
            self.assertEqual(len(merges), 1)
            self.assertEqual(merges[0]["subject"], "Merge topic changes")
            self.assertTrue(merges[0]["merge_context_only"])
            self.assertEqual(merges[0]["patch"], "")
            self.assertEqual(merges[0]["files"], [])
            self.assertEqual(
                merges[0]["stats"],
                {"files_changed": 0, "additions": 0, "deletions": 0},
            )

    def test_merge_conflict_keeps_a_combined_resolution_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            run(["git", "config", "user.name", "Digest Test"], cwd=source)
            run(["git", "config", "user.email", "digest@example.com"], cwd=source)
            commit(source, "conflict.txt", "base\n", "core: add base")
            run(["git", "checkout", "-b", "topic"], cwd=source)
            commit(source, "conflict.txt", "topic\n", "core: update topic")
            run(["git", "checkout", "main"], cwd=source)
            commit(source, "conflict.txt", "main\n", "core: update main")
            merged = subprocess.run(
                ["git", "merge", "--no-ff", "topic", "-m", "Merge topic with resolution"],
                cwd=source,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(merged.returncode, 0)
            (source / "conflict.txt").write_text("resolved uniquely\n", encoding="utf-8")
            run(["git", "add", "conflict.txt"], cwd=source)
            run(["git", "commit", "-m", "Merge topic with resolution"], cwd=source)

            repository, _next_state = fetch_commits.fetch_repository(
                source.as_uri(),
                {"repositories": {}},
                root / "mirrors",
            )
            merge = next(item for item in repository["commits"] if item["is_merge"])
            self.assertEqual(merge["patch_kind"], "combined")
            self.assertFalse(merge["merge_context_only"])
            self.assertIn("resolved uniquely", merge["patch"])
            self.assertEqual([item["path"] for item in merge["files"]], ["conflict.txt"])

    def test_failed_repository_keeps_its_previous_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing_remote = "/definitely/missing/git-commit-digest-repository.git"
            config = root / "config.json"
            state = root / "state.json"
            pending = root / "pending.json"
            write_json(config, [missing_remote])
            write_json(
                state,
                {
                    "repositories": {
                        missing_remote: {
                            "branch": "main",
                            "head": "a" * 40,
                        }
                    }
                },
            )
            run_script(
                "fetch_commits.py",
                "--config",
                str(config),
                "--state",
                str(state),
                "--cache-dir",
                str(root / "mirrors"),
                "--out",
                str(root / "raw.json"),
                "--base-state-out",
                str(root / "base.json"),
                "--next-state-out",
                str(pending),
                "--meta-out",
                str(root / "meta.json"),
            )
            raw = json.loads((root / "raw.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["repositories"][0]["status"], "failed")
            self.assertEqual(
                json.loads(pending.read_text(encoding="utf-8")),
                json.loads(state.read_text(encoding="utf-8")),
            )

    def test_empty_digest_renders_without_repository_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.json"
            analyses = root / "analyses.json"
            analyzed = root / "analyzed.json"
            digest = root / "digest.json"
            validated = root / "validated.json"
            report = root / "report.md"
            write_json(
                raw,
                {
                    "generated_at": "2026-08-07T01:00:00+00:00",
                    "initial_backfill_hours": 24,
                    "repositories": [
                        {
                            "id": "repo",
                            "name": "project",
                            "branch": "main",
                            "status": "success",
                            "first_run": False,
                            "commits": [],
                        }
                    ],
                },
            )
            write_json(analyses, [])
            run_script(
                "validate_commit_analyses.py",
                "--commits",
                str(raw),
                "--analyses",
                str(analyses),
                "--out",
                str(analyzed),
            )
            write_json(digest, {"overview": [], "repositories": []})
            run_script(
                "validate_digest.py",
                "--commits",
                str(analyzed),
                "--digest",
                str(digest),
                "--out",
                str(validated),
            )
            run_script(
                "render_digest.py",
                "--commits",
                str(analyzed),
                "--digest",
                str(validated),
                "--out",
                str(report),
                "--date",
                "2026-08-07",
            )
            rendered = report.read_text(encoding="utf-8")
            self.assertIn("| project | main | 0 | 0 | 无变化 |", rendered)
            self.assertIn("订阅仓库没有新增 Commit", rendered)
            self.assertNotIn("## project", rendered)

    def test_renderer_refuses_to_overwrite_an_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commits = root / "commits.json"
            digest = root / "digest.json"
            report = root / "report.md"
            write_json(
                commits,
                {
                    "generated_at": "2026-08-07T01:00:00+00:00",
                    "initial_backfill_hours": 24,
                    "repositories": [],
                },
            )
            write_json(digest, {"overview": [], "repositories": []})
            run_script(
                "render_digest.py",
                "--commits",
                str(commits),
                "--digest",
                str(digest),
                "--out",
                str(report),
                "--date",
                "2026-08-07",
            )
            original = report.read_text(encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "render_digest.py"),
                    "--commits",
                    str(commits),
                    "--digest",
                    str(digest),
                    "--out",
                    str(report),
                    "--date",
                    "2026-08-08",
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(report.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
