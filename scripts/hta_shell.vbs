Option Explicit
Dim gBusy
Dim gBooted
Dim gRoot

Function DecodePathPart(s)
  DecodePathPart = Replace(Replace(Replace(s, "%20", " "), "%25", "%"), "%5C", "\")
End Function

Function ProjectRoot()
  If Len(gRoot) > 0 Then
    ProjectRoot = gRoot
    Exit Function
  End If
  Dim fso, rootFile, cached, href, htaDir
  Set fso = CreateObject("Scripting.FileSystemObject")
  href = DecodePathPart(document.location.href)
  href = Replace(Replace(Replace(href, "file:///", ""), "file://", ""), "/", "\")
  If Len(href) >= 3 And Left(href, 1) = "\" And Mid(href, 3, 1) = ":" Then href = Mid(href, 2)
  If fso.FileExists(href) Then
    htaDir = fso.GetParentFolderName(fso.GetAbsolutePathName(href))
  Else
    htaDir = fso.GetParentFolderName(href)
  End If
  rootFile = fso.BuildPath(fso.BuildPath(htaDir, "data"), "hta_root.txt")
  If fso.FileExists(rootFile) Then
    cached = Trim(fso.OpenTextFile(rootFile, 1).ReadAll)
    If Len(cached) > 0 And fso.FolderExists(cached) Then
      gRoot = fso.GetAbsolutePathName(cached)
      ProjectRoot = gRoot
      Exit Function
    End If
  End If
  gRoot = htaDir
  ProjectRoot = gRoot
End Function

Function ReadUtcFromCache()
  Dim fso, p, ts, txt, lines, i, line, root
  ReadUtcFromCache = "-"
  root = ProjectRoot()
  Set fso = CreateObject("Scripting.FileSystemObject")
  p = fso.BuildPath(fso.BuildPath(root, "data"), "hta_dashboard_snapshot.txt")
  If Not fso.FileExists(p) Then Exit Function
  On Error Resume Next
  Set ts = fso.OpenTextFile(p, 1, False, 0)
  txt = ts.ReadAll
  ts.Close
  lines = Split(Replace(Replace(txt, vbCrLf, vbLf), vbCr, vbLf), vbLf)
  For i = 0 To UBound(lines)
    line = Trim(lines(i))
    If Len(line) >= 5 Then
      If Left(line, 4) = "UTC|" Then
        ReadUtcFromCache = Mid(line, 5)
        Exit Function
      End If
    End If
  Next
  On Error GoTo 0
End Function

Sub SetStatus(msg)
  Dim el
  Set el = document.getElementById("status")
  If Not el Is Nothing Then
    el.innerText = msg
  End If
  document.title = "TradingBot v9.1.0 | " & msg
End Sub

Sub ReloadFrame
  Dim fr, tick
  Set fr = document.getElementById("liveframe")
  If fr Is Nothing Then Exit Sub
  tick = Replace(CStr(Timer), ".", "")
  fr.src = "data/dashboard_live.html?t=" & tick
End Sub

Sub RunSnapshotAsync
  Dim fso, sh, root, bat, cmd
  Set fso = CreateObject("Scripting.FileSystemObject")
  Set sh = CreateObject("WScript.Shell")
  root = ProjectRoot()
  bat = fso.BuildPath(root, "start\0_hta_snapshot.bat")
  If Not fso.FileExists(bat) Then
    SetStatus "Missing snapshot bat under " & root
    Exit Sub
  End If
  sh.CurrentDirectory = root
  cmd = sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & bat & Chr(34)
  sh.Run cmd, 0, False
End Sub

Sub FinishRefresh
  Dim fso, root, htmlPath, utc, sz
  Set fso = CreateObject("Scripting.FileSystemObject")
  root = ProjectRoot()
  htmlPath = fso.BuildPath(fso.BuildPath(root, "data"), "dashboard_live.html")
  If Not fso.FileExists(htmlPath) Then
    SetStatus "Missing dashboard_live.html"
    gBusy = False
    Exit Sub
  End If
  ReloadFrame
  utc = ReadUtcFromCache()
  sz = fso.GetFile(htmlPath).Size
  SetStatus "OK " & sz & "b | UTC " & utc & " | 30s"
  gBusy = False
  window.setTimeout "RefreshAll", 30000
End Sub

Sub RefreshAll
  If gBusy Then Exit Sub
  gBusy = True
  SetStatus "Refreshing..."
  ReloadFrame
  RunSnapshotAsync
  window.setTimeout "FinishRefresh", 6000
End Sub

Sub RunBat(relativePath)
  Dim fso, sh, root, bat, cmd
  Set fso = CreateObject("Scripting.FileSystemObject")
  Set sh = CreateObject("WScript.Shell")
  root = ProjectRoot()
  bat = fso.BuildPath(root, relativePath)
  If Not fso.FileExists(bat) Then
    SetStatus "Missing " & relativePath
    Exit Sub
  End If
  sh.CurrentDirectory = root
  cmd = sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & bat & Chr(34)
  sh.Run cmd, 1, False
  SetStatus "Launched " & relativePath
End Sub

Sub RunBatSync(relativePath, extraArgs)
  Dim fso, sh, root, bat, cmd
  Set fso = CreateObject("Scripting.FileSystemObject")
  Set sh = CreateObject("WScript.Shell")
  root = ProjectRoot()
  bat = fso.BuildPath(root, relativePath)
  If Not fso.FileExists(bat) Then
    SetStatus "Missing " & relativePath
    Exit Sub
  End If
  sh.CurrentDirectory = root
  cmd = sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & bat & Chr(34)
  If Len(Trim(extraArgs)) > 0 Then cmd = cmd & " " & extraArgs
  sh.Run cmd, 0, True
  SetStatus "Done " & relativePath
End Sub

Sub RefreshSoon
  window.setTimeout "RefreshAll", 8000
End Sub

Sub BootDashboard
  If gBooted Then Exit Sub
  gBooted = True
  SetStatus "Ready"
  ReloadFrame
  window.setTimeout "RefreshAll", 1000
End Sub

Sub Window_OnLoad
  BootDashboard
End Sub

Sub btnGoLive_OnClick
  RunBat "start\START_BOT.bat"
  RefreshSoon
End Sub

Sub btnStop_OnClick
  RunBatSync "start\5_stop_bot.bat", "--nopause"
  RefreshAll
End Sub

Sub btnPrepare_OnClick
  RunBat "start\GO_LIVE_FULL.bat"
  RefreshSoon
End Sub

Sub btnCheck_OnClick
  RunBat "start\1_check_setup.bat"
End Sub

Sub btnStatus_OnClick
  RunBat "start\6_status.bat"
  RefreshSoon
End Sub

Sub btnDailyReport_OnClick
  RunBat "start\16_daily_report.bat"
End Sub

Sub btnRefresh_OnClick
  RefreshAll
End Sub
