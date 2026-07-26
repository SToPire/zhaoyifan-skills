---
name: peer-review
description: Cross-agent peer review workflow for code reviews. Use this skill whenever the user asks Codex to review code, a diff, commit, pull request, merge request, patch, or branch and wants another code agent such as Claude Code, Codex, or a configured CLI reviewer to independently propose findings and critically audit Codex's findings before results are returned. Also use when the user mentions peer review, a second reviewer, cross-agent review, mutual review, another agent checking findings, Claude reviewing findings, or wants review findings validated rather than accepted at face value.
---

# Peer Review

## Overview

Run a mutual cross-agent code review. The active agent is the orchestrator because it is running inside the user's TUI, but the review roles are symmetric: both agents independently propose findings, then each agent audits the other's findings. The final review is the de-duplicated union of findings accepted by the opposite agent.

This skill is for review validation, not for delegating the whole review to another agent. Always do your own independent review before reading the peer agent's proposed findings.

## Workflow

1. Identify the review target from the user request: diff, commit range, PR/MR, branch, or specific files.
2. Identify the peer agent command.
   - Prefer an explicit command from the user or environment, such as `PEER_REVIEW_AGENT_CMD`.
   - If none is configured, inspect available commands with lightweight checks such as `command -v claude`, `command -v codex`, and the relevant `--help` output.
   - Use a non-interactive CLI mode when available.
   - Do not call the same active agent in a way that recursively invokes this skill.
3. Produce your own independent review first. Do not call the peer agent before you have a draft set of findings.
4. Ask the peer agent to independently review the same target without seeing your draft findings.
5. Audit the peer agent's proposed findings yourself.
6. Ask the peer agent to audit your proposed findings.
7. Build the final accepted set:
   - Include your findings accepted by the peer.
   - Include peer findings accepted by you.
   - Merge duplicates, keeping the clearest statement and strongest evidence.
   - Exclude rejected findings.
   - Put unresolved disagreements in a separate disputed section, not in the accepted findings.
8. Iterate only on findings marked `REVISE` or `NEEDS_EVIDENCE`.
   - Gather missing evidence or narrow the claim.
   - Re-send only the changed findings for audit.
   - Stop when all accepted findings have passed opposite-agent audit.
   - If the same disagreement repeats without new evidence for two rounds, stop and mark it disputed.

Use a one-way fallback only when mutual review cannot run because the peer CLI is unavailable, the target is too large for the peer context, or the user explicitly asks for a faster review. If falling back, say so in the final response.

## Finding Format

Use this structure for both agents' proposed findings:

```text
- ID: A1
  Severity: High | Medium | Low
  Location: path/to/file:line
  Claim:
  Evidence:
  Consequence:
  Validation:
```

Use `A1`, `A2`, ... for findings proposed by the active agent. Use `B1`, `B2`, ... for findings proposed by the peer agent.

## Independent Peer Review Prompt

Use this prompt before showing the peer agent your own findings. This gives the peer a real chance to propose issues rather than merely react to yours.

```text
You are an independent code reviewer in a cross-agent review.

Review the target below as if you were the primary reviewer. Do not assume another agent has already found the important issues. Your job is to independently find concrete defects, regressions, security risks, data loss risks, concurrency problems, API contract violations, or missing tests that matter for this change.

Scope:
- Review target: <target description>
- Repository/path: <repo or worktree path>
- Your role: independent proposer of review findings

Rules:
- Work read-only. Do not edit files, commit, or perform destructive commands.
- Do not invoke another code agent or a peer-review skill.
- Prioritize correctness and behavioral risk over style.
- Do not include speculative issues without code or diff evidence.
- If there are no high-confidence findings, say so.
- Use stable IDs B1, B2, ...

Return findings in this structure:

- ID:
  Severity: High | Medium | Low
  Location:
  Claim:
  Evidence:
  Consequence:
  Validation:

Relevant context:
<paste diff summary, file snippets, commands run, or paths the peer should inspect>
```

## Audit Prompt

Use this prompt when one agent audits the other agent's proposed findings. Keep the critical-review language intact.

```text
You are the second reviewer in a cross-agent code review.

Your job is to critically audit the review findings below, not to agree with them. Treat each finding as a hypothesis that may be wrong. Try to refute it using the provided code, diff, and repository evidence. Do not defer to the proposer. Do not reward plausible-sounding claims without concrete evidence.

Scope:
- Review target: <target description>
- Repository/path: <repo or worktree path>
- Finding proposer: <agent name>
- Your role: adversarial auditor of the submitted findings

Rules:
- Work read-only. Do not edit files, commit, or perform destructive commands.
- Do not invoke another code agent or a peer-review skill.
- For each finding, decide one of: ACCEPT, REJECT, REVISE, NEEDS_EVIDENCE.
- Require exact code/diff evidence for ACCEPT.
- Reject findings that depend on incorrect assumptions, impossible execution paths, missing context, or severity inflation.
- If a finding is directionally valid but overstated, mark REVISE and say exactly what should change.
- If you cannot inspect enough context, mark NEEDS_EVIDENCE rather than guessing.
- You may add newly noticed high-confidence findings, but separate them from your audit of the submitted findings.

Return this structure:

## Verdict
APPROVED only if every submitted finding is ACCEPT or has a concrete revision that would make it acceptable. Otherwise CHANGES_REQUESTED.

## Finding Audit
For each finding:
- ID:
- Decision: ACCEPT | REJECT | REVISE | NEEDS_EVIDENCE
- Rationale:
- Required change or missing evidence:

## Additional Findings
Only include issues you independently verified with code evidence.

Review findings to audit:
<paste structured findings>

Relevant context:
<paste diff summary, file snippets, commands run, or paths the peer should inspect>
```

