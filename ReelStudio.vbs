' Reel Studio launcher
'  1. starts the backend silently (pythonw, no console window) if it is not already up
'  2. waits for the port
'  3. opens a chromeless app window with its own browser profile, so it behaves like a desktop app
Option Explicit

Dim sh, fso, dir, base, i, browser, profile, pw, c, cands

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir  = fso.GetParentFolderName(WScript.ScriptFullName)
base = "http://127.0.0.1:8787/"

Function IsUp(url)
  Dim req
  IsUp = False
  On Error Resume Next
  Set req = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  req.setTimeouts 1000, 1000, 1000, 2000
  req.open "GET", url, False
  req.send
  If Err.Number = 0 Then
    If req.status = 200 Then IsUp = True
  End If
  Err.Clear
  On Error GoTo 0
End Function

Function FindPythonW()
  Dim tools, sub_
  FindPythonW = ""
  tools = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\hermes\tools"
  If fso.FolderExists(tools) Then
    For Each sub_ In fso.GetFolder(tools).SubFolders
      If LCase(Left(sub_.Name, 7)) = "python-" Then
        If fso.FileExists(sub_.Path & "\pythonw.exe") Then
          FindPythonW = sub_.Path & "\pythonw.exe"
          Exit Function
        End If
      End If
    Next
  End If
  tools = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
  If fso.FolderExists(tools) Then
    For Each sub_ In fso.GetFolder(tools).SubFolders
      If fso.FileExists(sub_.Path & "\pythonw.exe") Then
        FindPythonW = sub_.Path & "\pythonw.exe"
        Exit Function
      End If
    Next
  End If
End Function

' ---------------------------------------------------------------- backend
If Not IsUp(base) Then
  pw = FindPythonW()
  sh.CurrentDirectory = dir
  If pw <> "" Then
    sh.Run """" & pw & """ """ & dir & "\server.py"" --no-browser", 0, False
  Else
    sh.Run "cmd /c start """" /min python """ & dir & "\server.py"" --no-browser", 0, False
  End If
  For i = 1 To 80
    WScript.Sleep 250
    If IsUp(base) Then Exit For
  Next
End If

If Not IsUp(base) Then
  MsgBox "Reel Studio backend did not start." & vbCrLf & vbCrLf & _
         "Open a terminal in:" & vbCrLf & dir & vbCrLf & vbCrLf & _
         "and run:  python server.py" & vbCrLf & _
         "to see the error.", 16, "Reel Studio"
  WScript.Quit 1
End If

' ---------------------------------------------------------------- app window
profile = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\ReelStudio\browser"
browser = ""
cands = Array( _
  "C:\Program Files\Google\Chrome\Application\chrome.exe", _
  "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", _
  sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Microsoft\Edge\Application\msedge.exe", _
  "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", _
  sh.ExpandEnvironmentStrings("%ProgramFiles%") & "\Microsoft\Edge\Application\msedge.exe")
For Each c In cands
  If fso.FileExists(c) Then
    browser = c
    Exit For
  End If
Next

If browser = "" Then
  sh.Run base, 1, False
Else
  sh.Run """" & browser & """ --app=" & base & " --user-data-dir=""" & profile & _
        """ --window-size=1500,960 --no-first-run --no-default-browser-check", 1, False
End If
