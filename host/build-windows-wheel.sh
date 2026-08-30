#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
output_dir="$repo_root/output/windows-host"
mkdir -p "$output_dir"

uv build --wheel --out-dir "$output_dir"
echo "Built the native Windows host wheel in $output_dir"
