#!/usr/bin/env bash
set -euo pipefail

if [[ ${1-} == "" || ${1-} == "-h" || ${1-} == "--help" ]]; then
  echo "Usage: $0 <branch-name>"
  exit 2
fi

BRANCH=$1

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository. Run scripts/git-setup.sh first to initialise."
  exit 2
fi

if git show-ref --quiet refs/heads/$BRANCH; then
  echo "Branch $BRANCH already exists. Checking out."
  git checkout $BRANCH
else
  git checkout -b $BRANCH
fi

echo "Now on branch: $(git rev-parse --abbrev-ref HEAD)"
