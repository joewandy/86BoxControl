# RetroBridge98

RetroBridge98 is a native Windows 98 browser window backed by a disposable
modern Chromium session on a native Windows or macOS host. The guest sends
addresses and input over one authenticated TCP connection; the host renders the
page and streams 640 x 480 RGB565/LZ4 frames back. This is our own client and
service. WRP, Browservice,
Internet Explorer, guest Python, and guest proxy settings are not part of the
runtime.

## What works

- Public HTTP and HTTPS navigation from the address bar (`Ctrl+L` or `F6`).
- Page links, buttons, text fields, scrolling, and single-window popup links.
- Back, Forward, Reload (`F5`), Stop (`Esc`), and a safe local Home page.
- Find Next/Previous (`Ctrl+F`); `Enter` finds next and `Esc` closes Find.
- JavaScript alert, confirm, and prompt dialogs through native Win98 message
  boxes. Prompt replies use an editable, bounded native text field and can be
  accepted or cancelled.
- Copy, Cut, Paste, and Select All. Page clipboard text is copied only between
  Chromium and the Windows 98 clipboard; the host system clipboard is untouched.
- Up to 20 guest-local Favorites stored in `C:\RETROBRIDGE\FAVORITES.INI`.
  The native manager can open, rename, delete, and reorder them; the guest also
  synchronizes the safe public entries into the Home dashboard.
- Downloads saved to the host user's `Downloads/RetroBridge98` inbox. Downloads
  are never opened automatically; names are sanitized, collisions are renamed,
  and the default limit is 100 MiB. A private, bounded history appears both on
  Home and in File > Download History.
- Connection status, page title/address updates, automatic reconnect, and
  Help > Connection Diagnostics. Home reports the guest/renderer versions,
  transport, Favorites, and recent downloads.

The deliberate omissions are tabs, saved Chrome sessions, login/password
integration, uploads, audio, printing, browser extensions, and access to Chrome
internal pages. Do not use the current build for sensitive credentials.

## Safety boundary

- The guest connects to the 86Box SLiRP host alias at `10.0.2.2:9866`. Keep the
  service bound to `127.0.0.1` unless the VM's network mode demonstrably
  requires a different listener.
- Pairing uses a random 128-bit token generated locally. The token, generated
  guest INI, build output, and VM disk are ignored by Git.
- Every guest connection gets a new temporary Chromium profile in a private
  directory. It does not use the normal host browser profile, cookies,
  extensions, or stored credentials. Closing the guest or stopping the service
  terminates the exact owned Chrome process tree and removes the profile.
- Navigation policy accepts only public `http` and `https` URLs. A loopback
  SOCKS guard independently blocks Chrome connections to loopback, private,
  link-local, metadata, and other non-public addresses, including after DNS
  resolution. `chrome://`, `file://`, and similar internal schemes are blocked
  or returned to the safe Home page.
- On macOS, runtime state and pairing secrets are mode `0600` and their parent
  directories are mode `0700`. On Windows, inheritance is removed and access
  is restricted to the current user, SYSTEM, and Administrators. Download
  history is private and bounded to 50 records.
- Browser-level Control/Alt shortcuts are not forwarded, apart from page
  Select All. The guest's navigation shortcuts are handled locally.
- Only one authenticated browser guest is accepted at a time. Frame ACK
  backpressure permits one displayed frame in flight so a slow VM cannot build
  an ever-growing latency queue.

Windows 98 itself remains unpatched. Prefer a guest NIC configuration with no
default gateway or DNS after driver validation so the VM can reach the
same-subnet renderer but cannot browse directly. SLiRP prevents unsolicited
inbound LAN traffic, but it is not a substitute for removing guest Internet
routing.

## Windows development and runtime boundary

On a Windows development PC, the canonical source checkout, Git operations,
Linux Python environment, dependency lock, tests, Docker/MinGW build, and ISO
generation stay in the WSL Linux filesystem. Docker Desktop supplies the WSL
Docker integration. `xorriso` creates ISOs. Do not put the checkout or `.venv`
under `/mnt/c`, and do not run native Windows Python from a `\\wsl.localhost`
source tree.

