Option Explicit

Dim sh, fso, sourceDir, installDir, programs, desktop, link, drive, candidate, answer, legacyTestLink
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
sourceDir = fso.GetParentFolderName(WScript.ScriptFullName)
installDir = "C:\RETROBRIDGE"
desktop = sh.SpecialFolders("Desktop")
programs = sh.SpecialFolders("Programs")

' Windows 98 can launch an AutoRun script with only its relative filename.
' In that case ScriptFullName does not reliably identify the CD root.  Locate
' the disc by its 8.3-safe payload names as a fallback.
If Not PayloadExists(sourceDir) Then
  sourceDir = ""
  For Each drive In fso.Drives
    If drive.IsReady Then
      candidate = drive.DriveLetter & ":\"
      If PayloadExists(candidate) Then
        sourceDir = candidate
        Exit For
      End If
    End If
  Next
End If

If sourceDir = "" Then
  MsgBox "RB98.EXE or RB98.INI is missing from the RetroBridge disc.", 16, "RetroBridge98"
  WScript.Quit 1
End If

If Not fso.FolderExists(installDir) Then fso.CreateFolder installDir
MakeWritable installDir & "\RETROBRIDGE98.EXE"
MakeWritable installDir & "\RETROBRIDGE.INI"
MakeWritable installDir & "\UNINSTALL.VBS"
MakeWritable installDir & "\AUTOSTRT.VBS"
CopyPayload SourcePath(sourceDir, "RB98.EXE"), installDir & "\RETROBRIDGE98.EXE"
CopyPayload SourcePath(sourceDir, "RB98.INI"), installDir & "\RETROBRIDGE.INI"
CopyPayload SourcePath(sourceDir, "UNINSTAL.VBS"), installDir & "\UNINSTALL.VBS"
CopyPayload SourcePath(sourceDir, "AUTOSTRT.VBS"), installDir & "\AUTOSTRT.VBS"
MakeWritable installDir & "\RETROBRIDGE98.EXE"
MakeWritable installDir & "\RETROBRIDGE.INI"
MakeWritable installDir & "\UNINSTALL.VBS"
MakeWritable installDir & "\AUTOSTRT.VBS"

Set link = sh.CreateShortcut(desktop & "\RetroBridge98.lnk")
link.TargetPath = installDir & "\RETROBRIDGE98.EXE"
link.WorkingDirectory = installDir
link.Description = "Modern web rendered safely on the native host"
link.Save

Set link = sh.CreateShortcut(programs & "\RetroBridge98.lnk")
link.TargetPath = installDir & "\RETROBRIDGE98.EXE"
link.WorkingDirectory = installDir
link.Description = "Modern web rendered safely on the native host"
link.Save

legacyTestLink = programs & "\Test RetroBridge98 Connection.lnk"
If fso.FileExists(legacyTestLink) Then fso.DeleteFile legacyTestLink, True
If fso.FileExists(installDir & "\NETPROBE.EXE") Then fso.DeleteFile installDir & "\NETPROBE.EXE", True
If fso.FileExists(installDir & "\NETWORK.INI") Then fso.DeleteFile installDir & "\NETWORK.INI", True

Set link = sh.CreateShortcut(programs & "\Enable RetroBridge98 at Startup.lnk")
link.TargetPath = "wscript.exe"
link.Arguments = Chr(34) & installDir & "\AUTOSTRT.VBS" & Chr(34) & " enable"
link.WorkingDirectory = installDir
link.Description = "Start RetroBridge98 automatically with Windows"
link.Save

Set link = sh.CreateShortcut(programs & "\Disable RetroBridge98 at Startup.lnk")
link.TargetPath = "wscript.exe"
link.Arguments = Chr(34) & installDir & "\AUTOSTRT.VBS" & Chr(34) & " disable"
link.WorkingDirectory = installDir
link.Description = "Keep RetroBridge98 manual"
link.Save

answer = MsgBox("Start RetroBridge98 automatically when Windows starts?" & vbCrLf & _
                "Choose No to keep launching it manually.", 292, "RetroBridge98 Setup")
If answer = 6 Then
  sh.Run "wscript.exe " & Chr(34) & installDir & "\AUTOSTRT.VBS" & Chr(34) & " enable quiet", 0, True
Else
  sh.Run "wscript.exe " & Chr(34) & installDir & "\AUTOSTRT.VBS" & Chr(34) & " disable quiet", 0, True
End If

MsgBox "RetroBridge98 was installed in C:\RETROBRIDGE.", 64, "RetroBridge98"

Function SourcePath(folder, name)
  If Right(folder, 1) = "\" Then
    SourcePath = folder & name
  Else
    SourcePath = folder & "\" & name
  End If
End Function

Function PayloadExists(folder)
  PayloadExists = False
  If folder = "" Then Exit Function
  PayloadExists = fso.FileExists(SourcePath(folder, "RB98.EXE")) And _
                  fso.FileExists(SourcePath(folder, "RB98.INI"))
End Function

Sub MakeWritable(path)
  Dim file
  If fso.FileExists(path) Then
    Set file = fso.GetFile(path)
    file.Attributes = file.Attributes And Not 1
  End If
End Sub

Sub CopyPayload(source, target)
  Dim failure
  On Error Resume Next
  Err.Clear
  fso.CopyFile source, target, True
  If Err.Number <> 0 Then
    failure = Err.Description
    On Error GoTo 0
    MsgBox "Could not update " & fso.GetFileName(target) & "." & vbCrLf & vbCrLf & _
           "Close RetroBridge98, then run INSTALL.VBS again." & vbCrLf & _
           "Windows reported: " & failure, 16, "RetroBridge98 Setup"
    WScript.Quit 1
  End If
  On Error GoTo 0
End Sub
