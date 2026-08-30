#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
image=${RETROBRIDGE_MINGW_IMAGE:-retrobridge-mingw32:local}

docker build --platform linux/amd64 \
  -f "$repo_root/toolchain/Dockerfile.mingw32" \
  -t "$image" "$repo_root/toolchain"
docker run --rm --platform linux/amd64 \
  -v "$repo_root:/src" \
  -w /src/guest/windows98/retrobridge98 \
  "$image" \
  make -f Makefile.mingw clean all

output_dir="$repo_root/output/guest"
mkdir -p "$output_dir"
find "$output_dir" -mindepth 1 -maxdepth 1 -type f -delete
cp "$repo_root/guest/windows98/retrobridge98/retrobridge98.exe" "$output_dir/retrobridge98.exe"

python3 "$repo_root/host/check-win98-pe.py" "$output_dir/retrobridge98.exe"

echo "Built Windows 98 executable in $repo_root/output/guest"
