Option Explicit

' Timing-based automation is fragile. Prefer normal installer switches or file
' operations when available. Replace the window title and answers below with
' values that you are entitled to use.

Dim sh, activated, answers, answer
Set sh = CreateObject("WScript.Shell")
answers = Array("YOUR NAME", "YOUR ORGANIZATION", "YOUR LICENSE VALUE")

WScript.Sleep 2500
activated = sh.AppActivate("INSTALLER WINDOW TITLE")
If Not activated Then
  MsgBox "The expected installer window was not found.", 48, "SendKeys stopped"
  WScript.Quit 1
End If

For Each answer In answers
  sh.SendKeys answer & "{ENTER}"
  WScript.Sleep 500
Next
