# Enrichment Style

Enrich only filtered high-value items.

For each item, write a concise structured explanation. Base the text on the item title, source content, comments, metadata, and any references you actually inspect.

## Chinese Fields

- `title_zh`: short Chinese headline. Keep proper nouns such as Linux, Rust, CUDA, GPT, Kubernetes, or repo names in English.
- `detailed_summary_zh`: 2-4 Chinese sentences combining what changed, why it matters, and key details. Be concrete.
- `background_zh`: 1-3 Chinese sentences explaining necessary technical context. Empty string is allowed if no background is needed.
- `community_discussion_zh`: 1-2 Chinese sentences summarizing comments or community signal. Empty string is allowed if no discussion exists.

## Optional English Fields

If the requested language includes English, also write:

- `title_en`
- `detailed_summary_en`
- `background_en`
- `community_discussion_en`

## Sources

If you inspect additional URLs, include them in `sources`. Do not invent citations. It is fine to leave `sources` empty when the item itself is sufficient.

Follow `references/schemas.md` for the final JSON shape.
