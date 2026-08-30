# 86BoxControl

86BoxControl is a reusable cross-platform toolkit for preparing, installing,
organizing, and validating DOS and Windows 98 software in an
[86Box](https://86box.net/) virtual machine. It also contains RetroBridge98, a
native Windows 98 browser whose pages are rendered by an isolated modern Chromium
process on a native Windows or macOS host.

This is not an 86Box fork or a prebuilt virtual machine. The repository contains
source code, automation, templates, and documentation only. It does not include
commercial software, product keys, registration data, VM disks, installation
media, generated images, content collections, or pairing secrets.

## What is included

| Path | Purpose |
| --- | --- |
| `host/` | Linux/macOS build tools plus the native Windows RetroBridge installer. |
| `guest/windows98/` | Windows Script Host and Autorun templates for installers, shortcuts, organization, file-copy workflows, and guest-written verification receipts. |
| `guest/windows98/retrobridge98/` | Native Win32 RetroBridge98 client, installer, resources, and protocol code. |
| `guest/dos/` | Small DOS installer and application launcher templates. |
| `host/retrobridge/` | Authenticated native renderer, browser controller, network policy, downloads, CLI, and optional Task Scheduler/LaunchAgent support. |
| `codex/` | Optional helpers for operating accessible parts of the 86Box macOS UI from Codex. |
| `docs/` | Detailed RetroBridge, media, provenance, and operating documentation. |
| `tests/` | Host protocol, browser, lifecycle, policy, and integration tests. |
| `toolchain/` | Reproducible 32-bit MinGW container for building the Windows 98 client. |

## Requirements

The general media tools require a POSIX shell plus:

- Linux with `xorriso` or macOS with `hdiutil`;
- [mtools](https://www.gnu.org/software/mtools/) for FAT floppy images;
- 86Box and a separately configured DOS or Windows 98 VM.

Install the command-line dependencies with Homebrew:

```sh
brew install mtools uv
```

RetroBridge98 additionally requires Docker, `uv`, Playwright Chromium, and a
Windows 98 guest with working TCP/IP networking. On a Windows development PC,
Docker Desktop exposes the Docker CLI to WSL; source, tests, and builds stay in
WSL while the built wheel, 86Box, VM assets, and live renderer stay native to
Windows. The documented defaults assume 86Box SLiRP, but pairing can be
configured for another host address. See
[`docs/WINDOWS-WSL.md`](docs/WINDOWS-WSL.md) for the verified Windows 6.0
layout and the exact development/runtime boundary.

Codex Desktop is optional and is needed only for the helpers under `codex/`.

## Get started

```sh
git clone https://github.com/joewandy/86BoxControl.git
cd 86BoxControl
```

Create the locked development environment and install the test browser:

```sh
uv sync --extra dev
uv run playwright install chromium
uv run pytest
```

## RetroBridge98

RetroBridge98 runs a native application inside Windows 98. The guest sends
addresses and input over one authenticated TCP connection. The native host
renders public web pages in a disposable Chromium profile and streams compressed
frames back to the guest. Internet Explorer, WRP, Browservice, guest Python,
and guest proxy settings are not required.

### Build in WSL and install the Windows host

From the repository root:

```sh
host/build-windows-wheel.sh
host/build-retrobridge-guest.sh
```

Install the resulting wheel from native PowerShell. Reading a built wheel from
WSL is supported; running Windows Python against the WSL source tree is not.

```powershell
pwsh -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\joewandy\Work\git\86BoxControl\host\install-windows-host.ps1 `
  -WheelPath \\wsl.localhost\Ubuntu\home\joewandy\Work\git\86BoxControl\output\windows-host\retrobridge98-0.3.0-py3-none-any.whl
$retrobridge = "$env:LOCALAPPDATA\RetroBridge98\venv\Scripts\retrobridge.exe"
& $retrobridge pair
& $retrobridge doctor
```

Build the ISO in WSL using the pairing INI created by the native Windows host:

```sh
host/build-retrobridge-iso.sh \
  --guest-ini /mnt/c/Users/joewandy/AppData/Local/RetroBridge98/pairing/retrobridge.ini
```

This workflow:

1. builds and installs an OS-neutral wheel into native Windows Python 3.12;
2. creates a native host token and matching guest INI with Windows ACLs;
3. verifies that an isolated Chromium session can render a frame;
4. cross-compiles `RETROBRIDGE98.EXE` for Windows 98;
5. creates `output/retrobridge98.iso` and its SHA-256 file.

The default guest configuration connects to `10.0.2.2:9866`, the usual 86Box
SLiRP host alias. For another virtual network, generate the pairing files with
an address reachable from the guest:

```powershell
& $retrobridge pair --server 192.0.2.10 --port 19866
```

Use the actual endpoint for that environment; the values above are only
documentation examples. Start the renderer with the same port. Existing
pairing files are not overwritten unless `--force` is supplied.

### Run the native renderer

```powershell
& $retrobridge start
& $retrobridge status
```

Normal operation uses these commands:

```powershell
& $retrobridge status
& $retrobridge logs --lines 100
& $retrobridge stop
& $retrobridge start
```

By default, the service listens on `127.0.0.1:9866`, keeps rotating logs under
the platform's native per-user data directory, and saves downloads in the
current user's `Downloads/RetroBridge98` directory. Only one authenticated
guest is accepted at a time.

Automatic startup at login is optional and uses Task Scheduler on Windows or a
LaunchAgent on macOS:

```powershell
& $retrobridge autostart install
& $retrobridge autostart status
& $retrobridge autostart remove
```

On macOS, run the same subcommands through `uv run retrobridge` from a native
macOS checkout.

Read [`docs/RETROBRIDGE.md`](docs/RETROBRIDGE.md) before changing listener or
login-service settings.

### Install the Windows 98 client

1. Mount `output/retrobridge98.iso` in the VM's CD-ROM drive.
2. Run `INSTALL.VBS` from the disc.
3. Keep guest startup disabled for the first run.
4. Open the installed RetroBridge98 desktop or Start-menu shortcut.

The default installation directory is `C:\RETROBRIDGE`. Close a running client
before installing an upgrade. Setup includes explicit shortcuts for enabling or
disabling automatic guest startup. A Windows desktop resolution of `800×600`
or higher is recommended so the fixed `640×480` browser viewport and native
window controls fit without enlarging the entire guest desktop excessively.

Common guest controls are:

| Action | Shortcut |
| --- | --- |
| Select the address | `Ctrl+L` or `F6` |
| Reload | `F5` |
| Stop loading | `Esc` |
| Find on page | `Ctrl+F` |
| Back / Forward | `Alt+Left` / `Alt+Right` |

RetroBridge supports public HTTP/HTTPS navigation, links and forms, scrolling,
native alert/confirm/prompt dialogs, Find, a guest-local clipboard, Favorites,
host-side downloads, download history, and reconnection. It intentionally omits
tabs, uploads, audio, printing, saved sessions, browser extensions, and password
integration. Do not enter sensitive credentials through an unpatched vintage
operating system.

### Network model

The guest should be able to reach the renderer without receiving unrestricted
direct Internet access. The exact adapter, address, and routing configuration
depends on the selected 86Box network mode. The host renderer independently
blocks private, loopback, link-local, metadata, and non-HTTP destinations after
DNS resolution. Pairing files, temporary browser profiles, and runtime state
remain local and are ignored by Git.

The complete feature list, configuration guidance, QA modes, protocol, and live
validation checklist are in [`docs/RETROBRIDGE.md`](docs/RETROBRIDGE.md).

## Preparing legacy media

The media scripts refuse to overwrite existing outputs. Keep original images
unchanged and work from copies or extracted directories.

### Extract floppy images

```sh
host/extract-floppies.sh work/extracted \
  originals/disk1.img originals/disk2.img originals/disk3.img
```

Each image is extracted into its own numbered directory and recorded in a
`SHA256SUMS` manifest.

### Merge compatible multi-disc directories

Some installers can read all their files from one directory:

```sh
host/merge-disk-directories.sh work/merged \
  work/extracted/disk01 work/extracted/disk02 work/extracted/disk03
```

The default merge aborts when the same relative filename has different
contents. Review every conflict before using `--keep-first`. Installers that
depend on volume labels, drive A, or real disk changes should remain on separate
floppy images.

### Build an ISO

```sh
host/build-iso.sh work/merged output/installer.iso
```

The result is a hybrid ISO with Joliet filenames suitable for mounting in an
86Box CD-ROM drive.

### Build a FAT floppy image

```sh
host/build-floppy.sh work/floppy output/installer.img 1440 INSTALL
```

Supported capacities are `720`, `1200`, and `1440` KiB. The optional volume
label must be at most 11 characters and contain only letters, numbers,
underscores, or dashes.

## Guest automation templates

The guest scripts are examples and focused workflows, not universal silent
installers:

- `RUN-INSTALLER-FROM-CD.VBS` locates and launches an installer beside the
  script without assuming a fixed CD drive letter.
- `RUN-INSTALLER-FROM-FLOPPY.VBS` validates and launches `A:\INSTALL.EXE`.
- `CREATE-SHORTCUTS.VBS` creates checked desktop shortcuts from a user-supplied
  `SHORTCUTS.TXT` manifest. Copy and edit `SHORTCUTS.EXAMPLE.TXT` first.
- `ORGANIZE-SHORTCUTS.VBS` groups shortcuts using case-insensitive rules from
  `CATEGORIES.TXT`. Copy and edit `CATEGORIES.EXAMPLE.TXT` first.
- `SENDKEYS-TEMPLATE.VBS` demonstrates last-resort keyboard automation. Replace
  every placeholder and expect timing and focus sensitivity.
- `guest/dos/RUNINST.BAT` launches a conventional installer from drive A.
- `guest/dos/launchers/APPLICATION.BAT` is a generic DOS launcher to copy and
  adapt to an installed application's directory and executable.

Windows 98 scripts and text payloads use CRLF line endings. Preserve them when
building vintage media.

For a shortcut disc, copy `AUTORUN.INF`, `CREATE-SHORTCUTS.VBS`, and an edited
copy of `SHORTCUTS.EXAMPLE.TXT` renamed to `SHORTCUTS.TXT` into one staging
directory. For an organizer disc, copy `ORGANIZE-AUTORUN.INF` as
`AUTORUN.INF`, `ORGANIZE-SHORTCUTS.VBS` as `ORGANIZE.VBS`, and an edited
`CATEGORIES.EXAMPLE.TXT` renamed to `CATEGORIES.TXT`. Build either directory
with `host/build-iso.sh`.

Each non-comment shortcut manifest line uses
`Title|Target|Working directory|Arguments|Check file`. Each category rule uses
`Category|keyword|keyword`; the first matching keyword determines the folder.
These plain-text formats avoid requiring JSON, PowerShell, or a newer runtime
inside Windows 98.

## File collection and verification workflow

The repository includes a configurable workflow for copying a collection from
one or more CDs into a Windows 98 directory, validating paths and sizes,
creating completion markers, and returning a guest-written receipt through a
writable FAT floppy when the framebuffer is unavailable.

`COLLECT.CFG` supplies the source folder, target directory, file extension,
expected total, disc markers, and optional shortcut/sample behavior. No content
files or associated applications are included or installed. See
[`docs/COLLECTION-WORKFLOW.md`](docs/COLLECTION-WORKFLOW.md) for the disc
layouts, configuration fields, build commands, and receipt workflow.

## Optional Codex helpers

`codex/sky-86box.mjs` wraps fresh-state discovery, exact-path CD mounting,
toolbar actions, guest keystrokes, screenshots, and media ejection for a Codex
`node_repl` session using `@oai/sky`:

```js
globalThis.sky = globalThis.sky || (await import('@oai/sky')).sky
var ctl = await import('file:///absolute/path/to/codex/sky-86box.mjs')
```

Accessible element indexes in 86Box are transient. Refresh application state
after every menu, dialog, or file-picker transition. Guest framebuffer controls
are generally pixel-only; host menus and guest keyboard input are the dependable
control surfaces. See [`docs/OPERATING-NOTES.md`](docs/OPERATING-NOTES.md).

## Testing

Run the complete host suite with:

```sh
uv run pytest -q
```

Rebuild and validate the Windows 98 executable with:

```sh
host/build-retrobridge-guest.sh
```

Build a separate QA image without overwriting another ISO:

```sh
RETROBRIDGE_REUSE_GUEST_BINARIES=1 \
  host/build-retrobridge-iso.sh output/retrobridge98-qa.iso
shasum -a 256 -c output/retrobridge98-qa.iso.sha256
```

Passing host tests or mounting an image is not proof that installation or
runtime behavior succeeded inside the guest. Confirm the expected executable,
shortcut, receipt, or application behavior in Windows 98.

## Generated and private files

Generated binaries, ISO and floppy images, tokens, pairing INI files, temporary
Chrome profiles, downloads, VM disks, original software, and content collections
do not belong in Git. The normal output paths are ignored, but always inspect
`git status` before committing.

## Documentation

- [`docs/RETROBRIDGE.md`](docs/RETROBRIDGE.md) — RetroBridge architecture,
  setup, operation, QA, and protocol.
- [`docs/COLLECTION-WORKFLOW.md`](docs/COLLECTION-WORKFLOW.md) — configurable
  multi-disc file copy and guest receipt workflow.
- [`docs/OPERATING-NOTES.md`](docs/OPERATING-NOTES.md) — practical 86Box,
  vintage-media, and guest automation lessons.
- [`docs/WINDOWS-WSL.md`](docs/WINDOWS-WSL.md) — canonical WSL development and
  native Windows 86Box/RetroBridge runtime layout.
- [`docs/PROVENANCE.md`](docs/PROVENANCE.md) — what was generalized into this
  repository and what was deliberately excluded.

## License

The original source code, scripts, and documentation in this repository are
licensed under the [MIT License](LICENSE), copyright (c) 2026 Joe Wandy.
Third-party software, media, trademarks, and 86Box itself remain subject to
their respective owners and licenses.
