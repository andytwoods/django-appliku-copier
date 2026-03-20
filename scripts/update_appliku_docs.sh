#!/usr/bin/env bash
# Fetch the latest Appliku LLM reference into APPLIKU.md.
# Run this before working on Appliku-related features to get current docs.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="$REPO_ROOT/APPLIKU.md"

curl -fsSL https://appliku.com/llms.txt -o "$OUTPUT"
echo "Updated $OUTPUT"
