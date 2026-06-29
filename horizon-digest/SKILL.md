---
name: horizon-digest
description: Generate a technical information digest from configured web sources using deterministic local scripts for fetching, filtering, validation, and rendering, while the active agent performs scoring, topic deduplication, and enrichment from staged JSON artifacts. Use when asked to create a daily/weekly technical digest, rank fetched source items, produce scored_items/enriched_items artifacts, or render a Chinese or English Markdown digest from RSS, Hacker News, GitHub, Reddit, or OSS Insight sources.
---

# Horizon Digest

## Overview

Build a digest as a staged artifact workflow. Scripts do deterministic work: fetch, normalize, merge URLs, pack batches, validate JSON, filter, and render Markdown. The active agent performs the judgment steps by reading staged JSON and writing strict JSON artifacts.

Keep the workflow portable across coding agents. Do not assume one agent product, model API, connector, or host app.

## Workflow

1. Create a run directory, usually `work/horizon-digest/<YYYYMMDD-HHMMSS>/`.
2. Choose or create a config JSON. If the user does not provide one, use `references/source-config.md` as the template.
3. Fetch source items:

```bash
python <skill>/scripts/fetch_sources.py --config <config.json> --out <run>/raw_items.json --meta-out <run>/meta.json
```

4. Merge exact URL duplicates:

```bash
python <skill>/scripts/merge_url_duplicates.py --items <run>/raw_items.json --out <run>/merged_items.json
```

5. Pack scoring batches:

```bash
python <skill>/scripts/pack_scoring_batches.py --items <run>/merged_items.json --out-dir <run>/scoring-batches --batch-size 10
```

6. Read `references/scoring-rubric.md` and the generated scoring batches. Write one `scores.json` containing `id`, `ai_score`, `ai_reason`, `ai_summary`, and `ai_tags` for every item.
7. Validate and merge scores:

```bash
python <skill>/scripts/validate_scored_items.py --items <run>/merged_items.json --scores <run>/scores.json --out <run>/scored_items.json
```

8. Read `references/topic-dedup-rules.md`, inspect `scored_items.json`, and write `topic_duplicates.json` only when duplicate groups exist.
9. Apply topic deduplication:

```bash
python <skill>/scripts/apply_topic_dedup.py --items <run>/scored_items.json --duplicates <run>/topic_duplicates.json --out <run>/deduped_items.json
```

10. Apply threshold, category quotas, and max item cap:

```bash
python <skill>/scripts/filter_items.py --config <config.json> --items <run>/deduped_items.json --out <run>/filtered_items.json
```

11. Pack enrichment batches:

```bash
python <skill>/scripts/pack_enrichment_batches.py --items <run>/filtered_items.json --out-dir <run>/enrichment-batches --batch-size 5
```

12. Read `references/enrichment-style.md` and write `enrichment.json` for every filtered item.
13. Validate and merge enrichment:

```bash
python <skill>/scripts/validate_enriched_items.py --items <run>/filtered_items.json --enrichment <run>/enrichment.json --out <run>/enriched_items.json --language zh
```

14. Render Markdown:

```bash
python <skill>/scripts/render_summary.py --config <config.json> --items <run>/enriched_items.json --meta <run>/meta.json --out <run>/summary-zh.md --language zh
```

15. Report artifact paths, counts, selected items, and any source warnings.

## Judgment Artifacts

Use strict JSON for agent-written files. Do not include Markdown fences in JSON artifacts.

- `scores.json`: see `references/schemas.md`.
- `topic_duplicates.json`: see `references/topic-dedup-rules.md`.
- `enrichment.json`: see `references/enrichment-style.md`.

After writing each agent-generated JSON file, run the matching validator before continuing.

## Resource Guide

- `references/source-config.md`: config shape and a starter config.
- `references/schemas.md`: item and artifact schemas.
- `references/scoring-rubric.md`: importance scoring rules.
- `references/topic-dedup-rules.md`: semantic duplicate grouping rules.
- `references/enrichment-style.md`: bilingual enrichment fields and writing style.
- `references/summary-format.md`: rendered Markdown structure.
