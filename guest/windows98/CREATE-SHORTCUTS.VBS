Option Explicit

Const ForReading = 1

Dim sh, fso, desktop, sourceDir, configPath
Dim input, line, fields, lineNumber, made, missing, invalid
Dim definitions(), definitionCount, index
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

desktop = sh.SpecialFolders("Desktop")
sourceDir = fso.GetParentFolderName(WScript.ScriptFullName)
configPath = SourcePath(sourceDir, "SHORTCUTS.TXT")
made = ""
missing = ""
invalid = ""
lineNumber = 0
definitionCount = 0

If Not fso.FileExists(configPath) Then
  MsgBox "SHORTCUTS.TXT was not found beside this script." & vbCrLf & _
    "Copy SHORTCUTS.EXAMPLE.TXT to SHORTCUTS.TXT and edit it first.", _
    48, "Shortcut configuration missing"
  WScript.Quit 2
End If

Set input = fso.OpenTextFile(configPath, ForReading)
Do Until input.AtEndOfStream
  lineNumber = lineNumber + 1
  line = Trim(input.ReadLine)
  If line <> "" And Left(line, 1) <> "#" Then
    fields = Split(line, "|")
    If UBound(fields) <> 4 Then
      invalid = invalid & "Line " & CStr(lineNumber) & vbCrLf
    ElseIf Trim(fields(0)) = "" Or Trim(fields(1)) = "" Or _
        Trim(fields(4)) = "" Then
      invalid = invalid & "Line " & CStr(lineNumber) & vbCrLf
    Else
      If definitionCount = 0 Then
        ReDim definitions(0)
      Else
        ReDim Preserve definitions(definitionCount)
      End If
      definitions(definitionCount) = line
      definitionCount = definitionCount + 1
    End If
  End If
Loop
input.Close

If invalid <> "" Then
  MsgBox "These lines do not contain five pipe-separated fields:" & vbCrLf & _
    invalid, 16, "Invalid shortcut configuration"
  WScript.Quit 3
End If

If definitionCount = 0 Then
  MsgBox "SHORTCUTS.TXT contains no shortcut definitions.", 48, _
    "No shortcuts configured"
  WScript.Quit 4
End If

For index = 0 To definitionCount - 1
  fields = Split(definitions(index), "|")
  AddShortcut Trim(fields(0)), Trim(fields(1)), Trim(fields(2)), _
    Trim(fields(3)), Trim(fields(4))
Next

If missing = "" Then
  MsgBox "Verified and added these desktop shortcuts:" & vbCrLf & vbCrLf & _
    made, 64, "Shortcuts ready"
Else
  MsgBox "Desktop shortcuts created:" & vbCrLf & made & vbCrLf & _
    "Files not found:" & vbCrLf & missing, 48, "Shortcut check"
End If

Sub AddShortcut(title, target, workDir, arguments, checkFile)
  Dim link
  If fso.FileExists(checkFile) Then
    Set link = sh.CreateShortcut(desktop & "\" & title & ".lnk")
    link.TargetPath = target
    If workDir <> "" Then link.WorkingDirectory = workDir
    If arguments <> "" Then link.Arguments = arguments
    link.Description = title
    link.Save
    made = made & title & vbCrLf
  Else
    missing = missing & checkFile & vbCrLf
  End If
End Sub

Function SourcePath(folder, name)
  If Right(folder, 1) = "\" Then
    SourcePath = folder & name
  Else
    SourcePath = folder & "\" & name
  End If
End Function
