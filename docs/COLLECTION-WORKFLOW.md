# Windows 98 file collection workflow

This configurable workflow copies files from one or more ISO images into a
chosen Windows 98 directory, verifies each source file by relative path and
size, checks the completed collection, and can return a guest-written result
through a writable FAT floppy image.

The repository contains only automation and an example configuration. Do not
commit content files, generated ISOs, result floppies, or VM disks.

## Configure the collection

Copy `guest/windows98/COLLECTION.EXAMPLE.CFG` to `COLLECT.CFG` in each staging
directory and edit these values:

| Key | Meaning |
| --- | --- |
| `SourceFolder` | Directory on each copy disc that contains the files. |
| `TargetRoot` | Absolute destination below a Windows drive root. |
| `FileExtension` | Extension to count and verify, without a leading dot. |
| `ExpectedCount` | Total matching files expected after all discs are copied. |
| `Markers` | Semicolon-separated `.OK` files required for final verification. May be empty. |
| `ShortcutName` | Optional desktop shortcut filename, including `.lnk`. May be empty. |
| `CollectionDescription` | Description stored in the optional shortcut. |
| `SampleRelativePath` | Optional file below `TargetRoot` to open after successful verification. |

Use ASCII text and CRLF line endings. Values cannot contain line breaks. Marker
names must be plain filenames, and `SampleRelativePath` must remain below the
configured target directory.

## Build copy discs

Prepare one staging directory per disc:

```text
copy-disc/
├── AUTORUN.INF   # guest/windows98/COLLECTION-AUTORUN.INF
├── COPYCOLL.VBS  # guest/windows98/COPY-COLLECTION-FROM-CD.VBS
├── COLLECT.CFG   # edited collection configuration
├── DISC.ID       # short marker base, for example DISC_1
└── FILES/        # name must match SourceFolder
    └── ...
```

Use a different `DISC.ID` on every disc. It may contain only letters, numbers,
underscores, and dashes. A disc ID of `DISC_1` creates `DISC_1.OK` after the
copy and byte-size verification succeed, or `DISC_1.FAILED` after a failure.
List every expected `.OK` filename in the `Markers` configuration used by the
final verifier.

Build each ISO with a distinct output name:

```sh
host/build-iso.sh copy-disc output/COLLECTION_DISC_1.iso
```

Mount and complete each disc separately. A mounted image is not evidence that
the copy finished; wait for the guest completion message or use the final
verification disc.

## Build a verification disc

```text
verify-disc/
├── AUTORUN.INF  # guest/windows98/COLLECTION-VERIFY-AUTORUN.INF
├── VERIFY.VBS   # guest/windows98/VERIFY-COLLECTION.VBS
└── COLLECT.CFG  # same completed-collection configuration
```

Build and mount it:

```sh
host/build-iso.sh verify-disc output/VERIFY_COLLECTION.iso
```

The verifier counts matching files recursively, checks every configured disc
marker, writes `COLLECTION.OK` or `COLLECTION.FAILED`, and optionally creates a
desktop shortcut and opens a sample file. It does not install or change an
application associated with the file type.

## Return a result through a floppy image

This is useful when the guest framebuffer cannot be inspected. Create an empty
1.44 MB FAT12 image:

```sh
mkdir -p output
truncate -s 1474560 output/COLLECTION_RESULT.img
mformat -i output/COLLECTION_RESULT.img -f 1440 -v RESULT ::
```

Mount it in guest drive A as writable media. Then build a result CD:

```text
result-disc/
├── AUTORUN.INF  # guest/windows98/COLLECTION-RESULT-AUTORUN.INF
├── RESULT.VBS   # guest/windows98/WRITE-COLLECTION-RESULT.VBS
└── COLLECT.CFG  # same completed-collection configuration
```

```sh
host/build-iso.sh result-disc output/COLLECTION_RESULT.iso
```

After the floppy image stops changing, eject it from 86Box before reading it:

```sh
mdir -i output/COLLECTION_RESULT.img ::
mtype -i output/COLLECTION_RESULT.img ::RESULT.TXT
mtype -i output/COLLECTION_RESULT.img ::DONE.OK
```

`status=SUCCESS` requires the configured file count, every configured marker,
`COLLECTION.OK`, and the optional desktop shortcut when one was requested. The
receipt verifies guest filesystem state; application behavior still requires a
separate runtime check.
