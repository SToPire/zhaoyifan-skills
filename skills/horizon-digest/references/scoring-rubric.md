# Scoring Rubric

Score each item from 0 to 10 for a technical reader interested in software engineering, systems, AI/ML, developer tools, open source, infrastructure, and adjacent research.

## Scale

| Score | Tier | Meaning |
| --- | --- | --- |
| 9-10 | Groundbreaking | Major breakthrough, paradigm shift, major release, important research result, or industry-changing event. |
| 7-8 | High value | Important technical development, deep technical analysis, novel approach, useful tool, or strong community signal. |
| 5-6 | Interesting | Useful but incremental update, tutorial, moderate community interest, or niche relevance. |
| 3-4 | Low priority | Minor update, generic commentary, common knowledge, thin content, or promotional material. |
| 0-2 | Noise | Spam, off-topic, trivial, duplicate, or low-quality content. |

## Factors

Consider:

- Technical depth and novelty.
- Potential impact on practitioners or researchers.
- Specificity: versions, benchmarks, architecture details, failures, limitations.
- Quality of writing or source credibility.
- Community discussion quality, not only raw engagement count.
- Engagement signals such as HN score, comments, Reddit score, GitHub stars gained, or repo activity.
- Fit for the requested digest scope.

Do not over-score pure announcements without technical substance. Do not under-score niche systems or infrastructure work if it is technically deep and relevant.

## Output

For each input item, output `id`, `ai_score`, `ai_reason`, `ai_summary`, and `ai_tags` following `references/schemas.md`.