When you audit the peer's findings yourself, apply the same decision labels and evidentiary standard. Do not keep a peer finding merely because the peer agent proposed it.

## Merge And Iteration Rules

Keep an explicit round log in your notes while working:

```text
Round 1:
- A proposed: A1, A2
- B proposed: B1
- A audit of B: B1 ACCEPT
- B audit of A: A1 ACCEPT, A2 REJECT
- Action: final candidates A1, B1; removed A2

Round 2:
- Re-sent changed findings: none
- Final accepted set: A1, B1
```

Merge duplicate or overlapping findings when they describe the same root cause and consequence. Preserve both original IDs in your notes, but present one final finding to the user.

Prefer removing weak findings over defending them. A finding should survive only if it is useful to the user and supported by concrete evidence.

Do not hide material peer objections. If final consensus was reached by dropping or narrowing findings, briefly state that peer review removed or revised draft items. If consensus cannot be reached, make that explicit and show the disputed item outside the accepted findings.

## Final Response

Lead with accepted findings, ordered by severity. For each finding, include the file/line reference and the shortest explanation needed to understand the bug or risk.

Then include a short peer-review note:

```text
Peer review: ran mutual review with <peer agent command/name> for <N> round(s); final accepted findings are the de-duplicated union of findings approved by the opposite agent.
```

If there are no accepted findings, say so directly:

```text
I found no mutually accepted issues. Draft findings that failed peer review were removed.
```

If there are disputed findings, put them after accepted findings under a separate `Disputed` section and explain that they are not part of the accepted review result.

If the peer agent could not be run, do not pretend peer review happened. State the command attempted, the failure, and provide your ordinary review separately.

## Command Handling

Because peer-agent CLIs differ, adapt invocation to the installed tool. Prefer passing the prompt through stdin or a temporary prompt file so quoting does not corrupt code snippets.

For long-running non-interactive peer CLIs, prefer an output mode that exposes progress before the final answer. This is especially important for `claude -p`, whose default text output may stay silent until the whole turn finishes even while the agent is actively reading files, running tools, or using subagents. When Claude Code is the peer agent, use streaming JSON when available and save it for inspection:

```bash
claude -p \
  --permission-mode dontAsk \
  --verbose \
  --output-format stream-json \
  --include-partial-messages \
  --add-dir <repo or worktree path> < "$tmp_prompt" \
  | tee <peer-output.jsonl>
```

In current Claude Code versions, `--output-format stream-json` requires `--verbose` when used with `--print`/`-p`; keep the two options together.

Also keep prompts out of the positional argument list when using `--add-dir`.
`--add-dir` accepts one or more directory arguments, so a prompt placed after it
can be parsed as another directory and leave `claude -p` with no input. Pass the
prompt through stdin, as in the example above, or put `--add-dir` after the
prompt only when the CLI invocation has been tested for that exact version.

Treat the stream and the peer agent's local session logs as liveness evidence. If the process has no final stdout yet, inspect recent stream events, session logs, process state, and network connections before deciding it is hung. If the stream shows ongoing tool calls, partial messages, or log growth, report that the peer is still making progress and continue waiting when the user's task allows it.

Do not terminate the peer reviewer merely because it is slow. Peer review can be valuable precisely because the second agent has time to explore, so slowness alone is not a failure condition. Only stop the peer process when there is concrete evidence that it cannot work normally, such as network failures, authentication or quota exhaustion, repeated API errors, a dead process, or no liveness evidence after checking the stream, logs, process state, and network state. If you stop the peer process, record the observed failure and explain the fallback in the final response.

Do not reduce the peer agent's review scope merely to make the command faster. Keeping the peer free to explore, use subagents, and follow suspicious paths is part of the value of this skill. Only restrict tools or switch to a smaller prompt when the user explicitly asks for a faster or narrower review, or when the peer CLI cannot make progress with the full review target.

Example pattern:

```bash
tmp_prompt="$(mktemp)"
$EDITOR "$tmp_prompt"   # or write the prompt by another safe method
<peer-agent-command> < "$tmp_prompt"
```

Use repo-local or temporary files for prompts and peer outputs when needed. Avoid committing these artifacts unless the user explicitly asks for them.
