# Git workflow helpers

This project includes a small set of convenience scripts (in the scripts/ directory)
to help get started with git and to perform common tasks safely. They are intentionally
simple wrappers around git to reduce the chance of accidental data loss and to
provide a consistent workflow for the team.

Scripts (executable under scripts/):

- git-setup.sh --remote <url> [--name <name>] [--email <email>]
  - Initialise a repository (git init -b main), create a sensible .gitignore,
    make an initial commit and optionally add and push to a remote called origin.

- git-commit.sh -m "message" [-b branch] [-a] [-t tag]
  - Commit changes with a message. Optionally switch/create a branch (-b),
    stage all changes (-a), and create a tag (-t).

- git-rollback.sh [commit-ish]
  - Create a safety tag backup/<timestamp> and hard-reset the current branch
    to commit-ish (defaults to HEAD~1). This is destructive: it resets working
    tree and index. The backup tag can be used to recover if needed.

- git-push.sh [remote] [branch] [--force]
  - Push the current (or specified) branch to a remote (default origin). Use
    --force carefully when you know you need to overwrite remote history.

- git-create-branch.sh <branch>
  - Create and checkout a feature branch (or checkout if it already exists).

- git-status.sh
  - Quick status summary: branch, short status, last 5 commits and remotes.

Quick examples

- Initialise a repo and push to GitHub:
  scripts/git-setup.sh --remote git@github.com:your-org/your-repo.git --name "Your Name" --email you@example.com

- Commit current work on a new branch:
  scripts/git-commit.sh -b feature/xyz -a -m "feat: add xyz"
  scripts/git-push.sh

- Undo the last commit (creates a backup tag first):
  scripts/git-rollback.sh

Safety notes

- git-rollback.sh does a hard reset and will drop uncommitted changes. The script
  creates a tag backup/<timestamp> before performing the reset so you can recover
  using git checkout backup/<timestamp> if you change your mind.

- These scripts are convenience helpers — they do not replace understanding of git.
  Review what they do (they are small and readable) and adapt them to your team's
  preferred workflow (e.g., use pull requests, protected branches, CI checks).
