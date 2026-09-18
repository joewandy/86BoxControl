#!/usr/bin/env bash
# Run an existing native Linux VM with RetroBridge, without changing its hardware.
set -euo pipefail

if [[ $# != 4 ]]; then
    echo "Usage: $0 VM_DIRECTORY 86BOX_EXECUTABLE ROM_DIRECTORY RETROBRIDGE_EXECUTABLE" >&2
    exit 2
fi
vm=$(realpath -- "$1")
emulator=$(realpath -- "$2")
roms=$(realpath -- "$3")
bridge=$(realpath -- "$4")
[[ -f "$vm/86box.cfg" && -d "$roms" && -x "$emulator" && -x "$bridge" ]]

# Hold this lock in the launcher until 86Box exits. Never open the same disk twice.
exec 9>"$vm/.linux-launch.lock"
if ! flock -n 9; then
    echo "This VM is already running through the Linux launcher." >&2
    exit 1
fi

owned_bridge=0
cleanup() {
    if [[ $owned_bridge == 1 ]]; then
        "$bridge" stop || true
    fi
}
trap cleanup EXIT

# Leave an independently started renderer running after this VM exits.
if ! "$bridge" status --json | python3 -c \
    'import json,sys; sys.exit(0 if json.load(sys.stdin)["running"] else 1)'; then
    "$bridge" start 9>&-
    owned_bridge=1
fi

"$emulator" -P "$vm" -R "$roms" -V "$(basename "$vm")" "$vm/86box.cfg" 9>&-
