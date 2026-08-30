Option Explicit

Dim sh, fso, installDir, desktopLink, menuLink, legacyTestLink, enableLink, disableLink, startupLink, answer
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
installDir = "C:\RETROBRIDGE"
desktopLink = sh.SpecialFolders("Desktop") & "\RetroBridge98.lnk"
menuLink = sh.SpecialFolders("Programs") & "\RetroBridge98.lnk"
legacyTestLink = sh.SpecialFolders("Programs") & "\Test RetroBridge98 Connection.lnk"
enableLink = sh.SpecialFolders("Programs") & "\Enable RetroBridge98 at Startup.lnk"
disableLink = sh.SpecialFolders("Programs") & "\Disable RetroBridge98 at Startup.lnk"
startupLink = sh.SpecialFolders("Startup") & "\RetroBridge98.lnk"

answer = MsgBox("Remove RetroBridge98 and its shortcuts?", 36, "RetroBridge98")
If answer <> 6 Then WScript.Quit 0

If fso.FileExists(desktopLink) Then fso.DeleteFile desktopLink, True
If fso.FileExists(menuLink) Then fso.DeleteFile menuLink, True
If fso.FileExists(legacyTestLink) Then fso.DeleteFile legacyTestLink, True
If fso.FileExists(enableLink) Then fso.DeleteFile enableLink, True
If fso.FileExists(disableLink) Then fso.DeleteFile disableLink, True
If fso.FileExists(startupLink) Then fso.DeleteFile startupLink, True

' This script is running from the install directory, so use a short delayed
' command to remove only the directory that belongs to RetroBridge98.
sh.Run "command.com /c ping 127.0.0.1 -n 3 > nul & deltree /y C:\RETROBRIDGE", 0, False
MsgBox "RetroBridge98 shortcuts were removed. Its directory will be removed now.", 64, "RetroBridge98"
