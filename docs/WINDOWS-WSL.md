# Windows and WSL layout

This repository uses a split development/runtime layout on Joe's Windows PC.

## Canonical locations

- Source, Git history, the locked Linux development environment, tests, Docker
  builds, wheels, guest binaries, and ISO generation live in WSL Ubuntu at
  `/home/joewandy/Work/git/86BoxControl`.
- Native 86Box 6.0 lives at `C:\Users\joewa\86Box`.
- The configured VM directory is `C:\Users\joewa\86Box\Virtual Machines` and
  the current machine is `My PC`.
- Native RetroBridge state, its Python 3.12 environment, WPF settings
  application, settings, dedicated browser profiles, pairing files, logs,
  generated application icon, and login task live below
  `%LOCALAPPDATA%\RetroBridge98`. Its visible launcher is installed per-user at
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\RetroBridge98`.
- Host-side downloads live at `%USERPROFILE%\Downloads\RetroBridge98`.

Do not create a second development checkout under `C:\` or `/mnt/c`. Do not
run native Windows Python from `\\wsl.localhost` or `\\wsl$` source paths.
Cross the filesystem boundary only with built artifacts such as a wheel or
guest ISO.

## Build and install flow

Run development commands in Ubuntu:

```sh
cd /home/joewandy/Work/git/86BoxControl
uv sync --extra dev
host/build-windows-settings.sh
host/build-retrobridge-guest.sh
```

`host/build-windows-settings.sh` runs the Python and .NET tests, publishes the
WPF application self-contained for `win-x64`, and builds the wheel. Install the
wheel and the complete `output/windows-host/settings` directory from native
PowerShell with `host/install-windows-host.ps1`. The installer accepts explicit
physical `-SupportDirectory` and `-StartMenuDirectory` paths for controlled
deployment. Verify the result through `/mnt/c/Users/joewa/AppData/Local` when a
packaged development shell may redirect `%LOCALAPPDATA%`.

Then run `retrobridge pair` and `retrobridge doctor` from the installed native
environment. Pass the resulting native pairing INI explicitly to
`host/build-retrobridge-iso.sh` in WSL. Copy the finished ISO into
`C:\Users\joewa\86Box\Media` before mounting it in the guest.

## 86Box migration notes

The VM originated on macOS with 86Box 5.3 and now runs under native Windows
86Box 6.0 build 9001. The original configuration is preserved beside the VM as
`86box.cfg.mac-5.3.bak`; treat it as a migration reference, not the active
configuration. The Windows 6.0 configuration is the canonical active version
and does not start fullscreen.

The VM Manager is configured through `%LOCALAPPDATA%\86Box\86box_global.cfg`
to scan `C:/Users/joewa/86Box/Virtual Machines/`. Keep the VM, its disk, ROMs,
and runtime state native to Windows. Do not run 86Box directly against assets
inside the WSL filesystem.

## Verified runtime

The optional Windows host service is the per-user Task Scheduler entry
`RetroBridge98 Renderer`. Fresh installations leave it absent or disabled. When
enabled, it binds to `127.0.0.1:9866`; 86Box SLiRP presents that service to the
guest as `10.0.2.2:9866`. The Windows 98 client is installed at
`C:\RETROBRIDGE`, starts at guest login, and authenticates with the paired INI
embedded in the installation ISO.

Keep the loopback listener and other least-privilege defaults.
Do not widen the listener or add a firewall exception merely to work around a
guest configuration problem.

The Start Menu contains **RetroBridge98** and **RetroBridge98 Settings**. The
first opens setup when settings are missing or invalid and otherwise launches
the persistent console. The second always opens setup and status. Creating or
updating either shortcut must not install, enable, or start the optional Task
Scheduler login service.
