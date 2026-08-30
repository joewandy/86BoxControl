#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 --guest-ini PATH [OUTPUT.iso]" >&2
  exit 2
}

guest_ini=
output=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --guest-ini)
      [ "$#" -ge 2 ] || usage
      guest_ini=$2
      shift 2
      ;;
    --help|-h)
      usage
      ;;
    -*)
      usage
      ;;
    *)
      [ -z "$output" ] || usage
      output=$1
      shift
      ;;
  esac
done

[ -n "$guest_ini" ] || usage
repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
output=${output:-"$repo_root/output/retrobridge98.iso"}
mkdir -p "$repo_root/output"
staging=$(mktemp -d "$repo_root/output/.retrobridge-media.XXXXXX")
cleanup() {
  [ ! -d "$staging" ] || rm -rf "$staging"
}
trap cleanup EXIT HUP INT TERM

[ -f "$guest_ini" ] || {
  echo "Pairing INI not found: $guest_ini" >&2
  exit 1
}

if [ "${RETROBRIDGE_REUSE_GUEST_BINARIES:-0}" = 1 ]; then
  [ -f "$repo_root/output/guest/retrobridge98.exe" ] || {
    echo "Guest binary not found: $repo_root/output/guest/retrobridge98.exe" >&2
    exit 1
  }
else
  "$repo_root/host/build-retrobridge-guest.sh"
fi

cp "$repo_root/output/guest/retrobridge98.exe" "$staging/RETROBRIDGE98.EXE"
cp "$guest_ini" "$staging/RETROBRIDGE.INI"
# The short aliases are the installer's canonical payload names.  Keeping the
# long names as well makes the disc understandable when browsed interactively.
cp "$repo_root/output/guest/retrobridge98.exe" "$staging/RB98.EXE"
cp "$guest_ini" "$staging/RB98.INI"
cp "$repo_root/guest/windows98/retrobridge98/INSTALL.VBS" "$staging/INSTALL.VBS"
cp "$repo_root/guest/windows98/retrobridge98/UNINSTALL.VBS" "$staging/UNINSTALL.VBS"
cp "$repo_root/guest/windows98/retrobridge98/UNINSTALL.VBS" "$staging/UNINSTAL.VBS"
cp "$repo_root/guest/windows98/retrobridge98/AUTOSTRT.VBS" "$staging/AUTOSTRT.VBS"
cp "$repo_root/guest/windows98/retrobridge98/AUTORUN.INF" "$staging/AUTORUN.INF"
cp "$repo_root/guest/windows98/retrobridge98/README.TXT" "$staging/README.TXT"

if [ -e "$output" ]; then
  echo "Refusing to overwrite: $output" >&2
  exit 1
fi
"$repo_root/host/build-iso.sh" "$staging" "$output"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$output" > "$output.sha256"
else
  shasum -a 256 "$output" > "$output.sha256"
fi
trap - EXIT HUP INT TERM
cleanup
echo "Created $output and $output.sha256"
