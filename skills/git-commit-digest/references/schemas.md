# Artifact Schemas

Agent-written files must be strict UTF-8 JSON without Markdown fences.

## analyses.json

Write a JSON array containing exactly one object for every commit in the analysis batches:

```json
[
  {
    "id": "0123456789abcdef:full-commit-sha",
    "purpose": "修复压缩数据读取失败后页面状态未清理的问题。",
    "changes": [
      "在解压错误路径中补充页面解锁和引用释放。",
      "统一重复的清理分支并保留底层 I/O 错误。"
    ],
    "impact": "影响异常恢复路径，正常读取流程保持不变。",
    "category": "fix",
    "subsystem": "erofs",
    "confidence": "high"
  }
]
```

Rules:

- Copy `id` exactly from the batch.
- Include every commit once, including merge commits.
- Use only categories and confidence values defined in `analysis-guidance.md`.
- Do not add prose outside the JSON array.

When no commits were fetched, write `[]`.

## digest.json

Write one global overview and one grouped digest object for every successful repository that has commits:

```json
{
  "overview": [
    "Linux 的主要变化集中在 EROFS 错误处理和内存管理。",
    "erofs-utils 改进了镜像构建流程并补充测试。"
  ],
  "repositories": [
    {
      "id": "0123456789abcdef",
      "overview": "本次更新以错误处理修复为主，没有明显外部接口变化。",
      "groups": [
        {
          "title": "EROFS：完善解压失败后的状态清理",
          "purpose": "避免解压失败后残留页面状态影响后续读取。",
          "changes": [
            "补充页面解锁和引用释放。",
            "统一错误清理路径。"
          ],
          "impact": "提高异常路径可靠性，正常读取行为保持不变。",
          "commit_ids": [
            "0123456789abcdef:full-commit-sha"
          ]
        }
      ]
    }
  ]
}
```

Rules:

- Copy repository and commit IDs exactly from `analyzed_commits.json`.
- Include every repository with commits exactly once.
- Include every commit exactly once across that repository's groups.
- Do not include unchanged or failed repositories in `repositories`; the renderer obtains their status from the fetched artifact.
- Keep `overview` as concise Chinese bullet text. It may be empty only when there are no new commits.
- Keep group titles specific enough to identify the subsystem and modification purpose.

When no commits were fetched, write:

```json
{
  "overview": [],
  "repositories": []
}
```

## Script-Generated Files

- `raw_commits.json`: repository metadata, bounded commit messages/file lists/patches with truncation flags, and per-repository status.
- `analyzed_commits.json`: `raw_commits.json` with validated `analysis` objects merged into commits.
- `validated_digest.json`: normalized and coverage-checked digest input.
- `base_state.json`: validated state snapshot read at fetch time; compare it during state promotion.
- `next_state.json`: pending default-branch names and HEADs, plus preserved first-subscription time/HEAD baselines for repositories that have not yet succeeded; promote it only after rendering succeeds.
- `meta.json`: counts, technical warnings, and structured analysis-evidence truncation details for operators, not report content.
- `state.json.transaction.json`: temporary finalization journal used to recover report/state consistency after an abrupt process exit; scripts remove it after recovery.
