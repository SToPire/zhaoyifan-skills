# Report Format

Render a Simplified Chinese Markdown report with this fixed structure:

```markdown
# Git Commit Digest · <YYYY-MM-DD>

生成时间：<local date and time>
范围：<exact persisted initial boundary, complete-history recovery, or last successful state to current run>

| 项目 | 分支 | 新增 Commit | 变更主题 | 状态 |
| --- | --- | ---: | ---: | --- |

## 今日概览

- <cross-repository summary>

## <project name>

新增 N 个 Commit，归纳为 M 个变更主题。<repository overview>

### <specific topic title>

**目的**

<why the change was made>

**修改内容**

- <concrete change>

**影响**

<behavioral or engineering impact>

**相关 Commit**

- `<short sha>` <subject>
```

Rules:

- Show every configured repository in the summary table.
- Use repository `project_name` in the summary table, range labels, detailed-section headings, and agent-written overview prose. Fall back to the technical `name` slug only when `project_name` is absent in an older artifact.
- Derive the range line from each repository's `coverage` metadata. Show the persisted timestamp for `initial_since`, say `完整历史` for `initial_full_history`, and identify repository-specific ranges when successful repositories use different modes or boundaries.
- Render detailed sections only for successful repositories with new commits.
- List every commit under exactly one topic.
- Link commit SHAs when the remote has a known HTTP commit URL.
- Do not render raw patches, email addresses, model confidence, or internal JSON fields.
- Do not add an “异常与限制” section.
- Keep fetch failures, history-rewrite warnings, and truncation details in `meta.json` only. A failed repository may be marked `失败` in the summary table without an error narrative.
