# Native Linux host

RetroBridge's renderer can run on native Linux alongside native Linux 86Box.
WSL remains a build environment: when 86Box runs on Windows, install the renderer
on Windows too. Do not use a copied Windows or macOS Python environment on Linux.

Linux uses the CLI and Private Chromium. The WPF settings application and the
Task Scheduler/LaunchAgent installers remain specific to Windows/macOS. Linux
login autostart is not implemented; the VM launcher below starts the renderer
when needed and stops it when the emulator exits. An already running renderer
is left running.

## Install the renderer

From this checkout, with `uv` installed:

```sh
uv sync --extra dev
uv run pytest
uv build --wheel
uv export --frozen --no-dev --no-emit-project --format requirements-txt \
  --output-file /tmp/retrobridge-runtime-requirements.txt
uv venv --python 3.12 "$HOME/.local/share/retrobridge98/venv"
uv pip install --python "$HOME/.local/share/retrobridge98/venv/bin/python" \
  -r /tmp/retrobridge-runtime-requirements.txt dist/retrobridge98-*.whl
"$HOME/.local/share/retrobridge98/venv/bin/python" -m playwright install chromium
"$HOME/.local/share/retrobridge98/venv/bin/retrobridge" doctor
```

If Chromium reports missing system libraries, install the dependencies indicated
by Playwright for the distribution. Do not change graphics drivers for migration.

State lives in `${XDG_STATE_HOME:-$HOME/.local/state}/RetroBridge98`:
`retrobridge.token`, `pairing/retrobridge.ini`, `runtime.json`, `connection.json`
and `logs/retrobridge.log`. Directories are private (0700), secrets are 0600.
Downloads go to `~/Downloads/RetroBridge98`.

## Migrate an existing VM

1. Shut down the source guest cleanly. Copy the complete VM directory, including
   its disk, configuration and NVRAM, and the matching ROM set. Preserve the
   source and verify the copy before booting it. Use the matching 86Box release.
2. Preserve virtual hardware, MAC address and disk geometry. Keep relative media
   paths valid, or update only the copied configuration. Keep backup configs.
3. Copy the existing host token and matching guest INI into the Linux state
   directory with private permissions. Do not generate a new token for an already
   paired guest, or copy Windows runtime state, startup settings or browser profiles.
4. Run the doctor check, then start the VM using the launcher below. Keep the
   renderer on `127.0.0.1:9866`; 86Box SLiRP exposes it to the guest as
   `10.0.2.2:9866`. No inbound firewall rule or LAN listener is needed.
5. Verify Windows 98, guest software, RetroBridge authentication and a rendered
   page. Eject old installer media after validation and shut the guest down cleanly.

The launcher accepts four explicit paths and locks the VM against duplicate
launches through this script:

```sh
bash host/launch-linux-vm.sh \
  "$HOME/Virtual Machines/86Box/Virtual Machines/My PC" \
  "$HOME/.local/opt/86box-6.0/86Box.AppImage" \
  "$HOME/.local/opt/86box-6.0/roms" \
  "$HOME/.local/share/retrobridge98/venv/bin/retrobridge"
```

Always start that VM through the same launcher; opening its disk in another
86Box process bypasses this script's lock. Shut down from Windows 98's Start
menu before closing the emulator. `Ctrl+End` releases captured input.
Windows and Linux copies become independent after migration; changes do not sync.
