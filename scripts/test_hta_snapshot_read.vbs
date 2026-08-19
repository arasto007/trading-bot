' Simulates HTA ReadSnapshot + key field parsing for CI/manual verification.
Option Explicit

Dim fso, root, cachePath, out, lines, i, line, ok
Dim hasState, hasUtc, hasAccount, paPf, paAccept

Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 8) = "\scripts" Then root = fso.GetParentFolderName(root)
cachePath = fso.BuildPath(fso.BuildPath(root, "data"), "hta_dashboard_snapshot.txt")

If Not fso.FileExists(cachePath) Then
  WScript.Echo "FAIL|cache missing: " & cachePath
  WScript.Quit 1
End If

out = ReadAll(cachePath)
If Len(Trim(out)) = 0 Then
  WScript.Echo "FAIL|cache empty"
  WScript.Quit 1
End If

lines = Split(Replace(Replace(out, vbCrLf, vbLf), vbCr, vbLf), vbLf)
hasState = False : hasUtc = False : hasAccount = False
paPf = "" : paAccept = ""

For i = 0 To UBound(lines)
  line = Trim(lines(i))
  If Left(line, 6) = "STATE|" Then hasState = True
  If Left(line, 4) = "UTC|" Then hasUtc = True
  If Left(line, 8) = "ACCOUNT|" Then hasAccount = True
  If Left(line, 7) = "ENGINE|" Then
    Dim parts
    parts = Split(line, "|")
    If UBound(parts) >= 7 And UCase(parts(1)) = "PA" Then
      paAccept = Mid(parts(4), 8)
      paPf = Mid(parts(6), 4)
    End If
  End If
Next

ok = hasState And hasUtc And hasAccount And Len(paPf) > 0 And Len(paAccept) > 0
If ok Then
  WScript.Echo "OK|STATE+UTC+ACCOUNT|PA_PF=" & paPf & "|PA_ACCEPT=" & paAccept
  WScript.Quit 0
Else
  WScript.Echo "FAIL|STATE=" & hasState & "|UTC=" & hasUtc & "|ACCOUNT=" & hasAccount & "|PA_PF=" & paPf
  WScript.Quit 1
End If

Function ReadAll(path)
  Dim ts, content
  ReadAll = ""
  On Error Resume Next
  Set ts = fso.OpenTextFile(path, 1, False, 0)
  If Not ts.AtEndOfStream Then ReadAll = ts.ReadAll
  ts.Close
  If Len(ReadAll) > 0 Then Exit Function
  Err.Clear
  Dim stm
  Set stm = CreateObject("ADODB.Stream")
  stm.Type = 2
  stm.Charset = "utf-8"
  stm.Open
  stm.LoadFromFile path
  content = stm.ReadText
  stm.Close
  If Err.Number = 0 Then ReadAll = content
  On Error GoTo 0
End Function
