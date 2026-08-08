#!/usr/bin/env bash
# Publish wiki/*.md to a repository's GitHub wiki.
#
# A GitHub wiki is a separate git repository (<repo>.wiki.git) with no REST API
# for content, so this is a clone-copy-push, not an API call.
#
# Usage:
#   bash scripts/publish-wiki.sh [<owner>] [<repo>]
# Defaults to genai-jerry/claude-software-factory.
#
# Auth: a fine-grained PAT will NOT work - GitHub wikis are outside the
#       fine-grained permission model entirely. Use either
#   - GITHUB_TOKEN=<CLASSIC PAT with repo scope>, or
#   - WIKI_REMOTE=git@github.com:OWNER/REPO.wiki.git to push over SSH.
#
# The wiki must exist before this can push to it. GitHub creates the wiki repo
# lazily: open Settings -> Features -> Wikis, then create any one page in the
# web UI. Until then the clone fails with "repository not found".
set -euo pipefail

OWNER="${1:-genai-jerry}"
REPO="${2:-claude-software-factory}"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/wiki"
if [[ ! -d "$SRC" ]]; then
  echo "No wiki/ directory at $SRC" >&2
  exit 1
fi

if [[ -n "${WIKI_REMOTE:-}" ]]; then
  # Explicit override. Use for SSH, which is the simplest way around the
  # fine-grained-PAT limitation below:
  #   WIKI_REMOTE=git@github.com:OWNER/REPO.wiki.git bash scripts/publish-wiki.sh
  REMOTE="$WIKI_REMOTE"
  SAFE_REMOTE="$WIKI_REMOTE"
elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
  REMOTE="https://x-access-token:${GITHUB_TOKEN}@github.com/${OWNER}/${REPO}.wiki.git"
  SAFE_REMOTE="https://github.com/${OWNER}/${REPO}.wiki.git"
else
  REMOTE="https://github.com/${OWNER}/${REPO}.wiki.git"
  SAFE_REMOTE="$REMOTE"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Cloning $SAFE_REMOTE"
if ! git clone --quiet "$REMOTE" "$WORK/wiki" 2>"$WORK/err"; then
  sed "s|${GITHUB_TOKEN:-__none__}|***|g" "$WORK/err" >&2
  cat >&2 <<'EOF'

Could not clone the wiki. The usual causes:
  - The wiki has never been initialised. Enable it under
    Settings -> Features -> Wikis and create one page in the web UI first;
    GitHub does not create the .wiki.git repo until a page exists.
  - GITHUB_TOKEN is unset, expired, or lacks repo scope.
EOF
  exit 1
fi

# Wiki pages are flat: the filename is the page title, dashes become spaces.
# Copy only top-level .md files; nothing else belongs in a wiki repo.
count=0
for f in "$SRC"/*.md; do
  [[ -e "$f" ]] || continue
  cp "$f" "$WORK/wiki/"
  echo "  + $(basename "$f")"
  count=$((count + 1))
done

if [[ $count -eq 0 ]]; then
  echo "No .md files in $SRC" >&2
  exit 1
fi

cd "$WORK/wiki"
if git diff --quiet && git diff --cached --quiet && [[ -z "$(git status --porcelain)" ]]; then
  echo "Wiki already up to date; nothing to push."
  exit 0
fi

git add -A
git -c user.name="${GIT_AUTHOR_NAME:-factory}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-factory@localhost}" \
    -c commit.gpgsign=false \
    commit --quiet -m "Sync wiki from wiki/ ($count page$([[ $count -eq 1 ]] || echo s))"

# Retry the push a few times; wiki pushes are as flaky as any other.
for delay in 0 2 4 8; do
  [[ $delay -gt 0 ]] && sleep "$delay"
  if git push --quiet origin HEAD 2>"$WORK/perr"; then
    echo "Pushed $count page(s) to https://github.com/${OWNER}/${REPO}/wiki"
    exit 0
  fi
done

sed "s|${GITHUB_TOKEN:-__none__}|***|g" "$WORK/perr" >&2
cat >&2 <<'EOF'

Push failed. If the clone succeeded and only the push was denied with 403,
the cause is almost certainly the token type, not its permissions:

  Fine-grained PATs cannot write to GitHub wikis. There is no wiki
  permission in the fine-grained scope list, so granting Contents, Issues
  and Pull requests read-write changes nothing. Read access can still
  succeed, which is why the clone works and the push does not.

Either of these works instead:

  1. A classic PAT with the `repo` scope:
       https://github.com/settings/tokens/new?scopes=repo
       GITHUB_TOKEN=ghp_xxx bash scripts/publish-wiki.sh

  2. SSH, which sidesteps tokens entirely:
       WIKI_REMOTE=git@github.com:OWNER/REPO.wiki.git bash scripts/publish-wiki.sh

A 403 on push can also mean the account lacks write access to the repo, or
the wiki is restricted to collaborators under Settings -> Features -> Wikis.
EOF
exit 1