The verified 86Box 6.0 paths and migration notes for this PC are in
[`WINDOWS-WSL.md`](WINDOWS-WSL.md).

```sh
uv sync --extra dev
uv run playwright install chromium
uv run pytest
host/build-windows-wheel.sh
host/build-retrobridge-guest.sh
```

Install only the built wheel into native Windows Python 3.12 with
`host/install-windows-host.ps1`. Native runtime files live below
`%LOCALAPPDATA%\RetroBridge98`; 86Box, its ROMs, VM configuration, and disks
also remain native Windows assets. Run `retrobridge pair` and
`retrobridge doctor` from that installed environment. Pairing creates
`%LOCALAPPDATA%\RetroBridge98\retrobridge.token` and
`%LOCALAPPDATA%\RetroBridge98\pairing\retrobridge.ini`; by default the INI
uses `10.0.2.2:9866`.

Pass that INI explicitly to the WSL media build:

```sh
host/build-retrobridge-iso.sh \
  --guest-ini /mnt/c/Users/USERNAME/AppData/Local/RetroBridge98/pairing/retrobridge.ini
```

The ISO script refuses to run without an explicit paired INI and writes
ignored binaries, the ISO, and hashes below `output/`. Use
`retrobridge pair --server ADDRESS --port PORT` for a different VM network
endpoint.

The Docker build uses a 32-bit MinGW cross-compiler and links against the
legacy `MSVCRT.DLL` supplied by Windows 98. PE headers target the Windows 4.0
GUI subsystem, and a checker rejects unexpected DLL imports. No compiler,
Python, or modern runtime is installed in the guest. The target Win98 machine
requires a non-null thread-ID pointer in `CreateThread`; do not simplify that
call to the form accepted by newer Windows releases.

## Native-host daily operation

On Windows, use the executable in the installed native environment:

```powershell
$retrobridge = "$env:LOCALAPPDATA\RetroBridge98\venv\Scripts\retrobridge.exe"
& $retrobridge start
& $retrobridge status
& $retrobridge logs --lines 100
& $retrobridge stop
```

The Windows installer also creates **Start > RetroBridge98 > RetroBridge98**.
That shortcut opens a persistent console with the listener, guest endpoint,
download directory, rotating log location, and live connection activity. Stop
it with `Ctrl+C`, then close the console. Installing the shortcut does not
enable the optional login service or otherwise start RetroBridge automatically.

On macOS, run the same commands from the native checkout:

```sh
uv run retrobridge start
uv run retrobridge status
uv run retrobridge logs --lines 100
uv run retrobridge stop
```

`start` refuses to create a second managed instance. `stop` terminates the
active guest session and its isolated Chromium descendants. On Windows, state
and logs are stored under `%LOCALAPPDATA%\RetroBridge98`; on macOS they retain
their existing Library locations. Logs rotate at 5 MiB with three backups.

Opt in to a per-user login service only after normal mode is verified:

```powershell
& $retrobridge autostart install
& $retrobridge autostart status
& $retrobridge autostart remove
```

Use `uv run retrobridge autostart ...` on macOS.

Windows uses the per-user `RetroBridge98 Renderer` Task Scheduler entry; macOS
uses the `com.retrobridge98.renderer` LaunchAgent. Both bind to loopback by
default and use explicit arguments. Changing configuration requires `--force`
so an existing service is not silently replaced. `retrobridge stop` leaves the
opt-in installed but stops the current session. While autostart is installed,
`start` uses its saved normal-mode settings and refuses headed or deterministic
QA modes; temporarily remove autostart before running those modes.

`retrobridge serve` runs in the foreground for development. If SLiRP cannot
reach the default loopback listener, diagnose the VM networking first. The
last-resort `--listen 0.0.0.0` exposes the authenticated listener to other
interfaces and should be used only with an explicit network reason.

Normal headless rendering keeps Chromium's native vertical scrollbar visible
inside the streamed `640x480` viewport. It can be dragged or clicked from the
Windows 98 client; the mouse wheel and Page Up/Page Down remain available too.

