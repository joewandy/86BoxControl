# Operating notes

These are the parts of the Windows 98/DOS setup that were broadly reusable.

## 86Box UI control from Codex

The original notes below describe the macOS migration source. On the current
Windows PC, keep Codex and Computer Use native to Windows, target the exact
86Box guest window returned by fresh application discovery, and refresh window
state after every menu or dialog transition. The emulated framebuffer remains
pixel-only even though 86Box's host menus and toolbar are accessible.

86Box 6.0 releases mouse capture with `Ctrl+End` or the middle mouse button. If
synthetic guest keystrokes are ignored at early Win98 startup, temporarily turn
on **Action > Keyboard requires capture**, capture the guest, send the key, and
restore the original preference after the desktop appears. Keep fullscreen off
by default. See [`WINDOWS-WSL.md`](WINDOWS-WSL.md) for the canonical Windows
paths and host/runtime split.

### Historical macOS notes

- The Windows guest framebuffer is effectively pixel-only to macOS accessibility. Host menus, toolbar buttons, and native file pickers are accessible; guest controls usually are not.
- Keyboard input is the dependable guest-control path: `Return`, `Tab`, `Shift+Tab`, arrows, `Escape`, and installer accelerators.
- Refresh `sky.get_app_state()` after every menu, dialog, or picker transition. Accessible element indexes change and stale indexes can select the wrong image.
- Use the macOS file picker's **Go to Folder** shortcut (`super+shift+g`) and an absolute path. This was much more reliable than navigating a long file list.
- Coordinate clicks were not implemented in the observed 86Box accessibility path. Use accessible host elements and guest keystrokes.
- The 86Box toolbar exposes useful accessible buttons including Pause, hard reset, ACPI shutdown, Ctrl+Alt+Del, Ctrl+Alt+Esc, and Settings. Hard reset should be a last resort because Windows 98 will often run ScanDisk after an unclean reset.
- A mounted image is not proof of a completed installation. Look for a guest completion screen and verify the installed executable or resulting shortcut.

## Media preparation

- Keep original disk images unchanged. Extract to per-disk directories and record hashes.
- Multi-disk installers often reuse filenames such as `INSTALL.EXE`, `DISK.ID`, or setup data files. Never flatten disks with unconditional overwrite.
- If a merged CD starts the wrong utility, compare duplicate filenames. A later
  disc can contain an unrelated `INSTALL.EXE`; preserving the first disc's
  installer is often the correct resolution.
- Some installers genuinely require disk swaps, disk labels, or drive A. In those cases rebuild labeled floppy images instead of forcing a merged CD.
- Eject installation media after setup so an accidental reboot cannot return to an installer or boot floppy.

## Windows 98 guest automation

- `WScript.Shell.CreateShortcut` works well for verified desktop launchers. Set `TargetPath` and `WorkingDirectory`; use `Arguments` when opening a persistent DOS prompt.
- Test the executable with `FileSystemObject.FileExists` before creating the shortcut. A visible shortcut alone is otherwise weak verification.
- Prefer a launcher that derives its CD directory from `WScript.ScriptFullName`; do not assume the CD is always drive D.
- `GetParentFolderName` may return a drive root with a trailing backslash. Add
  one only when it is missing; appending `\FILES` to `D:\` must not produce
  `D:\\FILES`.
- `SendKeys` is timing- and focus-sensitive. Use it only as a last-resort template and stop if the expected window cannot be activated.
- Avoid hiding errors globally with `On Error Resume Next`; it can make an installation look successful while a property or copy step silently failed.
- Windows 98 Autorun handling is inconsistent for scripts with arguments. If Autorun does not fire, launch the `.VBS` file explicitly from the CD.
- When the framebuffer is unavailable, a guest script can write a small result file to a writable FAT floppy image. Eject the image before inspecting it with `mtools`; the guest-written receipt is stronger evidence than CD activity or a mounted-media state.

## Sound and final state

- Muting macOS output is the broadest way to suppress both emulated-PC beeps and Windows restart sounds. Guest mixer settings alone may not cover every beep.
- Leave the VM running only when requested. Before handoff, check that it is not paused and that floppy/CD drives are empty unless media is intentionally needed.
