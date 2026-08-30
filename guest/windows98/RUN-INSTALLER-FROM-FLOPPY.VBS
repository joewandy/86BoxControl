Option Explicit

Dim sh, fso, installer
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
installer = "A:\INSTALL.EXE"

If fso.FileExists(installer) Then
  sh.Run installer, 1, False
Else
  MsgBox "A:\INSTALL.EXE was not found. Check the mounted floppy.", 48, "Installer not found"
End If
