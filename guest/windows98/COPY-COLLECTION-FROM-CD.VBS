Option Explicit

Const ForReading = 1
Const ForWriting = 2

Dim fso, shell, cdRoot, configPath, sourceRoot, targetRoot
Dim sourceFolder, fileExtension, discId, discIdFile, markerFile, sourceCount
Dim copyErrorNumber, copyErrorDescription, sourceDirectory

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

cdRoot = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(cdRoot, 1) <> "\" Then cdRoot = cdRoot & "\"
configPath = cdRoot & "COLLECT.CFG"

If Not fso.FileExists(configPath) Then
  shell.Popup "COLLECT.CFG was not found on this disc.", 10, _
    "Collection Copy", 16
  WScript.Quit 2
End If

sourceFolder = ReadConfigValue(configPath, "SourceFolder", "FILES")
targetRoot = ReadConfigValue(configPath, "TargetRoot", "")
fileExtension = NormalizeExtension( _
  ReadConfigValue(configPath, "FileExtension", ""))

If targetRoot = "" Or fileExtension = "" Then
  shell.Popup "TargetRoot and FileExtension are required in COLLECT.CFG.", _
    10, "Invalid collection configuration", 16
  WScript.Quit 2
End If
If Len(targetRoot) < 4 Or Mid(targetRoot, 2, 2) <> ":\" Then
  shell.Popup "TargetRoot must be an absolute path below a drive root.", _
    10, "Invalid collection configuration", 16
  WScript.Quit 2
End If
If InStr(1, targetRoot, "..", 0) > 0 Or Not SafeExtension(fileExtension) Or _
    sourceFolder = "" Or InStr(1, sourceFolder, "..", 0) > 0 Or _
    InStr(1, sourceFolder, ":", 0) > 0 Or Left(sourceFolder, 1) = "\" Or _
    Left(sourceFolder, 1) = "/" Then
  shell.Popup "SourceFolder, TargetRoot, or FileExtension is invalid.", _
    10, "Invalid collection configuration", 16
  WScript.Quit 2
End If

sourceRoot = cdRoot & sourceFolder
discId = "DISC"
If fso.FileExists(cdRoot & "DISC.ID") Then
  Set discIdFile = fso.OpenTextFile(cdRoot & "DISC.ID", ForReading)
  If Not discIdFile.AtEndOfStream Then discId = Trim(discIdFile.ReadLine)
  discIdFile.Close
End If
If Not SafeDiscId(discId) Then
  shell.Popup "DISC.ID must contain only letters, numbers, underscore, or dash.", _
    10, "Invalid collection disc", 16
  WScript.Quit 2
End If

If Not fso.FolderExists(sourceRoot) Then
  shell.Popup "The configured source folder was not found on this disc.", _
    10, "Collection Copy", 16
  WScript.Quit 2
End If

sourceCount = CountMatching(sourceRoot, fileExtension)
If sourceCount = 0 Then
  shell.Popup "No ." & fileExtension & " files were found on this disc.", _
    10, "Collection Copy", 16
  WScript.Quit 2
End If

EnsureFolderTree targetRoot
If fso.FileExists(targetRoot & "\" & discId & ".OK") Then
  fso.DeleteFile targetRoot & "\" & discId & ".OK", True
End If

Set sourceDirectory = fso.GetFolder(sourceRoot)
On Error Resume Next
If sourceDirectory.Files.Count > 0 Then
  fso.CopyFile sourceRoot & "\*", targetRoot & "\", True
End If
If sourceDirectory.SubFolders.Count > 0 Then
  fso.CopyFolder sourceRoot & "\*", targetRoot & "\", True
End If
copyErrorNumber = Err.Number
copyErrorDescription = Err.Description
Err.Clear
On Error GoTo 0

If copyErrorNumber <> 0 Then
  WriteMarker targetRoot & "\" & discId & ".FAILED", _
    "Copy failed: " & CStr(copyErrorNumber) & " " & copyErrorDescription
  shell.Popup "Copy failed: " & copyErrorDescription, 10, _
    "Collection Copy", 16
  WScript.Quit 3
End If

If Not VerifyMatchingTree(sourceRoot, targetRoot, fileExtension) Then
  WriteMarker targetRoot & "\" & discId & ".FAILED", _
    "Verification failed after copying " & CStr(sourceCount) & " files."
  shell.Popup "The files were copied, but verification failed.", 10, _
    "Collection Copy", 16
  WScript.Quit 4
End If

markerFile = targetRoot & "\" & discId & ".OK"
If fso.FileExists(targetRoot & "\" & discId & ".FAILED") Then
  fso.DeleteFile targetRoot & "\" & discId & ".FAILED", True
End If
WriteMarker markerFile, _
  "Verified " & CStr(sourceCount) & " ." & fileExtension & _
  " files from " & discId & "." & vbCrLf & "Completed: " & CStr(Now)

shell.Popup "Copied and verified " & CStr(sourceCount) & " ." & _
  fileExtension & " files from " & discId & ".", 10, "Collection Copy", 64
WScript.Quit 0

Sub EnsureFolderTree(folderPath)
  Dim parent
  If fso.FolderExists(folderPath) Then Exit Sub
  parent = fso.GetParentFolderName(folderPath)
  If parent <> "" And Not fso.FolderExists(parent) Then EnsureFolderTree parent
  fso.CreateFolder folderPath
End Sub

Sub WriteMarker(filePath, contents)
  Dim outputFile
  Set outputFile = fso.OpenTextFile(filePath, ForWriting, True)
  outputFile.WriteLine contents
  outputFile.Close
End Sub

Function NormalizeExtension(value)
  value = LCase(Trim(value))
  If Left(value, 1) = "." Then value = Mid(value, 2)
  NormalizeExtension = value
End Function

Function SafeDiscId(value)
  Dim index, character
  SafeDiscId = (value <> "" And Len(value) <= 32)
  For index = 1 To Len(value)
    character = Mid(value, index, 1)
    If InStr(1, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", _
        UCase(character), 0) = 0 Then SafeDiscId = False
  Next
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

Function VerifyMatchingTree(sourcePath, destinationPath, extension)
  Dim source, file, childFolder, destinationFile, childDestination
  VerifyMatchingTree = False
  If Not fso.FolderExists(destinationPath) Then Exit Function
  Set source = fso.GetFolder(sourcePath)
  For Each file In source.Files
    If LCase(fso.GetExtensionName(file.Name)) = extension Then
      destinationFile = destinationPath & "\" & file.Name
      If Not fso.FileExists(destinationFile) Then Exit Function
      If fso.GetFile(destinationFile).Size <> file.Size Then Exit Function
    End If
  Next
  For Each childFolder In source.SubFolders
    childDestination = destinationPath & "\" & childFolder.Name
    If Not VerifyMatchingTree(childFolder.Path, childDestination, extension) Then
      Exit Function
    End If
  Next
  VerifyMatchingTree = True
End Function
