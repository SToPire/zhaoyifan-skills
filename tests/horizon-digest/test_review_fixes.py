#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "skills" / "horizon-digest"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_sources  # noqa: E402
import render_summary  # noqa: E402
from _common import default_digest_date, load_config, resolve_output_file  # noqa: E402
from merge_url_duplicates import merge_items  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        check=True,
        text=True,
        capture_output=True,
    )


class ReviewFixTests(unittest.TestCase):
    def test_source_config_starter_is_valid_json(self) -> None:
        text = (ROOT / "references" / "source-config.md").read_text(encoding="utf-8")
        start = text.index("```json") + len("```json")
        end = text.index("```", start)

        config = json.loads(text[start:end])

        self.assertIn("output_file", config)
        self.assertIn("sources", config)
        self.assertIn("filtering", config)

    def test_output_file_is_required_and_relative_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            write_json(config, {"output_file": "reports/{run_id}.md"})
            loaded = load_config(config)

            self.assertEqual(
                resolve_output_file(
                    config,
                    loaded,
                    run_id="20260817-190532",
                    date="2026-08-17",
                ),
                (root / "reports" / "20260817-190532.md").resolve(),
            )

            write_json(config, {})
            with self.assertRaisesRegex(ValueError, "output_file"):
                load_config(config)

    def test_output_file_expands_braced_environment_variable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            write_json(config, {"output_file": "${TEST_DIGEST_ROOT}/{run_id}.md"})

            with mock.patch.dict(os.environ, {"TEST_DIGEST_ROOT": str(root / "reports")}):
                loaded = load_config(config)

            self.assertEqual(
                resolve_output_file(config, loaded, run_id="run", date="2026-08-17"),
                (root / "reports" / "run.md").resolve(),
            )

    def test_url_merge_keeps_distinct_queries(self) -> None:
        items = [
            {"id": "a", "url": "https://news.ycombinator.com/item?id=1", "content": "short"},
            {"id": "b", "url": "https://news.ycombinator.com/item?id=2", "content": "longer"},
        ]

        self.assertEqual(len(merge_items(items)), 2)

    def test_default_digest_date_uses_utc_plus_8_boundary(self) -> None:
        utc_boundary = datetime(2026, 7, 2, 18, 4, tzinfo=timezone.utc)

        self.assertEqual(default_digest_date(utc_boundary), "2026-07-03")
        self.assertIs(render_summary.default_digest_date, default_digest_date)

    def test_render_summary_source_line_uses_utc_plus_8(self) -> None:
        item = {
            "source_type": "hackernews",
            "published_at": "2026-07-02T18:04:39+00:00",
            "metadata": {},
        }

        self.assertIn(
            "7月3日 02:04",
            render_summary.source_line(item, "zh", render_summary.LABELS["zh"]),
        )

    def test_reddit_skips_malformed_post_without_aborting_source(self) -> None:
        payload = {
            "data": {
                "children": [
                    {"data": {"id": "bad", "score": "not-a-number", "created_utc": 1}},
                    {
                        "data": {
                            "id": "good",
                            "score": 3,
                            "created_utc": datetime.now(timezone.utc).timestamp(),
                            "permalink": "/r/x/comments/good/post/",
                            "title": "Good post",
                            "url": "https://example.com/good",
                        }
                    },
                ]
            }
        }
        original_get_json = fetch_sources.get_json
        original_comments = fetch_sources.fetch_reddit_comments
        fetch_sources.get_json = lambda *args, **kwargs: payload
        fetch_sources.fetch_reddit_comments = lambda *args, **kwargs: []
        warnings: list[str] = []
        try:
            items = fetch_sources.fetch_reddit(
                {
                    "sources": {
                        "reddit": {
                            "enabled": True,
                            "subreddits": [{"subreddit": "x", "min_score": 1}],
                            "fetch_comments": 0,
                        }
                    }
                },
                datetime.now(timezone.utc) - timedelta(days=1),
                warnings,
            )
        finally:
            fetch_sources.get_json = original_get_json
            fetch_sources.fetch_reddit_comments = original_comments

        self.assertEqual([item["id"] for item in items], ["reddit:post:good"])
        self.assertTrue(any("skipped malformed item bad" in warning for warning in warnings))

    def test_group_without_limit_uses_default_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            items = root / "items.json"
            out = root / "out.json"
            write_json(
                config,
                {
                    "output_file": str(root / "summary.md"),
                    "filtering": {
                        "ai_score_threshold": 1,
                        "default_group_limit": 1,
                        "category_groups": {"infra": {"categories": ["infra"]}},
                    }
                },
            )
            write_json(
                items,
                [
                    {"id": "a", "ai_score": 9, "metadata": {"category": "infra"}},
                    {"id": "b", "ai_score": 8, "metadata": {"category": "infra"}},
                ],
            )

            run_script("filter_items.py", "--config", str(config), "--items", str(items), "--out", str(out))

            self.assertEqual([item["id"] for item in json.loads(out.read_text(encoding="utf-8"))], ["a"])

    def test_validate_enrichment_without_language_accepts_english_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.json"
            enrichment = root / "enrichment.json"
            out = root / "out.json"
            write_json(items, [{"id": "x", "metadata": {}}])
            write_json(
                enrichment,
                [{"id": "x", "title_en": "Title", "detailed_summary_en": "Summary"}],
            )

            run_script(
                "validate_enriched_items.py",
                "--items",
                str(items),
                "--enrichment",
                str(enrichment),
                "--out",
                str(out),
            )

            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))[0]["metadata"]["title_en"], "Title")

    def test_render_summary_drops_unsafe_links_and_escapes_html_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            items = root / "items.json"
            out = root / "summary.md"
            write_json(config, {"output_file": str(out), "languages": ["en"]})
            write_json(
                items,
                [
                    {
                        "id": "x",
                        "source_type": "rss",
                        "title": "Unsafe",
                        "url": "javascript:alert(1)",
                        "published_at": "2026-06-29T00:00:00+00:00",
                        "ai_score": 7,
                        "ai_summary": "Summary",
                        "metadata": {
                            "sources": [
                                {"title": "<Ref>", "url": "http://example.com/a)b"},
                                {"title": "Bad", "url": "javascript:alert(2)"},
                            ]
                        },
                    }
                ],
            )

            run_script(
                "render_summary.py",
                "--config",
                str(config),
                "--items",
                str(items),
                "--language",
                "en",
                "--date",
                "2026-06-29",
                "--run-id",
                "test-run",
            )

            rendered = out.read_text(encoding="utf-8")
            self.assertNotIn("javascript:", rendered)
            self.assertNotIn("<a id=", rendered)
            self.assertNotIn("#item-1", rendered)
            self.assertIn("1. Unsafe ⭐ 7/10", rendered)
            self.assertIn("## Unsafe ⭐ 7/10", rendered)
            self.assertIn('<a href="http://example.com/a)b">&lt;Ref&gt;</a>', rendered)

    def test_render_summary_refuses_to_overwrite_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            items = root / "items.json"
            output = root / "summary.md"
            write_json(config, {"output_file": str(output), "languages": ["en"]})
            write_json(items, [])
            output.write_text("existing report\n", encoding="utf-8")

            with self.assertRaises(subprocess.CalledProcessError):
                run_script(
                    "render_summary.py",
                    "--config",
                    str(config),
                    "--items",
                    str(items),
                    "--language",
                    "en",
                    "--date",
                    "2026-08-17",
                    "--run-id",
                    "test-run",
                )

            self.assertEqual(output.read_text(encoding="utf-8"), "existing report\n")

if __name__ == "__main__":
    unittest.main()
