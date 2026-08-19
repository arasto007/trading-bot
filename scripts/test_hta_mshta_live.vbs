Option Explicit
' Launch live_dashboard.hta briefly and verify RefreshLivePanel wrote boot log.
Dim sh, fso, root, hta, logPath, t0, content
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 8) = "\scripts" Then root = fso.GetParentFolderName(root)
hta = fso.BuildPath(root, "live_dashboard.hta")
logPath = fso.BuildPath(fso.BuildPath(root, "data"), "hta_last_refresh.txt")

If Not fso.FileExists(hta) Then
  WScript.Echo "FAIL|missing hta"
  WScript.Quit 1
End If

If fso.FileExists(logPath) Then fso.DeleteFile logPath, True

On Error Resume Next
sh.Run "taskkill /F /IM mshta.exe", 0, True
WScript.Sleep 500

Dim rootFile, ts
rootFile = fso.BuildPath(fso.BuildPath(root, "data"), "hta_root.txt")
If Not fso.FolderExists(fso.BuildPath(root, "data")) Then fso.CreateFolder fso.BuildPath(root, "data")
Set ts = fso.CreateTextFile(rootFile, True, False)
ts.Write root
ts.Close

sh.Run "mshta.exe """ & hta & """", 1, False
t0 = Timer
Do While Timer - t0 < 15
  WScript.Sleep 500
  If fso.FileExists(logPath) Then Exit Do
Loop

If Not fso.FileExists(logPath) Then
  WScript.Echo "FAIL|no hta_last_refresh.txt after 15s - VBScript did not run"
  sh.Run "taskkill /F /IM mshta.exe", 0, True
  WScript.Quit 1
End If

content = Trim(fso.OpenTextFile(logPath, 1).ReadAll)
If InStr(content, "bytes=") > 0 And InStr(content, "root=") > 0 Then
  WScript.Echo "OK|" & content
  sh.Run "taskkill /F /IM mshta.exe", 0, True
  WScript.Quit 0
Else
  WScript.Echo "FAIL|bad log: " & content
  sh.Run "taskkill /F /IM mshta.exe", 0, True
  WScript.Quit 1
End If
