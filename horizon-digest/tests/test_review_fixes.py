#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_sources  # noqa: E402
import render_summary  # noqa: E402
import send_webhook  # noqa: E402
from _common import default_digest_date  # noqa: E402
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

        self.assertIn("sources", config)
        self.assertIn("filtering", config)
        self.assertIn("webhook", config)
        self.assertFalse(config["webhook"]["enabled"])

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
        self.assertIs(send_webhook.default_digest_date, default_digest_date)

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
            write_json(config, {"languages": ["en"]})
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
                "--out",
                str(out),
                "--language",
                "en",
                "--date",
                "2026-06-29",
            )

            rendered = out.read_text(encoding="utf-8")
            self.assertNotIn("javascript:", rendered)
            self.assertNotIn("<a id=", rendered)
            self.assertNotIn("#item-1", rendered)
            self.assertIn("1. Unsafe ⭐ 7/10", rendered)
            self.assertIn("## Unsafe ⭐ 7/10", rendered)
            self.assertIn('<a href="http://example.com/a)b">&lt;Ref&gt;</a>', rendered)

    def test_send_webhook_renders_horizon_style_json_body(self) -> None:
        requests: list[dict[str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                requests.append(
                    {
                        "path": self.path,
                        "trace": self.headers.get("x-trace-id", ""),
                        "content_type": self.headers.get("Content-Type", ""),
                        "body": self.rfile.read(length).decode("utf-8"),
                    }
                )
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"code":"0000000000","desc":"OK"}')

            def log_message(self, format: str, *args: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config = root / "config.json"
                summary = root / "summary.md"
                items = root / "items.json"
                meta = root / "meta.json"
                out = root / "webhook_result.json"
                url = f"http://127.0.0.1:{server.server_port}/hook?date=#{{date}}&token=secret"
                write_json(
                    config,
                    {
                        "languages": ["zh"],
                        "webhook": {
                            "enabled": True,
                            "url_env": "TEST_HORIZON_DIGEST_WEBHOOK_URL",
                            "languages": ["zh"],
                            "request_body": {
                                "data": {
                                    "authCode": "${TEST_HORIZON_DIGEST_AUTH_CODE}",
                                    "msgContent": [
                                        {
                                            "msgId": "horizon_#{date}_#{language}_#{timestamp}",
                                            "scheduleTaskName": "#{message_title}",
                                            "content": "#{summary}",
                                            "count": "#{item_count}",
                                        }
                                    ],
                                }
                            },
                            "headers": "x-trace-id: horizon_#{date}_#{language}_#{timestamp}",
                            "success_body_contains": ["0000000000", "OK"],
                        },
                    },
                )
                summary.write_text("# Horizon 每日速递\n\n内容", encoding="utf-8")
                write_json(items, [{"id": "a"}, {"id": "b"}])
                write_json(meta, {"raw_count": 9})
                env = os.environ.copy()
                env["TEST_HORIZON_DIGEST_WEBHOOK_URL"] = url
                env["TEST_HORIZON_DIGEST_AUTH_CODE"] = "auth-value"

                subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS / "send_webhook.py"),
                        "--config",
                        str(config),
                        "--summary",
                        str(summary),
                        "--items",
                        str(items),
                        "--meta",
                        str(meta),
                        "--out",
                        str(out),
                        "--language",
                        "zh",
                        "--date",
                        "2026-06-29",
                    ],
                    check=True,
                    text=True,
                    capture_output=True,
                    env=env,
                )

                result = json.loads(out.read_text(encoding="utf-8"))
                body = json.loads(requests[0]["body"])
                message = body["data"]["msgContent"][0]
                self.assertTrue(result["success"])
                self.assertEqual(result["status_code"], 200)
                self.assertEqual(
                    result["url"],
                    f"http://127.0.0.1:{server.server_port}/hook?date=2026-06-29&token=%2A%2A%2A",
                )
                self.assertIn("date=2026-06-29", requests[0]["path"])
                self.assertEqual(requests[0]["content_type"], "application/json")
                self.assertTrue(requests[0]["trace"].startswith("horizon_2026-06-29_"))
                self.assertEqual(body["data"]["authCode"], "auth-value")
                self.assertEqual(message["scheduleTaskName"], "Horizon 2026-06-29 日报")
                self.assertEqual(message["content"], "# Horizon 每日速递\n\n内容")
                self.assertEqual(message["count"], "2")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
