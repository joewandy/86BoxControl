# Repository-local agent guidance

These instructions apply to the whole repository.

## Host-specific execution

- On this Windows PC, the canonical checkout is
  `/home/joewandy/Work/git/86BoxControl` in WSL Ubuntu. Do not create or use a
  development copy under `C:\` or `/mnt/c`.
- When working in that WSL checkout from Windows-hosted Codex, keep Codex
  Windows-native for Computer Use but run Git and development commands inside
  Ubuntu. This includes Python environment work, dependency installation,
  tests, builds, generated outputs, and Docker commands. Use a WSL terminal or
  `wsl.exe -d Ubuntu -- bash -lc 'cd /home/joewandy/Work/git/86BoxControl && <command>'`.
- For 86BoxControl and RetroBridge on this Windows PC, keep source, Git,
  Linux Python environments, dependency locking, tests, wheel/guest builds,
  ISO generation, and Docker work in WSL. Install the built RetroBridge wheel
  into a separate native Windows Python 3.12 environment, and keep 86Box, ROMs,
  VM configurations, disks, runtime state, pairing secrets, logs, and downloads
  in native Windows locations.
- Never run native Windows Python directly from the `\\wsl.localhost` or
  `\\wsl$` source tree. Never put the Linux checkout or Linux development
  environment under `/mnt/c`. Crossing the boundary for a built wheel, guest
  ISO, or native Windows runtime asset is intentional; executing a development
  environment from the other filesystem is not.
- The verified native emulator on this PC is 86Box 6.0 under
  `C:\Users\joewa\86Box`; its VM Manager scans
  `C:\Users\joewa\86Box\Virtual Machines`. Keep the active Windows 6.0 VM
  configuration windowed by default. Preserve the adjacent macOS 5.3
  configuration backup as migration evidence.
- Read `docs/WINDOWS-WSL.md` before changing Windows/WSL paths, native host
  installation, 86Box runtime assets, or the RetroBridge login service.
- When working in a native checkout on the MacBook Air, run commands natively
  on macOS. Do not use `wsl.exe` or assume WSL paths there.
- Use dependencies built for the current operating system. Do not execute
  copied macOS environments, binaries, or caches in Linux, or vice versa;
  rebuild what is needed after moving between hosts.
