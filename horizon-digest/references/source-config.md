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
  }
}
```

Supported source types in the first version:

- `rss`: RSS or Atom feeds.
- `hackernews`: Hacker News top stories plus top comments.
- `github`: public user events and repository releases.
- `reddit`: public subreddit JSON.
- `ossinsight`: OSS Insight trending repositories.

Optional environment variables:

- `GITHUB_TOKEN`: increases GitHub rate limits.
- Any variable referenced inside RSS URLs, such as `${LWN_KEY}`.

Source failures should be recorded as warnings and should not abort the whole digest unless no items are fetched.
