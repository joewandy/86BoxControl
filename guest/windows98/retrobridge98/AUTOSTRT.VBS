Option Explicit

Dim sh, fso, startupLink, installDir, action, quiet, link
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
installDir = "C:\RETROBRIDGE"
startupLink = sh.SpecialFolders("Startup") & "\RetroBridge98.lnk"
action = ""
quiet = False
If WScript.Arguments.Count > 0 Then action = LCase(WScript.Arguments(0))
If WScript.Arguments.Count > 1 Then quiet = LCase(WScript.Arguments(1)) = "quiet"

If action = "enable" Then
  Set link = sh.CreateShortcut(startupLink)
  link.TargetPath = installDir & "\RETROBRIDGE98.EXE"
  link.WorkingDirectory = installDir
  link.Description = "Start RetroBridge98 when Windows starts"
  link.Save
  If Not quiet Then MsgBox "RetroBridge98 will start automatically with Windows.", 64, "RetroBridge98"
ElseIf action = "disable" Then
  If fso.FileExists(startupLink) Then fso.DeleteFile startupLink, True
  If Not quiet Then MsgBox "RetroBridge98 automatic startup is disabled.", 64, "RetroBridge98"
Else
  MsgBox "Use AUTOSTRT.VBS enable or AUTOSTRT.VBS disable.", 48, "RetroBridge98"
  WScript.Quit 2
End If
