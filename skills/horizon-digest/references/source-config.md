# Source Config

Use a JSON config file with source settings and digest filtering rules. Environment variables in string values may use `${VAR_NAME}` and are expanded by the fetch script.

Starter config:

```json
{
  "version": "1.0",
  "languages": ["zh"],
  "sources": {
    "github": [
      {
        "type": "user_events",
        "username": "karpathy",
        "enabled": true
      }
    ],
    "hackernews": {
      "enabled": true,
      "fetch_top_stories": 30,
      "min_score": 100,
      "top_comments": 5
    },
    "rss": [
      {
        "name": "LWN.net",
        "url": "https://lwn.net/headlines/full_text?key=${LWN_KEY}",
        "enabled": true,
        "category": "linux-kernel"
      },
      {
        "name": "Brendan Gregg",
        "url": "https://www.brendangregg.com/blog/rss.xml",
        "enabled": true,
        "category": "systems"
      }
    ],
    "reddit": {
      "enabled": true,
      "subreddits": [
        {
          "subreddit": "linux",
          "enabled": true,
          "sort": "hot",
          "time_filter": "day",
          "fetch_limit": 15,
          "min_score": 60
        }
      ],
      "fetch_comments": 5
    },
    "ossinsight": {
      "enabled": true,
      "period": "past_24_hours",
      "languages": ["All"],
      "keywords": [],
      "min_stars": 10,
      "max_items": 30
    }
  },
  "filtering": {
    "time_window_hours": 24,
    "ai_score_threshold": 6.0,
    "max_items": 15,
    "category_groups": {},
    "default_group": "other",
    "default_group_limit": null
  },
  "webhook": {
    "enabled": false,
    "url_env": "HIBOARD_WEBHOOK_URL",
    "languages": ["zh"],
    "request_body": {
      "data": {
        "authCode": "${HIBOARD_AUTH_CODE}",
        "msgContent": [
          {
            "msgId": "horizon_#{date}_#{language}_#{timestamp}",
            "scheduleTaskId": "horizon_summary_#{date}_#{language}",
            "scheduleTaskName": "#{message_title}",
            "summary": "#{message_title}",
            "result": "#{result}",
            "content": "#{summary}",
            "source": "horizon",
            "taskFinishTime": "#{timestamp}"
          }
        ]
      }
    },
    "headers": "x-trace-id: horizon_#{date}_#{language}_#{timestamp}",
    "success_body_contains": ["0000000000", "OK"]
  }
}
```

Supported source types in the first version:

- `rss`: RSS or Atom feeds.
- `hackernews`: Hacker News top stories plus top comments.
- `github`: public user events and repository releases.
- `reddit`: public subreddit JSON.
- `ossinsight`: OSS Insight trending repositories.

## Webhook delivery

The `webhook` block is optional. It is disabled unless `webhook.enabled` is `true`.

Supported fields:

- `enabled`: set to `true` to send the rendered summary after `render_summary.py`.
- `url_env`: environment variable containing the webhook URL. Prefer this for secrets.
- `url`: literal URL or a string containing `${VAR_NAME}` environment references. Use this only when storing the URL in config is acceptable.
- `languages`: optional list of digest languages to send.
- `request_body`: optional string, object, or array. Objects and arrays are sent as JSON. Strings that parse as JSON are sent as JSON; other strings are sent as form data.
- `headers`: optional dict or newline-separated `Name: Value` lines.
- `message_title`: optional title template.
- `variables`: optional object of extra template variables.
- `success_body_contains`: optional string or list of strings that must appear in the response body in addition to a 2xx HTTP status.

Template placeholders use `#{name}`. Built-in variables include `date`, `language`, `summary`, `important_items`, `selected_items`, `item_count`, `all_items`, `all_items_count`, `result`, `message_title`, `message_kind`, and `timestamp`.

Optional environment variables:

- `GITHUB_TOKEN`: increases GitHub rate limits.
- Any variable referenced inside RSS URLs, such as `${LWN_KEY}`.
- Any variable referenced by `webhook.url_env`, `webhook.url`, or `webhook.request_body`.

Source failures should be recorded as warnings and should not abort the whole digest unless no items are fetched.
