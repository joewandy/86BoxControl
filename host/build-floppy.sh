#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 SOURCE_DIRECTORY OUTPUT.img 720|1200|1440 [VOLUME_LABEL]" >&2
  exit 2
}

[ "$#" -ge 3 ] && [ "$#" -le 4 ] || usage

source_dir=$1
output=$2
capacity=$3
label=${4:-RETRODISK}

[ -d "$source_dir" ] || {
  echo "Source directory not found: $source_dir" >&2
  exit 1
}

[ ! -e "$output" ] || {
  echo "Refusing to overwrite: $output" >&2
  exit 1
}

case "$capacity" in
  720) bytes=737280 ;;
  1200) bytes=1228800 ;;
  1440) bytes=1474560 ;;
  *) usage ;;
esac

case "$label" in
  *[!A-Za-z0-9_-]*|'')
    echo "Volume label must contain only letters, numbers, underscore, or dash." >&2
    exit 1
    ;;
esac

[ "${#label}" -le 11 ] || {
  echo "FAT volume label must be at most 11 characters." >&2
  exit 1
}

command -v mformat >/dev/null 2>&1 && command -v mcopy >/dev/null 2>&1 || {
  echo "mformat and mcopy are required; install mtools first." >&2
  exit 1
}

parent=$(dirname "$output")
mkdir -p "$parent"
temporary=$(mktemp "$parent/.86box-floppy.XXXXXX")
cleanup() {
  [ ! -f "$temporary" ] || rm -f "$temporary"
}
trap cleanup EXIT HUP INT TERM

truncate -s "$bytes" "$temporary"
mformat -i "$temporary" -f "$capacity" -v "$label" ::

set -- "$source_dir"/*
[ -e "$1" ] || {
  echo "Source directory is empty: $source_dir" >&2
  exit 1
}
mcopy -s -i "$temporary" "$@" ::

mv "$temporary" "$output"
trap - EXIT HUP INT TERM
echo "Created $output"
