Option Explicit

Const ForReading = 1
Const ForWriting = 2

Dim fso, shell, sourceDir, configPath, targetRoot, fileExtension
Dim expectedCountText, expectedCount, markerList, shortcutName
Dim description, sampleRelativePath, actualCount, markersOk
Dim verificationMessage, markerFile, desktopPath, shortcut, sampleFile

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
sourceDir = fso.GetParentFolderName(WScript.ScriptFullName)
configPath = SourcePath(sourceDir, "COLLECT.CFG")

If Not fso.FileExists(configPath) Then
  shell.Popup "COLLECT.CFG was not found beside this script.", 10, _
    "Collection Verification", 16
  WScript.Quit 2
End If

targetRoot = ReadConfigValue(configPath, "TargetRoot", "")
fileExtension = NormalizeExtension( _
  ReadConfigValue(configPath, "FileExtension", ""))
expectedCountText = ReadConfigValue(configPath, "ExpectedCount", "")
markerList = ReadConfigValue(configPath, "Markers", "")
shortcutName = ReadConfigValue(configPath, "ShortcutName", "")
description = ReadConfigValue(configPath, "CollectionDescription", _
  "Offline file collection")
sampleRelativePath = ReadConfigValue(configPath, "SampleRelativePath", "")

If targetRoot = "" Or fileExtension = "" Or _
    Not DigitsOnly(expectedCountText) Then InvalidConfiguration
On Error Resume Next
Err.Clear
expectedCount = CLng(expectedCountText)
If Err.Number <> 0 Then
  On Error GoTo 0
  InvalidConfiguration
End If
On Error GoTo 0
If expectedCount < 0 Then InvalidConfiguration
If Not ValidMarkerList(markerList) Then InvalidConfiguration
If InStr(1, shortcutName, "\", 0) > 0 Then InvalidConfiguration
If InStr(1, sampleRelativePath, "..", 0) > 0 Or _
    InStr(1, sampleRelativePath, ":", 0) > 0 Then InvalidConfiguration
If Not SafeExtension(fileExtension) Then InvalidConfiguration

If Not fso.FolderExists(targetRoot) Then
  shell.Popup "The configured collection directory does not exist.", 20, _
    "Collection Verification", 16
  WScript.Quit 2
End If

markersOk = MarkersPresent(targetRoot, markerList)
actualCount = CountMatching(targetRoot, fileExtension)
If (Not markersOk) Or actualCount <> expectedCount Then
  verificationMessage = "Verification failed." & vbCrLf & _
    "Expected files: " & CStr(expectedCount) & vbCrLf & _
    "Found files: " & CStr(actualCount) & vbCrLf & _
    "Configured markers present: " & CStr(markersOk)
  If fso.FileExists(targetRoot & "\COLLECTION.OK") Then
    fso.DeleteFile targetRoot & "\COLLECTION.OK", True
  End If
  WriteMarker targetRoot & "\COLLECTION.FAILED", verificationMessage
  shell.Popup verificationMessage, 30, "Collection Verification", 16
  WScript.Quit 3
End If

verificationMessage = "Verified " & CStr(expectedCount) & " ." & _
  fileExtension & " files and all configured markers." & vbCrLf & _
  "Location: " & targetRoot & vbCrLf & "Completed: " & CStr(Now)
markerFile = targetRoot & "\COLLECTION.OK"
If fso.FileExists(targetRoot & "\COLLECTION.FAILED") Then
  fso.DeleteFile targetRoot & "\COLLECTION.FAILED", True
End If
WriteMarker markerFile, verificationMessage

If shortcutName <> "" Then
  desktopPath = shell.SpecialFolders("Desktop")
  Set shortcut = shell.CreateShortcut(desktopPath & "\" & shortcutName)
  shortcut.TargetPath = targetRoot
  shortcut.WorkingDirectory = targetRoot
  shortcut.Description = description
  shortcut.IconLocation = "C:\WINDOWS\EXPLORER.EXE,0"
  shortcut.Save
End If

shell.Popup verificationMessage, 30, "Collection Verification", 64
If sampleRelativePath <> "" Then
  sampleFile = targetRoot & "\" & sampleRelativePath
  If fso.FileExists(sampleFile) Then
    shell.Run Chr(34) & sampleFile & Chr(34), 1, False
  End If
End If
WScript.Quit 0

Sub InvalidConfiguration
  shell.Popup "COLLECT.CFG contains an invalid or missing value.", 10, _
    "Invalid collection configuration", 16
  WScript.Quit 2
End Sub

Sub WriteMarker(filePath, contents)
  Dim outputFile
  Set outputFile = fso.OpenTextFile(filePath, ForWriting, True)
  outputFile.WriteLine contents
  outputFile.Close
End Sub

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
