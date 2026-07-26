#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <lore-url-or-message-id> <patch-output-dir>" >&2
  exit 2
fi

locator=$1
output_dir=$2

if ! command -v b4 >/dev/null 2>&1; then
  echo "b4 is required for git-am-ready kernel patch extraction." >&2
  echo "Install it with your distro package manager or: python3 -m pip install --user b4" >&2
  exit 127
fi

if [ -e "$output_dir" ] && [ "$(find "$output_dir" -mindepth 1 -maxdepth 1 | head -n 1)" ]; then
  echo "refusing to write into non-empty output directory: $output_dir" >&2
  exit 1
fi

mkdir -p "$output_dir"
b4 am -o "$output_dir" "$locator"
