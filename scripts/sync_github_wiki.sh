#!/usr/bin/env bash
# Sync ai/docs/wiki/*.md -> github.com/mouxangithub/ai.wiki
set -euo pipefail

WIKI_REPO="${WIKI_REPO:-https://github.com/mouxangithub/ai.wiki.git}"
COMMIT_MSG="${COMMIT_MSG:-docs: sync OP Agent wiki from ai/docs/wiki}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WIKI_SRC="$AI_ROOT/docs/wiki"
TMP="$(mktemp -d)"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

if [[ ! -d "$WIKI_SRC" ]]; then
  echo "Wiki source not found: $WIKI_SRC" >&2
  exit 1
fi

echo "Cloning $WIKI_REPO"
git clone "$WIKI_REPO" "$TMP"
cp "$WIKI_SRC"/*.md "$TMP/"
cd "$TMP"
git add -A
if git diff --staged --quiet; then
  echo "Wiki already up to date."
  exit 0
fi
git commit -m "$COMMIT_MSG"
git push
echo "Wiki pushed successfully."
