#!/bin/sh
# Pull the latest version of this branch from GitHub and rebuild/restart what changed.
# Your .env, certs/ and database are untouched (they are not in git).
#   cd /opt/gift-top-up/isp-platform && ./scripts/update.sh
set -e
cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Local edits to tracked files would be overwritten:"
  git status --short --untracked-files=no
  echo "Keep a copy (e.g. cp frontend/allowlist.conf ~/), undo with: git checkout -- <file>, then re-run."
  exit 1
fi

branch=$(git rev-parse --abbrev-ref HEAD)
old=$(git rev-parse HEAD)

# The link to GitHub is flaky here: HTTP/1.1 plus a few retries.
n=1
until git -c http.version=HTTP/1.1 fetch origin "$branch"; do
  [ $n -ge 5 ] && { echo "GitHub unreachable after $n tries."; exit 1; }
  echo "fetch failed, retry $n/4 in $((n * 5))s..."; sleep $((n * 5)); n=$((n + 1))
done
git merge --ff-only FETCH_HEAD

new=$(git rev-parse HEAD)
if [ "$old" = "$new" ]; then
  echo "Already up to date ($(git log -1 --format='%h %s'))."
  exit 0
fi
echo "Updated:"
git log --format='  %h %s' "$old..$new"

docker compose up -d --build
docker compose ps
