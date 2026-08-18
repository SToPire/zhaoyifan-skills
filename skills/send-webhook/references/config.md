# Webhook Config

Use one JSON object per delivery target. The request body is intentionally target-specific while the surrounding configuration shape stays the same:

```json
{
  "version": "1.0",
  "name": "example",
  "enabled": true,
  "url_env": "WEBHOOK_URL",
  "method": "POST",
  "headers": {
    "x-delivery-id": "#{content_sha256}"
  },
  "request_body": {
    "title": "#{content_title}",
    "content": "#{content}"
  },
  "timeout_seconds": 30
}
```

## Fields

- `enabled`: enable delivery. Missing or `false` means skip successfully.
- `name`: optional target name included in result records and available as `#{target_name}`.
- `url_env`: environment variable containing the webhook URL. Prefer this for secrets.
- `url`: literal HTTP(S) URL or a string containing `${VAR_NAME}` references.
- `method`: optional `GET` or `POST`. By default, use `POST` when a request body exists and `GET` otherwise.
- `request_body`: optional string, object, or array. Send objects, arrays, and JSON strings as JSON; send other strings as form data.
- `headers`: optional object or newline-separated `Name: Value` lines.
- `variables`: optional object containing target-specific template variables. It cannot override built-in or delivery variables.
- `success_body_contains`: optional string or list of strings that must all appear in the response body in addition to a 2xx status.
- `timeout_seconds`: optional request timeout from 1 to 300 seconds; default 30.

Expand `${VAR_NAME}` from the environment before applying `#{name}` delivery templates. Fail enabled delivery if an environment reference, URL, or template variable is unresolved.

Do not store credentials in Markdown or delivery-variable JSON. Keep them in environment variables referenced only by the trusted config.

## Built-in Template Variables

- `content`: complete Markdown text.
- `content_path`: content path passed to the sender.
- `content_name`: filename including its extension.
- `content_stem`: filename without its extension.
- `content_title`: first Markdown heading, falling back to `content_stem`.
- `content_sha256`: SHA-256 of the UTF-8 Markdown content.
- `content_size_bytes`: UTF-8 content size.
- `target_name`: config `name`, or `webhook` when omitted.
- `timestamp`: current Unix timestamp in UTC.

Pass optional per-delivery values in a separate JSON object with `--variables`:

```json
{
  "channel": "engineering",
  "labels": ["daily", "systems"]
}
```

Each entry becomes a `#{name}` template variable. An exact placeholder preserves structured JSON values; for example, `"labels": "#{labels}"` renders as an array rather than a string.

The sender honors standard `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` behavior for remote destinations. It always bypasses environment proxies for `localhost` and loopback IP addresses so local validation cannot be redirected through an ambient proxy.
