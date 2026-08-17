# Webhook Config

Use a dedicated JSON object for a delivery target:

```json
{
  "enabled": true,
  "url_env": "HIBOARD_WEBHOOK_URL",
  "languages": ["zh"],
  "request_body": {
    "data": {
      "authCode": "${HIBOARD_AUTH_CODE}",
      "msgContent": [
        {
          "msgId": "#{message_id}",
          "scheduleTaskId": "#{message_kind}_#{date}_#{language}",
          "scheduleTaskName": "#{message_title}",
          "summary": "#{message_title}",
          "result": "#{result}",
          "content": "#{content}",
          "source": "#{message_kind}",
          "taskFinishTime": "#{timestamp}"
        }
      ]
    }
  },
  "headers": "x-trace-id: #{message_id}",
  "success_body_contains": ["0000000000", "OK"]
}
```

The sender also accepts this object under a top-level `webhook` key so an existing combined configuration can be migrated without changing its shape.

## Fields

- `enabled`: enable delivery. Missing or `false` means skip successfully.
- `url_env`: environment variable containing the webhook URL. Prefer this for secrets.
- `url`: literal HTTP(S) URL or a string containing `${VAR_NAME}` references.
- `languages`: optional allowlist matched against the message language.
- `method`: optional `GET` or `POST`. By default, use `POST` when a request body exists and `GET` otherwise.
- `request_body`: optional string, object, or array. Send objects, arrays, and JSON strings as JSON; send other strings as form data.
- `headers`: optional object or newline-separated `Name: Value` lines.
- `variables`: optional object containing target-specific template variables. It cannot override built-in variables.
- `success_body_contains`: optional string or list of strings that must all appear in the response body in addition to a 2xx status.
- `timeout_seconds`: optional request timeout from 1 to 300 seconds; default 30.

Expand `${VAR_NAME}` from the environment before applying `#{name}` message templates. Fail enabled delivery if an environment reference, URL, or template variable is unresolved.

Do not store credentials in message JSON. Keep them in environment variables referenced only by the trusted config.

The sender honors standard `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` behavior for remote destinations. It always bypasses environment proxies for `localhost` and loopback IP addresses so local validation cannot be redirected through an ambient proxy.
