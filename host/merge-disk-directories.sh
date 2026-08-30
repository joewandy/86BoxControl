#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: merge-disk-directories.sh [--keep-first] OUTPUT_DIRECTORY DISK_DIRECTORY...

The default is safe: files with the same relative path must be identical or the
merge fails. --keep-first keeps the first version and reports each conflict.
EOF
  exit 2
}

keep_first=0
if [[ ${1:-} == "--keep-first" ]]; then
  keep_first=1
  shift
fi

[[ $# -ge 2 ]] || usage

output=$1
shift

[[ ! -e "$output" ]] || {
  echo "Refusing to overwrite: $output" >&2
  exit 1
}

parent=$(dirname "$output")
mkdir -p "$parent"
staging=$(mktemp -d "$parent/.86box-merge.XXXXXX")
cleanup() {
  [[ ! -d "$staging" ]] || rm -rf "$staging"
}
trap cleanup EXIT

had_conflict=0
for source_dir in "$@"; do
  [[ -d "$source_dir" ]] || {
    echo "Disk directory not found: $source_dir" >&2
    exit 1
  }

  while IFS= read -r -d '' source_file; do
    relative=${source_file#"$source_dir"/}
    target="$staging/$relative"

    if [[ -f "$target" ]]; then
      if ! cmp -s "$source_file" "$target"; then
        echo "Conflict: $relative (keeping the earlier file)" >&2
        had_conflict=1
      fi
      continue
    fi

    mkdir -p "$(dirname "$target")"
    cp -p "$source_file" "$target"
  done < <(find "$source_dir" -type f -print0)
done

if [[ $had_conflict -eq 1 && $keep_first -eq 0 ]]; then
  echo "Merge aborted. Review the conflicts or rerun with --keep-first." >&2
  exit 1
fi

mv "$staging" "$output"
trap - EXIT
echo "Created $output"
