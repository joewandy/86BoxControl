#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
dotnet_root=${DOTNET_ROOT:-/home/joewandy/.dotnet}
dotnet="$dotnet_root/dotnet"
solution="$repo_root/host/windows/RetroBridge98.Settings.sln"
test_project="$repo_root/host/windows/RetroBridge98.Settings.Tests/RetroBridge98.Settings.Tests.csproj"
app_project="$repo_root/host/windows/RetroBridge98.Settings/RetroBridge98.Settings.csproj"
output_dir="$repo_root/output/windows-host/settings"
icon_path="$repo_root/output/windows-host/retrobridge98.ico"

mkdir -p "$(dirname "$icon_path")"
cd "$repo_root"
uv sync --extra dev
uv run pytest -q
uv run python -m retrobridge.windows_launcher "$icon_path"

"$dotnet" restore "$solution" -p:EnableWindowsTargeting=true
"$dotnet" restore "$app_project" -r win-x64 -p:EnableWindowsTargeting=true
"$dotnet" test "$test_project" -c Release --no-restore
"$dotnet" publish "$app_project" \
  -c Release \
  -r win-x64 \
  --self-contained true \
  --no-restore \
  -p:EnableWindowsTargeting=true \
  -p:PublishTrimmed=false \
  -p:ApplicationIcon="$icon_path" \
  -o "$output_dir"

test -f "$output_dir/RetroBridge98.Settings.exe"
"$repo_root/host/build-windows-wheel.sh"
echo "Published the self-contained Windows settings application in $output_dir"
