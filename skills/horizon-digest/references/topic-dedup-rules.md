# Topic Dedup Rules

Group items only when they cover the same real-world event, release, incident, paper, benchmark, or announcement.

Keep items separate when they are merely about the same project, company, technology, or theme but describe different facts.

The first item in each group is the primary item to keep. Choose the highest-scored item as primary; if scores tie, choose the item with richer content or stronger source credibility.

Output `topic_duplicates.json`:

```json
{
  "duplicates": [
    ["primary-item-id", "duplicate-item-id"]
  ]
}
```

An index-based form is also accepted by the script:

```json
{
  "duplicates": [[0, 3, 9]]
}
```

When there are no duplicates, write:

```json
{"duplicates": []}
```

Err on the side of keeping items separate.