In Windows 98, install from the ISO with `INSTALL.VBS` and launch
`C:\RETROBRIDGE\RETROBRIDGE98.EXE` or its installed shortcut.
Close a running RetroBridge98 client before installing an upgrade; the setup
script detects the locked executable and explains how to retry. The client
reconnects automatically when the managed service is restarted. Guest startup
is opt-in and defaults to No during setup. The Start menu contains explicit
Enable and Disable RetroBridge98 at Startup shortcuts; both use
`AUTOSTRT.VBS`, and uninstall removes the Startup shortcut.

Use an `800×600` or larger Windows desktop when practical. The browser transport
remains a fixed `640×480`; the larger guest desktop simply gives that viewport
and its native window controls enough room and reduces aggressive fullscreen
scaling of Windows bitmap text.

## Deterministic QA modes

Run the isolated browser fixture suite without depending on a live website:

```sh
uv run retrobridge stop
uv run retrobridge start --self-test
```

The fixture home exercises normal and popup-target links, text input and form
submission, a bounded download, confirm/prompt dialogs, clipboard operations,
Find, Favorites, Back/Forward, and reconnect behavior. Direct authenticated QA
routes `/dialog`, `/prompt`, and `/download.bin` make the native dialog and
download paths reproducible without coordinate-dependent clicking. The fixture
is available only to an authenticated guest while self-test mode is active;
its synthetic hostname does not resolve through normal egress.

For raw framebuffer performance and long-run ACK testing:

```sh
uv run retrobridge stop
uv run retrobridge start --test-pattern
```

Let the animated pattern run for at least ten minutes. The service logs every
50 acknowledged frames with displayed FPS and average KiB per frame. Confirm at
least 3 FPS, no reconnect, no protocol error, and no visibly growing input
latency or VM slowdown. Return to normal mode with `retrobridge stop` followed
by `retrobridge start`.

The Chrome source frame is 921,600 BGR24 bytes. The negotiated native transport
quantizes it to 614,400 RGB565 bytes and then LZ4-compresses each independent
frame; the deterministic animated pattern is about 21 KiB on the wire. The
service still accepts the raw BGR24 codec requested by older clients. If the
framebuffer gate misses 3 FPS, investigate the measured encode, transfer,
decode, and display stages; do not hide latency by queuing frames.

## Live validation checklist

1. With the VM shut down, configure AMD PCnet-PCI II with SLiRP. Boot and verify
   its Windows 98 driver and same-subnet reachability to `10.0.2.2`.
2. Install the current ISO with `INSTALL.VBS`; keep guest startup disabled for
   the first run, then launch RetroBridge98 and confirm it connects.
3. Run the ten-minute `--test-pattern` gate above.
4. Run `--self-test` and exercise its links, typing, dialog, download, clipboard,
   Find, Favorite, Back/Forward, and service stop/reconnect paths.
5. Run normal mode and test at least two public sites without signing in. Check
   blocked private/internal destinations and verify that downloads appear only
   in the host inbox.
6. Exercise Favorite add/rename/reorder/delete and confirm Home sync, then open
   File > Download History and verify its persisted record.
7. Exit the guest client, stop the service, and confirm no process command line
   contains `retrobridge98-chrome-` or `playwright_chromiumdev_profile`.

## Protocol

Every packet begins with 12 little-endian bytes: `RB98`, version `1`, message
type, and payload length. The maximum payload is 2 MiB. The protocol supports
HELLO/WELCOME, navigation and browser control, pointer and keyboard input,
frame/ACK, status, clipboard, Find, dialog/reply, download notification,
peer/version information, synchronized Favorites, bounded download
history, ping/pong, and structured errors. New messages are capability-gated so
0.2 peers continue using only the original protocol surface. Text is
Windows-1252. The guest negotiates either legacy raw BGR24 or RGB565/LZ4 in
HELLO/WELCOME; each frame header records its codec and uncompressed stride. One
frame may be outstanding, so the service drops stale Chrome frames and waits
for the guest's display acknowledgement.

The canonical Python definitions live in `host/retrobridge/protocol.py`; the C
constants and endian helpers live in
`guest/windows98/retrobridge98/rbproto.h`.
