# Summary Format

The renderer creates Markdown with:

1. H1 heading: `Horizon 每日速递 - YYYY-MM-DD` or `Horizon Daily - YYYY-MM-DD`.
2. A blockquote showing total fetched count and selected item count.
3. A table of contents with item links and scores.
4. One section per item:
   - linked title and score,
   - detailed summary,
   - source line,
   - optional background,
   - optional references,
   - optional community discussion,
   - tags.

The renderer uses `metadata.title_<language>`, `metadata.detailed_summary_<language>`, `metadata.background_<language>`, and `metadata.community_discussion_<language>` when available. It falls back to `ai_summary` and original title.
