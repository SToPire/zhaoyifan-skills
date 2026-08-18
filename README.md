# zhaoyifan-skills

A collection of reusable agent skills organized according to the
[Agent Skills specification](https://agentskills.io/specification).

## Available Skills

- `git-commit-digest`: Analyze new commits from subscribed Git repositories and produce a Chinese digest.
- `horizon-digest`: Build technical digests from configured web sources.
- `linux-erofs-thread`: Analyze linux-erofs mailing-list threads and patch series.
- `paper-reading`: Produce structured Chinese reports for arXiv papers.
- `peer-review`: Run mutual cross-agent code reviews.
- `qemu-kernel-lab`: Build repeatable QEMU-based Linux kernel test environments.
- `send-webhook`: Send existing Markdown files through configured HTTP(S) webhooks.

## Install

List the skills available in this repository:

```bash
npx skills add SToPire/zhaoyifan-skills --list
```

Install interactively:

```bash
npx skills add SToPire/zhaoyifan-skills
```

Install a specific skill:

```bash
npx skills add SToPire/zhaoyifan-skills --skill paper-reading
```
