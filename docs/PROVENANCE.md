# Provenance and selection

The source material was generalized from practical DOS and Windows 98 setup,
media-building, and guest-validation work. Personal paths and machine-specific
configuration are intentionally not part of the repository.

## Retained and generalized

- `guest/windows98/CREATE-SHORTCUTS.VBS` turns a user-supplied shortcut manifest
  into verified Windows 98 desktop shortcuts.
- The two `RUN-INSTALLER` scripts consolidate reusable CD/floppy launcher
  patterns.
- `guest/dos/RUNINST.BAT` and the generic launcher template preserve reusable
  DOS command patterns.
- The host scripts formalize the `mtools` and `hdiutil` workflow used to
  extract, rebuild, merge, and package legacy media.
- `codex/sky-86box.mjs` consolidates fresh-state discovery, exact-path file
  selection, toolbar, keyboard, screenshot, and eject patterns for 86Box.

## Deliberately excluded

- Downloaded application archives and extracted commercial program files.
- VM disks, floppy images, generated ISO variants, and artwork.
- One-off scripts containing user names, organizations, or registration values.
- Failed or superseded application-specific launcher variants.
- Destructive cleanup scripts that were specific to one partial installation.
- VM-specific configuration files and absolute paths to the user's virtual hard disk.

The `SENDKEYS-TEMPLATE.VBS` file retains only the generic focus-and-timing technique; all original answers were replaced with explicit placeholders.
