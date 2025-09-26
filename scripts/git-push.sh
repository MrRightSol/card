#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [remote] [branch] [--force]

Defaults: remote=origin, branch=current branch

Examples:
  $0                    # push current branch to origin
  $0 origin feature/x   # push 'feature/x' to origin
  $0 origin main --force
EOF
}

REMOTE=${1-}
BRANCH_ARG=${2-}
FORCE=false

if [[ "$REMOTE" == "--help" || "$REMOTE" == "-h" ]]; then
  usage; exit 0
fi

if [[ "$BRANCH_ARG" == "--force" ]]; then
  FORCE=true
  BRANCH_ARG=""
fi

if [[ ${3-} == "--force" ]]; then
  FORCE=true
fi

if [[ -z "$REMOTE" ]]; then
  REMOTE=origin
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository."; exit 2
fi

if [[ -z "$BRANCH_ARG" ]]; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD)
else
  BRANCH=$BRANCH_ARG
fi

if [[ "$FORCE" == true ]]; then
  echo "Force pushing $BRANCH to $REMOTE"
  git push $REMOTE +$BRANCH
else
  git push $REMOTE $BRANCH
fi

echo "Push complete."
