Option Explicit
' End-to-end: root file + cache + parse (same rules as live_dashboard.hta)
Dim fso, root, rootFile, cachePath, out, lines, i, line, ok
Dim hasUtc, hasAccount, hasState, paPf

Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If Right(root, 8) = "\scripts" Then root = fso.GetParentFolderName(root)

rootFile = fso.BuildPath(fso.BuildPath(root, "data"), "hta_root.txt")
cachePath = fso.BuildPath(fso.BuildPath(root, "data"), "hta_dashboard_snapshot.txt")

If Not fso.FileExists(rootFile) Then
  Dim ts
  Set ts = fso.CreateTextFile(rootFile, True, False)
  ts.Write root
  ts.Close
End If

If Not fso.FileExists(cachePath) Then
  WScript.Echo "FAIL|no cache - run status_snapshot.py first"
  WScript.Quit 1
End If

out = fso.OpenTextFile(cachePath, 1, False, 0).ReadAll
lines = Split(Replace(Replace(out, vbCrLf, vbLf), vbCr, vbLf), vbLf)
hasUtc = False : hasAccount = False : hasState = False : paPf = ""
ok = False

For i = 0 To UBound(lines)
  line = Trim(lines(i))
  If InStr(line, "STATE|") = 1 Then hasState = True
  If InStr(line, "UTC|") = 1 Then hasUtc = True
  If InStr(line, "ACCOUNT|") = 1 Then hasAccount = True
  If InStr(line, "ENGINE|") = 1 Then
    Dim parts
    parts = Split(line, "|")
    If UBound(parts) >= 7 And UCase(parts(1)) = "PA" Then paPf = parts(6)
  End If
Next

ok = hasState And hasUtc And hasAccount And Len(out) > 100
If ok Then
  WScript.Echo "OK|bytes=" & Len(out) & "|UTC=" & hasUtc & "|ACCOUNT=" & hasAccount & "|PA_PF=" & paPf
  WScript.Quit 0
Else
  WScript.Echo "FAIL|bytes=" & Len(out) & "|STATE=" & hasState & "|UTC=" & hasUtc & "|ACCOUNT=" & hasAccount
  WScript.Quit 1
End If
