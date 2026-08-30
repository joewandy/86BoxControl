Option Explicit

Dim sh, fso, sourceDir, installer
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

sourceDir = fso.GetParentFolderName(WScript.ScriptFullName)
installer = sourceDir & "\INSTALL.EXE"

If fso.FileExists(installer) Then
  sh.Run Chr(34) & installer & Chr(34), 1, False
Else
  MsgBox "INSTALL.EXE was not found beside this launcher:" & vbCrLf & sourceDir, 48, "Installer not found"
End If
