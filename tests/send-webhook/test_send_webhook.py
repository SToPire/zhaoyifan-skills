#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "skills" / "send-webhook"
SCRIPT = ROOT / "scripts" / "send_webhook.py"
sys.path.insert(0, str(SCRIPT.parent))

import send_webhook  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def base_message() -> dict[str, object]:
    return {
        "id": "horizon-digest:20260629:zh",
        "kind": "horizon-digest",
        "title": "Horizon 2026-06-29 日报",
        "date": "2026-06-29",
        "language": "zh",
        "variables": {"item_count": 2},
    }


class SendWebhookTests(unittest.TestCase):
    def test_reference_config_is_valid_json(self) -> None:
        text = (ROOT / "references" / "config.md").read_text(encoding="utf-8")
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        config = json.loads(text[start:end])
        self.assertTrue(config["enabled"])
        self.assertEqual(config["url_env"], "HIBOARD_WEBHOOK_URL")

    def test_sends_generic_json_body_and_redacts_secrets(self) -> None:
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
                message = root / "message.json"
                content = root / "report.md"
                out = root / "result.json"
                write_json(
                    config,
                    {
                        "enabled": True,
                        "url_env": "TEST_SEND_WEBHOOK_URL",
                        "languages": ["zh"],
                        "request_body": {
                            "authCode": "${TEST_SEND_WEBHOOK_AUTH_CODE}",
                            "msgId": "#{message_id}",
                            "title": "#{message_title}",
                            "content": "#{content}",
                            "count": "#{item_count}",
                        },
                        "headers": "x-trace-id: #{message_id}",
                        "success_body_contains": ["0000000000", "OK"],
                    },
                )
                write_json(message, base_message())
                content.write_text("# Horizon\n\n内容", encoding="utf-8")
                env = os.environ.copy()
                env["TEST_SEND_WEBHOOK_URL"] = (
                    f"http://127.0.0.1:{server.server_port}/hook?date=#{{date}}&token=secret"
                )
                env["TEST_SEND_WEBHOOK_AUTH_CODE"] = "auth-value"
                env["HTTP_PROXY"] = "http://127.0.0.1:9"
                env["HTTPS_PROXY"] = "http://127.0.0.1:9"
                env["NO_PROXY"] = ""
                env["no_proxy"] = ""

                subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--config",
                        str(config),
                        "--message",
                        str(message),
                        "--content",
                        str(content),
                        "--out",
                        str(out),
                    ],
                    check=True,
                    text=True,
                    capture_output=True,
                    env=env,
                )

                result = json.loads(out.read_text(encoding="utf-8"))
                body = json.loads(requests[0]["body"])
                self.assertTrue(result["success"])
                self.assertEqual(result["message_id"], "horizon-digest:20260629:zh")
                self.assertGreater(result["body_size_bytes"], 0)
                self.assertEqual(len(result["body_sha256"]), 64)
                self.assertEqual(
                    result["url"],
                    f"http://127.0.0.1:{server.server_port}/hook?date=2026-06-29&token=%2A%2A%2A",
                )
                self.assertEqual(requests[0]["content_type"], "application/json")
                self.assertEqual(requests[0]["trace"], "horizon-digest:20260629:zh")
                self.assertEqual(body["authCode"], "auth-value")
                self.assertEqual(body["msgId"], "horizon-digest:20260629:zh")
                self.assertEqual(body["title"], "Horizon 2026-06-29 日报")
                self.assertEqual(body["content"], "# Horizon\n\n内容")
                self.assertEqual(body["count"], 2)
        finally:
            server.shutdown()
            server.server_close()

    def test_enabled_missing_url_environment_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            message = root / "message.json"
            content = root / "report.md"
            out = root / "result.json"
            write_json(config, {"enabled": True, "url_env": "MISSING_SEND_WEBHOOK_URL"})
            write_json(message, base_message())
            content.write_text("content", encoding="utf-8")
            env = os.environ.copy()
            env.pop("MISSING_SEND_WEBHOOK_URL", None)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config),
                    "--message",
                    str(message),
                    "--content",
                    str(content),
                    "--out",
                    str(out),
                ],
                check=False,
                text=True,
                capture_output=True,
                env=env,
            )

            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 1)
            self.assertFalse(result["success"])
            self.assertFalse(result["skipped"])
            self.assertIn("is not set", result["error"])

    def test_message_date_requires_zero_padding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            message_path = Path(tmp) / "message.json"
            message = base_message()
            message["date"] = "2026-6-1"
            write_json(message_path, message)

            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                send_webhook.validate_message(message_path)

    def test_disabled_delivery_does_not_require_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            message = root / "message.json"
            content = root / "report.md"
            out = root / "result.json"
            write_json(
                config,
                {
                    "enabled": False,
                    "url_env": "MISSING_SEND_WEBHOOK_URL",
                    "request_body": {"secret": "${MISSING_SEND_WEBHOOK_SECRET}"},
                },
            )
            write_json(message, base_message())
            content.write_text("content", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config),
                    "--message",
                    str(message),
                    "--content",
                    str(content),
                    "--out",
                    str(out),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(result["skipped"])
            self.assertFalse(result["enabled"])

    def test_dry_run_accepts_legacy_nested_webhook_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            message = root / "message.json"
            content = root / "report.md"
            out = root / "result.json"
            write_json(
                config,
                {
                    "webhook": {
                        "enabled": True,
                        "url": "https://example.com/hook?secret=value",
                        "request_body": {"content": "#{summary}"},
                    }
                },
            )
            write_json(message, base_message())
            content.write_text("content", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config),
                    "--message",
                    str(message),
                    "--content",
                    str(content),
                    "--out",
                    str(out),
                    "--dry-run",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["method"], "POST")
            self.assertEqual(result["url"], "https://example.com/hook?secret=%2A%2A%2A")
            self.assertGreater(result["body_size_bytes"], 0)
            self.assertEqual(len(result["body_sha256"]), 64)

    def test_exact_placeholder_preserves_structured_variable(self) -> None:
        config = {
            "enabled": True,
            "url": "https://example.com/hook",
            "request_body": {"facts": "#{facts}"},
        }
        message = base_message()
        message["variables"] = {"facts": {"repositories": 3, "commits": 18}}
        variables = send_webhook.build_variables(config, message, "content")

        _, body, _, _ = send_webhook.build_request(config, variables)

        assert body is not None
        self.assertEqual(
            json.loads(body.decode("utf-8"))["facts"],
            {"repositories": 3, "commits": 18},
        )


if __name__ == "__main__":
    unittest.main()
