# Configuration

The caller supplies the config path. Use a JSON object with unique Git remote URLs, a final Markdown path, and a persistent state directory:

```json
{
  "repositories": [
    "https://github.com/e2b-dev/infra.git",
    "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git",
    "https://github.com/erofs/erofs-utils.git"
  ],
  "project_names": {
    "https://github.com/e2b-dev/infra.git": "E2B"
  },
  "output_file": "/path/to/git-commit-digest/{run_id}.md",
  "state_directory": "/path/to/git-commit-digest-state"
}
```

Use optional `project_names` overrides when a public project name differs from its remote repository slug. The override is the authoritative report-facing label, while URL-based repository IDs and cursors remain unchanged. Repositories without an override use the URL's repository basename.

`output_file` must resolve to `.md` and may contain `{run_id}` and `{date}`. String values may reference environment variables as `${VAR_NAME}`. Resolve relative paths against the config directory and refuse to overwrite an existing report.

The state directory contains `state.json`, its lock and recovery journal, bare Git mirrors, and recoverable run directories. The scripts preserve the first 24-hour subscription boundary across retries, compare later runs by reachability from the last successful default-branch HEAD, and retain cursors on repository failure or unsafe history rewrites. Keep scheduling and credentials outside this config.
