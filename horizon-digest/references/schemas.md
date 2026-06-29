# Schemas

## Content Item

Scripts exchange items as JSON arrays. Each item has this shape:

```json
{
  "id": "source:kind:native_id",
  "source_type": "rss",
  "title": "Title",
  "url": "https://example.com/item",
  "content": "Optional content or comments",
  "author": "author-or-source",
  "published_at": "2026-06-27T00:00:00+00:00",
  "fetched_at": "2026-06-27T01:00:00+00:00",
  "metadata": {},
  "ai_score": null,
  "ai_reason": null,
  "ai_summary": null,
  "ai_tags": []
}
```

`published_at` and `fetched_at` must be ISO-8601 strings. `metadata` may contain source-specific fields such as `score`, `descendants`, `subreddit`, `feed_name`, `repo`, `discussion_url`, `category`, or `stars_gained`.

## scores.json

Write either a JSON array or an object with an `items` array:

```json
[
  {
    "id": "rss:example:abc123",
    "ai_score": 7.5,
    "ai_reason": "Brief reason for the score.",
    "ai_summary": "One-sentence summary.",
    "ai_tags": ["systems", "linux", "performance"]
  }
]
```

Rules:

- Include exactly one score object for every input item.
- `ai_score` must be a number from 0 to 10.
- `ai_reason` must explain the score in one short sentence.
- `ai_summary` must be one sentence.
- `ai_tags` must contain 2-6 concise lowercase topic tags when possible.

## enrichment.json

Write either a JSON array or an object with an `items` array:

```json
[
  {
    "id": "rss:example:abc123",
    "title_zh": "中文标题",
    "detailed_summary_zh": "发生了什么、为什么重要、关键细节。",
    "background_zh": "必要背景。",
    "community_discussion_zh": "社区讨论摘要，若无则为空字符串。",
    "title_en": "English title",
    "detailed_summary_en": "What happened, why it matters, and key details.",
    "background_en": "Necessary background.",
    "community_discussion_en": "Discussion summary, or empty string.",
    "sources": [
      {
        "title": "Reference title",
        "url": "https://example.com/reference"
      }
    ]
  }
]
```

For Chinese digests, `_zh` fields are required. `_en` fields are optional but useful for future bilingual output. `sources` is optional and should only include URLs that were actually inspected.

## webhook result

When webhook delivery is enabled, write the script result to `webhook_result.json`:

```json
{
  "enabled": true,
  "skipped": false,
  "dry_run": false,
  "method": "POST",
  "url": "https://example.com/webhook?token=***",
  "headers": {
    "Content-Type": "application/json",
    "User-Agent": "horizon-digest-webhook/0.1"
  },
  "success": true,
  "status_code": 200,
  "body_contains_passed": true,
  "response_body_preview": "{\"code\":\"0000000000\",\"desc\":\"OK\"}"
}
```

If the webhook is disabled, language-filtered, or missing its URL environment variable, the result uses `"skipped": true` and exits successfully. HTTP/network failures or configured response-body checks that do not pass exit non-zero after writing the result.
