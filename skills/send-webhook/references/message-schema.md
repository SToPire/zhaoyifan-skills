# Message Schema

Write strict UTF-8 JSON without Markdown fences:

```json
{
  "id": "horizon-digest:20260811-103248:zh",
  "kind": "horizon-digest",
  "title": "Horizon 2026-08-11 日报",
  "date": "2026-08-11",
  "language": "zh",
  "variables": {
    "item_count": 12,
    "all_items_count": 41
  }
}
```

## Fields

- `id`: required stable message ID. Reuse it when retrying the same content.
- `kind`: required producer or report type.
- `title`: required human-readable title.
- `date`: required `YYYY-MM-DD` digest date.
- `language`: required language identifier such as `zh` or `en`.
- `variables`: optional object of producer-specific scalar, list, or object values.

Message variables cannot replace reserved built-ins.

## Built-in Template Variables

- `message_id`: `id` from the message.
- `message_kind`: `kind` from the message.
- `message_title`: `title` from the message.
- `date`: digest date.
- `language`: digest language.
- `content`: complete content file text.
- `summary`: compatibility alias for `content`.
- `result`: always `success` for a delivery request.
- `timestamp`: current Unix timestamp in UTC.

Every entry in message `variables` is also available as `#{name}`. Keep provider-specific fields in the message or config variables rather than adding producer-specific behavior to the sender.
