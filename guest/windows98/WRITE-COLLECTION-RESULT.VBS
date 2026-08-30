Option Explicit

Const ForReading = 1
Const ForWriting = 2

Dim fso, shell, sourceDir, configPath, targetRoot, fileExtension
Dim expectedCountText, expectedCount, markerList, shortcutName
Dim actualCount, markersOk, collectionMarkerOk, shortcutOk, status
Dim desktopPath, resultFile, doneFile, writeErrorNumber

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
sourceDir = fso.GetParentFolderName(WScript.ScriptFullName)
configPath = SourcePath(sourceDir, "COLLECT.CFG")

If Not fso.FileExists(configPath) Then WScript.Quit 2
targetRoot = ReadConfigValue(configPath, "TargetRoot", "")
fileExtension = NormalizeExtension( _
  ReadConfigValue(configPath, "FileExtension", ""))
expectedCountText = ReadConfigValue(configPath, "ExpectedCount", "")
markerList = ReadConfigValue(configPath, "Markers", "")
shortcutName = ReadConfigValue(configPath, "ShortcutName", "")

If targetRoot = "" Or fileExtension = "" Or _
    Not DigitsOnly(expectedCountText) Then WScript.Quit 2
On Error Resume Next
Err.Clear
expectedCount = CLng(expectedCountText)
If Err.Number <> 0 Then
  On Error GoTo 0
  WScript.Quit 2
End If
On Error GoTo 0
If expectedCount < 0 Or Not ValidMarkerList(markerList) Or _
    Not SafeExtension(fileExtension) Or _
    InStr(1, shortcutName, "\", 0) > 0 Then WScript.Quit 2

actualCount = 0
If fso.FolderExists(targetRoot) Then
  actualCount = CountMatching(targetRoot, fileExtension)
End If
markersOk = MarkersPresent(targetRoot, markerList)
collectionMarkerOk = fso.FileExists(targetRoot & "\COLLECTION.OK")

shortcutOk = True
If shortcutName <> "" Then
  desktopPath = shell.SpecialFolders("Desktop")
  shortcutOk = fso.FileExists(desktopPath & "\" & shortcutName)
End If

status = "FAILED"
If actualCount = expectedCount And markersOk And _
    collectionMarkerOk And shortcutOk Then status = "SUCCESS"

On Error Resume Next
Err.Clear
Set resultFile = fso.OpenTextFile("A:\RESULT.TXT", ForWriting, True)
If Err.Number = 0 Then
  resultFile.WriteLine "status=" & status
  resultFile.WriteLine "file_extension=" & fileExtension
  resultFile.WriteLine "file_count=" & CStr(actualCount)
  resultFile.WriteLine "expected_count=" & CStr(expectedCount)
  resultFile.WriteLine "disc_markers=" & LCase(CStr(markersOk))
  resultFile.WriteLine "collection_marker=" & LCase(CStr(collectionMarkerOk))
  resultFile.WriteLine "desktop_shortcut=" & LCase(CStr(shortcutOk))
  resultFile.WriteLine "checked_at=" & CStr(Now)
  resultFile.Close
End If
writeErrorNumber = Err.Number
On Error GoTo 0

If writeErrorNumber = 0 Then
  Set doneFile = fso.OpenTextFile("A:\DONE.OK", ForWriting, True)
  doneFile.WriteLine status
  doneFile.Close
Else
  WScript.Quit 4
End If
WScript.Quit 0

Function SourcePath(folder, name)
  If Right(folder, 1) = "\" Then
    SourcePath = folder & name
  Else
    SourcePath = folder & "\" & name
  End If
End Function

Function NormalizeExtension(value)
  value = LCase(Trim(value))
  If Left(value, 1) = "." Then value = Mid(value, 2)
  NormalizeExtension = value
End Function

Function SafeExtension(value)
  Dim index, character
  SafeExtension = (value <> "" And Len(value) <= 16)
  For index = 1 To Len(value)
    character = Mid(value, index, 1)
    If InStr(1, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", _
        UCase(character), 0) = 0 Then SafeExtension = False
  Next
End Function

Function DigitsOnly(value)
  Dim index, character
  DigitsOnly = (value <> "")
  For index = 1 To Len(value)
    character = Mid(value, index, 1)
    If InStr(1, "0123456789", character, 0) = 0 Then DigitsOnly = False
  Next
End Function

Function ReadConfigValue(path, key, defaultValue)
  Dim input, line, separator, currentKey
  ReadConfigValue = defaultValue
  Set input = fso.OpenTextFile(path, ForReading)
  Do Until input.AtEndOfStream
    line = Trim(input.ReadLine)
    If line <> "" And Left(line, 1) <> "#" Then
      separator = InStr(1, line, "=", 0)
      If separator > 1 Then
        currentKey = Trim(Left(line, separator - 1))
        If LCase(currentKey) = LCase(key) Then
          ReadConfigValue = Trim(Mid(line, separator + 1))
          input.Close
          Exit Function
        End If
      End If
    End If
  Loop
  input.Close
End Function

Function ValidMarkerList(value)
  Dim markers, index, marker
  ValidMarkerList = True
  If Trim(value) = "" Then Exit Function
  markers = Split(value, ";")
  For index = 0 To UBound(markers)
    marker = Trim(markers(index))
    If marker = "" Or InStr(1, marker, "\", 0) > 0 Or _
        InStr(1, marker, "/", 0) > 0 Or InStr(1, marker, ":", 0) > 0 Or _
        InStr(1, marker, "..", 0) > 0 Then ValidMarkerList = False
  Next
End Function

Function MarkersPresent(folderPath, value)
  Dim markers, index, marker
  MarkersPresent = True
  If Trim(value) = "" Then Exit Function
  markers = Split(value, ";")
  For index = 0 To UBound(markers)
    marker = Trim(markers(index))
    If Not fso.FileExists(folderPath & "\" & marker) Then
      MarkersPresent = False
    End If
  Next
End Function

Function CountMatching(folderPath, extension)
  Dim folder, file, childFolder, total
  Set folder = fso.GetFolder(folderPath)
  total = 0
  For Each file In folder.Files
    If LCase(fso.GetExtensionName(file.Name)) = extension Then total = total + 1
  Next
  For Each childFolder In folder.SubFolders
    total = total + CountMatching(childFolder.Path, extension)
  Next
  CountMatching = total
End Function
