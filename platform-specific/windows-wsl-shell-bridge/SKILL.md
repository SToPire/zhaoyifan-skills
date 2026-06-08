---
name: windows-wsl-shell-bridge
description: Windows-specific workflow for running complex Bash or shell commands inside WSL from Windows PowerShell. Use when scripts contain `$variables`, command substitutions, loops, quotes, here-documents, or multi-line bodies that would be corrupted by PowerShell or `wsl.exe bash -lc` quoting. Provides a bundled `wslsh.ps1` bridge that writes the script to a temporary `.sh` file and executes it inside WSL.
metadata:
  short-description: Run complex WSL shell scripts from Windows safely
---

# Windows WSL Shell Bridge

Use this skill on Windows when invoking WSL commands from PowerShell and the shell body is more than a simple command.

Prefer the bridge for:

- Bash variables such as `$tool`, `$PATH`, and `$HOME`
- Command substitutions such as `$(whoami)`
- Loops, functions, conditionals, and here-documents
- Multi-line scripts
- Any command where nested quoting through `wsl.exe bash -lc "..."` is fragile

For simple commands such as `wsl.exe uname -a`, calling `wsl.exe` directly is fine.

## Bridge Script

Bundled script:

`scripts/wslsh.ps1`

The bridge accepts a script from PowerShell pipeline input, writes it as UTF-8 without BOM, converts CRLF to LF, maps the current Windows working directory to `/mnt/<drive>/...`, and runs it in WSL using `bash` by default.

Use it like this from PowerShell:

```powershell
@'
for tool in bash zsh git python3; do
  path=$(command -v "$tool" 2>/dev/null || true)
  printf "%s => %s\n" "$tool" "${path:-missing}"
done
'@ | C:\Users\ZYF\.codex\skills\windows-wsl-shell-bridge\scripts\wslsh.ps1
```

Put the Bash script inside a single-quoted PowerShell here-string (`@' ... '@`) so PowerShell does not expand `$...` before the bridge receives it.

## Options

- `-Distro <name>`: run in a specific WSL distribution.
- `-Shell <name>`: use another shell executable instead of `bash`.
- `-Login`: pass `-l` to the shell before the generated script path.

Example:

```powershell
@'
printf 'cwd=%s\n' "$PWD"
printf 'user=%s\n' "$(whoami)"
'@ | C:\Users\ZYF\.codex\skills\windows-wsl-shell-bridge\scripts\wslsh.ps1 -Distro archlinux
```

## Working Guidance

When this skill triggers, prefer `scripts/wslsh.ps1` for WSL-side exploration, checks, and scripts. Keep the current Windows working directory at the relevant project root before invoking the bridge so WSL runs from the corresponding `/mnt/c/...` location.

Do not symlink or share the entire `.codex` directory between Windows and WSL. If WSL-side Codex also needs this skill, copy or symlink only this skill directory.
