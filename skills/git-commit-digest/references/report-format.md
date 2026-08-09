# Report Format

Render a Simplified Chinese Markdown report with this fixed structure:

```markdown
# Git Commit Digest · <YYYY-MM-DD>

生成时间：<local date and time>
范围：<last successful state to current run, or first-run 24-hour backfill>

| 仓库 | 分支 | 新增 Commit | 变更主题 | 状态 |
| --- | --- | ---: | ---: | --- |

## 今日概览

- <cross-repository summary>

## <repository>

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
- Render detailed sections only for successful repositories with new commits.
- List every commit under exactly one topic.
- Link commit SHAs when the remote has a known HTTP commit URL.
- Do not render raw patches, email addresses, model confidence, or internal JSON fields.
- Do not add an “异常与限制” section.
- Keep fetch failures, history-rewrite warnings, and truncation details in `meta.json` only. A failed repository may be marked `失败` in the summary table without an error narrative.
