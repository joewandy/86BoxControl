#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 OUTPUT_DIRECTORY DISK_IMAGE..." >&2
  exit 2
}

[ "$#" -ge 2 ] || usage

output=$1
shift

command -v mcopy >/dev/null 2>&1 || {
  echo "mcopy is required; install mtools first." >&2
  exit 1
}

if [ -e "$output" ] && [ "$(find "$output" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  echo "Refusing to use non-empty output directory: $output" >&2
  exit 1
fi

mkdir -p "$output"
manifest="$output/SHA256SUMS"
: > "$manifest"

number=1
for image in "$@"; do
  [ -f "$image" ] || {
    echo "Disk image not found: $image" >&2
    exit 1
  }

  disk_name=$(printf 'disk%02d' "$number")
  disk_dir="$output/$disk_name"
  mkdir "$disk_dir"
  mcopy -s -i "$image" '::*' "$disk_dir"
  shasum -a 256 "$image" >> "$manifest"
  echo "Extracted $image -> $disk_dir"
  number=$((number + 1))
done
