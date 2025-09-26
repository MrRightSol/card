#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [--remote <url>] [--email <email>] [--name <name>]

Initialise a git repository in this project (if not already a repo),
create a sensible .gitignore, make an initial commit and optionally
add a remote and push the initial branch (main).

Options:
  --remote <url>   Set 'origin' remote to <url> and push the initial branch
  --email <email>  Configure git user.email for this repo
  --name <name>    Configure git user.name for this repo
EOF
}

REMOTE=""
GIT_EMAIL=""
GIT_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote) REMOTE="$2"; shift 2;;
    --email) GIT_EMAIL="$2"; shift 2;;
    --name) GIT_NAME="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Already inside a git repository. Nothing to initialise."
else
  echo "Initialising git repository..."
  git init -b main
fi

if [[ -n "$GIT_NAME" ]]; then
  git config user.name "$GIT_NAME"
fi
if [[ -n "$GIT_EMAIL" ]]; then
  git config user.email "$GIT_EMAIL"
fi

# Ensure a reasonable .gitignore exists
if [[ ! -f .gitignore ]]; then
  cat > .gitignore <<'GITIGNORE'
# Python
venv/
venv2/
__pycache__/
*.pyc
.env
.env.*

# OS / Editor
.DS_Store
.vscode/
.idea/

# Test / build
.pytest_cache/
dist/
build/

# local data
data/
*.db
GITIGNORE
  git add .gitignore
fi

git add -A
if git diff --cached --quiet; then
  echo "No changes to commit."
else
  git commit -m "chore: initial commit"
fi

if [[ -n "$REMOTE" ]]; then
  echo "Adding remote origin -> $REMOTE"
  git remote remove origin 2>/dev/null || true
  git remote add origin "$REMOTE"
  echo "Pushing main to origin..."
  git push -u origin main
fi

echo "Done. Use scripts/git-commit.sh, scripts/git-rollback.sh, scripts/git-push.sh to manage changes."
