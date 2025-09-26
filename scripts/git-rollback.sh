#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [commit-ish]

If commit-ish is provided, this script will hard-reset the current branch
to that commit. If not provided it will reset to HEAD~1 (undo last commit).

The script first creates a safety tag (backup/<timestamp>) pointing to the
current HEAD so you can recover if needed.
EOF
}

TARGET=${1-}

if [[ "$TARGET" == "-h" || "$TARGET" == "--help" ]]; then
  usage; exit 0
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository."; exit 2
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_TAG="backup/$TS"
git tag "$BACKUP_TAG" || true
echo "Created backup tag: $BACKUP_TAG -> $(git rev-parse --short HEAD)"

if [[ -z "$TARGET" ]]; then
  TARGET="HEAD~1"
fi

echo "Resetting to $TARGET (this will discard working tree and index changes)."
read -p "Are you sure? [y/N] " ans
if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
  echo "Aborted."
  exit 1
fi

git reset --hard "$TARGET"
echo "Reset complete. Current HEAD -> $(git rev-parse --short HEAD)"
echo "If you need to recover the previous state: git checkout $BACKUP_TAG"
