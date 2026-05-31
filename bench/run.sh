#!/bin/sh
# Build and run every bench/*.kod. Each program reports its own
# self-timed work in ms.
set -e
cd "$(dirname "$0")/.."

for src in bench/*.kod; do
    stem="$(basename "$src" .kod)"
    uv run kod build "$src" >/dev/null 2>&1
    "./build/apps/$stem/$stem"
done
