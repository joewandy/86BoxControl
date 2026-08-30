#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 SOURCE_DIRECTORY OUTPUT.iso" >&2
  exit 2
}

[ "$#" -eq 2 ] || usage

source_dir=$1
output=$2

[ -d "$source_dir" ] || {
  echo "Source directory not found: $source_dir" >&2
  exit 1
}

case "$output" in
  *.iso) ;;
  *)
    echo "Output must end in .iso: $output" >&2
    exit 1
    ;;
esac

[ ! -e "$output" ] || {
  echo "Refusing to overwrite: $output" >&2
  exit 1
}

if command -v hdiutil >/dev/null 2>&1; then
  hdiutil makehybrid -iso -joliet -o "$output" "$source_dir"
elif command -v xorriso >/dev/null 2>&1; then
  xorriso -as mkisofs -iso-level 3 -J -R -o "$output" "$source_dir"
else
  echo "No supported ISO builder found; install xorriso on Linux or use hdiutil on macOS" >&2
  exit 1
fi
echo "Created $output"
