#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 -m "commit message" [-b branch] [-a] [-t tag]

Options:
  -m MESSAGE   Commit message (required)
  -b BRANCH    Create and/or switch to BRANCH before committing
  -a           Stage all changes (git add -A)
  -t TAG       Create lightweight tag TAG pointing to the new commit
EOF
}

MSG=""
BRANCH=""
ALL=false
TAG=""

while getopts ":m:b:at:" opt; do
  case $opt in
    m) MSG="$OPTARG";;
    b) BRANCH="$OPTARG";;
    a) ALL=true;;
    t) TAG="$OPTARG";;
    \?) echo "Invalid option -$OPTARG"; usage; exit 2;;
  esac
done

if [[ -z "$MSG" ]]; then
  echo "Commit message is required."; usage; exit 2
fi

if [[ -n "$BRANCH" ]]; then
  if git show-ref --quiet refs/heads/$BRANCH; then
    git checkout $BRANCH
  else
    git checkout -b $BRANCH
  fi
fi

if $ALL; then
  git add -A
fi

if git diff --cached --quiet; then
  echo "No staged changes to commit."; exit 0
fi

git commit -m "$MSG"

if [[ -n "$TAG" ]]; then
  git tag "$TAG"
  echo "Created tag $TAG"
fi

echo "Commit complete. Use scripts/git-push.sh to push to remote."
