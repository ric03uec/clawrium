#!/usr/bin/env bash
# Concatenate per-scene captured outputs into a single timeline transcript.
# Usage: bash docs/demos/lib/stitch.sh <demo-folder>
#   <demo-folder> = path containing outputs/NN-*.txt files (e.g. docs/demos/20260618-quickstart-onboarding)
# Writes <demo-folder>/stitched.txt and prints a line count summary.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <demo-folder>" >&2
  exit 1
fi

DEMO_DIR="$1"
OUT_DIR="$DEMO_DIR/outputs"
STITCH="$DEMO_DIR/stitched.txt"

if [ ! -d "$OUT_DIR" ]; then
  echo "ERROR: $OUT_DIR does not exist or has no scene captures." >&2
  exit 1
fi

: > "$STITCH"
for f in "$OUT_DIR"/*.txt; do
  [ -e "$f" ] || { echo "ERROR: no scene capture files found in $OUT_DIR" >&2; exit 1; }
  scene=$(basename "$f" .txt)
  printf '\n========== %s ==========\n' "$scene" >> "$STITCH"
  cat "$f" >> "$STITCH"
done

echo "--- per-scene line counts ---"
wc -l "$OUT_DIR"/*.txt
echo ""
echo "--- stitched total ---"
wc -l "$STITCH"
