#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository."; exit 2
fi

echo "Branch: $(git rev-parse --abbrev-ref HEAD)"
echo
git status --short
echo
echo "Last 5 commits:"
git --no-pager log -n 5 --oneline
echo
echo "Remotes:"
git remote -v || true
