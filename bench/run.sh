#!/bin/sh
# Build and run every bench/*.kod. Each program reports its own
# self-timed work in ms. Compile output is silenced so the table-shaped
# stdout is the only visible result.
set -e
cd "$(dirname "$0")/.."

for src in bench/*.kod; do
    stem="$(basename "$src" .kod)"
    uv run kod build "$src" >/dev/null 2>&1
    printf "%-12s " "$stem"
    "./build/apps/$stem/$stem"
done
