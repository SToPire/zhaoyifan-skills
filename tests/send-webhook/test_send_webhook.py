#!/usr/bin/env python3
import hashlib
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


class SendWebhookTests(unittest.TestCase):
    def test_url_redaction_hides_userinfo_and_sensitive_query(self) -> None:
        redacted = send_webhook.redact_url(
            "https://alice:password@example.com/hook?token=secret&id=visible"
        )

        self.assertEqual(
            redacted,
            "https://***:***@example.com/hook?token=%2A%2A%2A&id=visible",
        )

    def test_invalid_url_error_is_redacted(self) -> None:
        url = "ftp://alice:password@example.com/hook?token=secret"

        with self.assertRaises(ValueError) as raised:
            send_webhook.resolve_url({"url": url}, {})

        message = str(raised.exception)
        self.assertNotIn("alice", message)
        self.assertNotIn("password", message)
        self.assertNotIn("secret", message)
        self.assertIn("ftp://***:***@example.com/hook?token=%2A%2A%2A", message)

    def test_reference_config_is_generic_valid_json(self) -> None:
        text = (ROOT / "references" / "config.md").read_text(encoding="utf-8")
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        config = json.loads(text[start:end])

        self.assertTrue(config["enabled"])
        self.assertEqual(config["name"], "example")
        self.assertEqual(config["url_env"], "WEBHOOK_URL")
        self.assertNotIn("languages", config)

    def test_repository_hiboard_config_has_no_digest_fields(self) -> None:
        path = ROOT / "config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(config)

        self.assertEqual(config["name"], "hiboard")
        self.assertNotIn("languages", config)
        for field in ("message_id", "message_kind", "message_title", "#{date}", "#{language}"):
            self.assertNotIn(field, serialized)

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
                variables = root / "variables.json"
                content = root / "report.md"
                out = root / "result.json"
                write_json(
                    config,
                    {
                        "name": "test-target",
                        "enabled": True,
                        "url_env": "TEST_SEND_WEBHOOK_URL",
                        "request_body": {
                            "authCode": "${TEST_SEND_WEBHOOK_AUTH_CODE}",
                            "deliveryId": "#{content_sha256}",
                            "title": "#{content_title}",
                            "content": "#{content}",
                            "facts": "#{facts}",
                        },
                        "headers": {"x-trace-id": "#{content_sha256}"},
                        "success_body_contains": ["0000000000", "OK"],
                    },
                )
                write_json(variables, {"facts": {"items": 2}})
                markdown = "# Horizon\n\n内容"
                content.write_text(markdown, encoding="utf-8")
                expected_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                env = os.environ.copy()
                env["TEST_SEND_WEBHOOK_URL"] = (
                    f"http://127.0.0.1:{server.server_port}/hook?id=#{{content_sha256}}&token=secret"
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
                        "--content",
                        str(content),
                        "--variables",
                        str(variables),
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
                self.assertEqual(result["target"], "test-target")
                self.assertEqual(result["content_sha256"], expected_hash)
                self.assertGreater(result["body_size_bytes"], 0)
                self.assertEqual(len(result["body_sha256"]), 64)
                self.assertEqual(
                    result["url"],
                    f"http://127.0.0.1:{server.server_port}/hook?id={expected_hash}&token=%2A%2A%2A",
                )
                self.assertEqual(requests[0]["content_type"], "application/json")
                self.assertEqual(requests[0]["trace"], expected_hash)
                self.assertEqual(body["authCode"], "auth-value")
                self.assertEqual(body["deliveryId"], expected_hash)
                self.assertEqual(body["title"], "Horizon")
                self.assertEqual(body["content"], markdown)
                self.assertEqual(body["facts"], {"items": 2})
        finally:
            server.shutdown()
            server.server_close()

    def test_enabled_missing_url_environment_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            content = root / "report.md"
            out = root / "result.json"
            write_json(config, {"enabled": True, "url_env": "MISSING_SEND_WEBHOOK_URL"})
            content.write_text("content", encoding="utf-8")
            env = os.environ.copy()
            env.pop("MISSING_SEND_WEBHOOK_URL", None)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config),
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

    def test_delivery_variables_must_be_an_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            variables = Path(tmp) / "variables.json"
            write_json(variables, ["not", "an", "object"])

            with self.assertRaisesRegex(ValueError, "JSON object"):
                send_webhook.load_delivery_variables(variables)

    def test_delivery_variables_cannot_override_builtins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            variables = Path(tmp) / "variables.json"
            write_json(variables, {"content": "replacement"})

            with self.assertRaisesRegex(ValueError, "cannot override built-ins"):
                send_webhook.load_delivery_variables(variables)

    def test_disabled_delivery_does_not_require_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            content = root / "report.md"
            out = root / "result.json"
            write_json(
                config,
                {
                    "name": "disabled-target",
                    "enabled": False,
                    "url_env": "MISSING_SEND_WEBHOOK_URL",
                    "request_body": {"secret": "${MISSING_SEND_WEBHOOK_SECRET}"},
                },
            )
            content.write_text("content", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config),
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
            self.assertEqual(result["target"], "disabled-target")

    def test_dry_run_uses_content_metadata_without_sending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            content = root / "report.md"
            out = root / "result.json"
            write_json(
                config,
                {
                    "name": "preview",
                    "enabled": True,
                    "url": "https://example.com/hook?secret=value",
                    "request_body": {
                        "title": "#{content_title}",
                        "content": "#{content}",
                    },
                },
            )
            content.write_text("# Preview\n\ncontent", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config),
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
            self.assertEqual(result["target"], "preview")
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
        delivery_variables = {"facts": {"repositories": 3, "commits": 18}}
        variables = send_webhook.build_variables(
            config,
            delivery_variables,
            "content",
            "report.md",
        )

        _, body, _, _ = send_webhook.build_request(config, variables)

        assert body is not None
        self.assertEqual(
            json.loads(body.decode("utf-8"))["facts"],
            {"repositories": 3, "commits": 18},
        )

    def test_builtin_content_metadata_is_derived_from_markdown(self) -> None:
        variables = send_webhook.build_variables(
            {"name": "target"},
            {},
            "# Daily Report\n\nBody",
            "/tmp/daily.md",
        )

        self.assertEqual(variables["content_name"], "daily.md")
        self.assertEqual(variables["content_stem"], "daily")
        self.assertEqual(variables["content_title"], "Daily Report")
        self.assertEqual(variables["target_name"], "target")
        self.assertEqual(len(variables["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
