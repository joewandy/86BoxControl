Option Explicit

Const ForReading = 1

Dim sh, fso, desktop, programs, sourceDir, configPath
Dim rules(), ruleCount, moved
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

desktop = sh.SpecialFolders("Desktop")
programs = sh.SpecialFolders("Programs")
sourceDir = fso.GetParentFolderName(WScript.ScriptFullName)
configPath = SourcePath(sourceDir, "CATEGORIES.TXT")
ruleCount = 0
moved = ""

LoadRules configPath
CreateCategoryFolders
MoveDesktopShortcuts
CollectStartMenuShortcuts programs

If moved = "" Then
  MsgBox "Category folders were created, but no matching desktop shortcuts " & _
    "were found.", 64, "Shortcut organization complete"
Else
  MsgBox "Shortcut organization completed." & vbCrLf & vbCrLf & moved, _
    64, "Shortcut organization complete"
End If

Sub LoadRules(path)
  Dim input, line, fields, category, lineNumber
  If Not fso.FileExists(path) Then
    MsgBox "CATEGORIES.TXT was not found beside this script." & vbCrLf & _
      "Copy CATEGORIES.EXAMPLE.TXT to CATEGORIES.TXT and edit it first.", _
      48, "Category configuration missing"
    WScript.Quit 2
  End If

  Set input = fso.OpenTextFile(path, ForReading)
  lineNumber = 0
  Do Until input.AtEndOfStream
    lineNumber = lineNumber + 1
    line = Trim(input.ReadLine)
    If line <> "" And Left(line, 1) <> "#" Then
      fields = Split(line, "|")
      If UBound(fields) < 1 Then InvalidRule lineNumber
      category = Trim(fields(0))
      If Not ValidCategory(category) Then InvalidRule lineNumber
      If ruleCount = 0 Then
        ReDim rules(0)
      Else
        ReDim Preserve rules(ruleCount)
      End If
      rules(ruleCount) = line
      ruleCount = ruleCount + 1
    End If
  Loop
  input.Close

  If ruleCount = 0 Then
    MsgBox "CATEGORIES.TXT contains no category rules.", 48, _
      "No categories configured"
    WScript.Quit 3
  End If
End Sub

Sub InvalidRule(lineNumber)
  MsgBox "Invalid category rule on line " & CStr(lineNumber) & "." & vbCrLf & _
    "Use: Category|keyword|keyword", 16, "Invalid category configuration"
  WScript.Quit 3
End Sub

Function ValidCategory(category)
  Dim invalid, index
  invalid = Array("\", "/", ":", "*", "?", Chr(34), "<", ">")
  ValidCategory = (category <> "")
  For index = 0 To UBound(invalid)
    If InStr(1, category, invalid(index), 0) > 0 Then ValidCategory = False
  Next
End Function

Function CategoryFor(name)
  Dim index, fields, keywordIndex
  CategoryFor = ""
  For index = 0 To ruleCount - 1
    fields = Split(rules(index), "|")
    For keywordIndex = 1 To UBound(fields)
      If Trim(fields(keywordIndex)) <> "" And _
          Contains(name, Trim(fields(keywordIndex))) Then
        CategoryFor = Trim(fields(0))
        Exit Function
      End If
    Next
  Next
End Function

Function Contains(text, fragment)
  Contains = (InStr(1, LCase(text), LCase(fragment), 1) > 0)
End Function

Function IsDesktopLauncher(name)
  Dim extension
  extension = LCase(fso.GetExtensionName(name))
  IsDesktopLauncher = (extension = "lnk" Or extension = "pif" Or _
    extension = "url" Or extension = "bat")
End Function

Function IsLaunchShortcut(name)
  IsLaunchShortcut = Not (Contains(name, "uninstall") Or _
    Contains(name, "readme") Or Contains(name, "help") Or _
    Contains(name, "release notes"))
End Function

Function UniqueDestination(folderPath, fileName)
  Dim candidate, base, extension, number
  candidate = folderPath & "\" & fileName
  If Not fso.FileExists(candidate) Then
    UniqueDestination = candidate
    Exit Function
  End If

  base = fso.GetBaseName(fileName)
  extension = fso.GetExtensionName(fileName)
  number = 1
  Do
    candidate = folderPath & "\" & base & " (Desktop " & number & ")"
    If extension <> "" Then candidate = candidate & "." & extension
    number = number + 1
  Loop While fso.FileExists(candidate)
  UniqueDestination = candidate
End Function

Sub CreateCategoryFolders
  Dim index, fields, category
  For index = 0 To ruleCount - 1
    fields = Split(rules(index), "|")
    category = Trim(fields(0))
    EnsureFolder desktop & "\" & category
    EnsureFolder programs & "\" & category
  Next
End Sub

Sub CollectStartMenuShortcuts(path)
  Dim folder, file, subfolder, category, desktopCopy, menuCopy
  Set folder = fso.GetFolder(path)

  For Each file In folder.Files
    If (LCase(fso.GetExtensionName(file.Name)) = "lnk" Or _
        LCase(fso.GetExtensionName(file.Name)) = "pif") And _
        IsLaunchShortcut(file.Name) Then
      category = CategoryFor(file.Name)
      If category <> "" Then
        desktopCopy = desktop & "\" & category & "\" & file.Name
        menuCopy = programs & "\" & category & "\" & file.Name
        If Not fso.FileExists(desktopCopy) Then
          fso.CopyFile file.Path, desktopCopy, False
        End If
        If LCase(file.Path) <> LCase(menuCopy) And _
            Not fso.FileExists(menuCopy) Then
          fso.CopyFile file.Path, menuCopy, False
        End If
      End If
    End If
  Next

  For Each subfolder In folder.SubFolders
    CollectStartMenuShortcuts subfolder.Path
  Next
End Sub

Sub MoveDesktopShortcuts
  Dim file, sourceList, items, source, category, destination, menuCopy, index
  sourceList = ""

  For Each file In fso.GetFolder(desktop).Files
    If IsDesktopLauncher(file.Name) Then
      category = CategoryFor(file.Name)
      If category <> "" Then sourceList = sourceList & file.Path & vbCrLf
    End If
  Next

  items = Split(sourceList, vbCrLf)
  For index = 0 To UBound(items)
    source = items(index)
    If source <> "" And fso.FileExists(source) Then
      category = CategoryFor(fso.GetFileName(source))
      destination = UniqueDestination(desktop & "\" & category, _
        fso.GetFileName(source))
      menuCopy = programs & "\" & category & "\" & fso.GetFileName(source)
      fso.MoveFile source, destination
      moved = moved & fso.GetFileName(source) & " -> " & category & vbCrLf
      If LCase(fso.GetExtensionName(destination)) <> "bat" And _
          Not fso.FileExists(menuCopy) Then
        fso.CopyFile destination, menuCopy, False
      End If
    End If
  Next
End Sub

Sub EnsureFolder(path)
  If Not fso.FolderExists(path) Then fso.CreateFolder path
End Sub

Function SourcePath(folder, name)
  If Right(folder, 1) = "\" Then
    SourcePath = folder & name
  Else
    SourcePath = folder & "\" & name
  End If
End Function
