Option Explicit
Dim fso, sc, block, htaPath, text, start, endPos, marker
Set fso = CreateObject("Scripting.FileSystemObject")
htaPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "..\live_dashboard.hta")
If Right(WScript.ScriptFullName, 8) = "\scripts" Then
  htaPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "live_dashboard.hta")
End If
text = fso.OpenTextFile(htaPath, 1).ReadAll
marker = "<script language=""VBScript"">"
start = InStr(1, text, marker, vbTextCompare)
If start = 0 Then
  WScript.Echo "FAIL|no script marker"
  WScript.Quit 1
End If
start = start + Len(marker)
endPos = InStr(start, text, "</script>", vbTextCompare)
block = Mid(text, start, endPos - start)
On Error Resume Next
Set sc = CreateObject("ScriptControl")
sc.Language = "VBScript"
sc.AddCode block
If Err.Number <> 0 Then
  WScript.Echo "FAIL|line? " & Err.Description
  WScript.Quit 1
End If
WScript.Echo "OK|bytes=" & Len(block)
WScript.Quit 0
