---
name: linux-erofs-thread
description: Find linux-erofs mailing-list threads on lore.kernel.org, fetch every message in a thread, summarize the discussion at per-email granularity, produce a Chinese technical report, and optionally save patch series in git-am-ready form with b4.
---

# linux-erofs-thread

Use this skill when the user asks to investigate a linux-erofs mailing-list
discussion, summarize a lore thread, understand review history, or fetch patches
from a thread for direct git application.

## Inputs

Accept any of these:

- A lore URL for `linux-erofs`, `all`, or another kernel list.
- A Message-ID, with or without angle brackets.
- Search terms such as a feature name, patch subject, author, bug symptom, or
  commit title.
- An output path for the report and, if requested, a patch output path.

Default output language is Simplified Chinese unless the user asks otherwise.

## Tools

- Use `scripts/fetch_lore_thread.py` to download a thread mbox and extract per
  message JSON/Markdown reading material.
- Use `scripts/save_thread_patches.sh` when patches must be saved in a form that
  can be applied by `git am`.
- Prefer `b4` for patch extraction. Do not reconstruct patch files manually from
  quoted email text unless the user explicitly asks for a best-effort fallback.

## Workflow

### 1. Locate The Thread

If the user gives a lore URL or Message-ID, use it directly.

If the user gives search terms:

- Search for `site:lore.kernel.org/linux-erofs <terms>`.
- Prefer direct `lore.kernel.org` results over mirrors.
- Mirror pages are acceptable only for discovering the original Message-ID or
  lore URL.
- When multiple plausible threads exist, choose the one whose subject, author,
  version, and dates best match the user's intent; mention ambiguity briefly.

### 2. Fetch The Full Thread

Run:

```bash
python3 scripts/fetch_lore_thread.py \
  --url <lore-url-or-message-id> \
  --output-dir <artifact-dir>
```

The script writes:

- `<slug>.mbox`: raw thread mbox.
- `<slug>.messages.json`: parsed message metadata and body text.
- `<slug>.messages.md`: compact per-message reading index.

Use the JSON as the canonical input for analysis. Reopen the raw mbox only when
the JSON body was truncated or MIME parsing looks suspicious.

### 3. Summarize At Per-Email Granularity

Do not collapse the thread into only a cover-letter summary. For every message,
capture:

- index in thread order
- author, date, subject, and Message-ID
- message role: cover, patch, review, reply, maintainer decision, bot/test
  result, resend/version note, or unrelated side discussion
- key claim or change
- technical details that affect EROFS behavior, on-disk format, kernel API,
  userspace tooling, compatibility, performance, or review outcome
- review tags such as `Reviewed-by`, `Acked-by`, `Tested-by`, `Fixes`,
  `Reported-by`, `Suggested-by`, `Closes`, and maintainer instructions

For patch emails, summarize the commit intent and touched subsystem, but keep
review comments and follow-up replies as separate messages. For replies, state
what exact concern, request, objection, or resolution the reply introduced.

### 4. Produce The Report

Use this structure unless the user asks for a different format:

```markdown
# <thread subject>

## 基本信息
- lore: <canonical thread url>
- message-id: <root or selected message id>
- 时间范围: <first date> - <last date>
- 参与者: <main participants>
- 邮件数: <count>
- patch 状态: <none | single patch | series, version, count>

## 总结
<2-5 bullets about the purpose, design, and final discussion state>

## 逐封邮件梳理
| # | 时间 | 作者 | 类型 | 主题 | 要点 |
|---|------|------|------|------|------|

## 技术主线
<group the thread's technical discussion by issue, not by chronology>

## 结论和未决问题
<what was accepted, rejected, requested, or left unresolved>

## Patch 获取情况
<paths to saved git-am-ready files, validation command, and result>
```

Keep the report grounded in email content. If you infer a thread outcome from
silence, later versions, or maintainer wording, label it as an inference.

### 5. Save Patches When Needed

If the user asks to fetch patches, or the report would be incomplete without
the patch artifact, run:

```bash
scripts/save_thread_patches.sh <lore-url-or-message-id> <patch-output-dir>
```

This uses `b4 am -o <patch-output-dir>` and produces mbox files intended for
`git am`.

Validate when a target git tree is available:

```bash
git am --check <patch-output-dir>/*.mbx
```

If validation fails, report the exact failing command and error. Do not edit the
patch payload unless the user explicitly asks for a rebased or repaired patch.

## Rules

- Treat lore/public-inbox as the source of truth.
- Preserve Message-IDs and links in the report so the user can audit claims.
- Separate email-thread facts from your own technical inference.
- Do not omit short review replies; they often carry the final decision or tag.
- Do not overwrite an existing report or patch directory unless the user asks.
- When the thread has multiple patch revisions, summarize the selected thread
  first and mention nearby revisions only when they explain the outcome.
