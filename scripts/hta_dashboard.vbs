Dim gRefreshBusy
Dim gInitDone

Function LinePrefix(line, prefix)
  LinePrefix = (InStr(line, prefix) = 1)
End Function

Function ProjectRoot()
  Dim fso, rootFile, cached, htaDir
  Set fso = CreateObject("Scripting.FileSystemObject")
  htaDir = HtaFileDir()
  rootFile = fso.BuildPath(fso.BuildPath(htaDir, "data"), "hta_root.txt")
  If fso.FileExists(rootFile) Then
    cached = Trim(ReadTextFile(rootFile))
    If Len(cached) > 0 And fso.FolderExists(cached) Then
      ProjectRoot = fso.GetAbsolutePathName(cached)
      Exit Function
    End If
  End If
  ProjectRoot = htaDir
End Function

Function HtaFileDir()
  Dim fso, href
  Set fso = CreateObject("Scripting.FileSystemObject")
  href = document.location.href
  href = Replace(href, "file:///", "")
  href = Replace(href, "file://", "")
  href = Replace(href, "/", "\")
  If Len(href) >= 3 And Left(href, 1) = "\" And Mid(href, 3, 1) = ":" Then
    href = Mid(href, 2)
  End If
  If fso.FileExists(href) Then
    HtaFileDir = fso.GetParentFolderName(fso.GetAbsolutePathName(href))
  Else
    HtaFileDir = fso.GetParentFolderName(href)
  End If
End Function

Function ReadTextFile(path)
  Dim fso, ts
  ReadTextFile = ""
  Set fso = CreateObject("Scripting.FileSystemObject")
  If Not fso.FileExists(path) Then Exit Function
  On Error Resume Next
  Set ts = fso.OpenTextFile(path, 1, False, 0)
  If Not ts.AtEndOfStream Then ReadTextFile = ts.ReadAll
  ts.Close
  On Error GoTo 0
End Function

Function NormalizeLines(out)
  NormalizeLines = Split(Replace(Replace(out, vbCrLf, vbLf), vbCr, vbLf), vbLf)
End Function

Sub KickSnapshotRefresh(root)
  Dim fso, sh, snapBat, cmd
  On Error Resume Next
  Set fso = CreateObject("Scripting.FileSystemObject")
  Set sh = CreateObject("WScript.Shell")
  snapBat = fso.BuildPath(root, "start\0_hta_snapshot.bat")
  If fso.FileExists(snapBat) Then
    cmd = sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & snapBat & Chr(34)
    sh.CurrentDirectory = root
    sh.Run cmd, 0, False
  End If
  On Error GoTo 0
End Sub

Sub RunSnapshotSync(root)
  Dim fso, sh, snapBat, cmd
  On Error Resume Next
  Set fso = CreateObject("Scripting.FileSystemObject")
  Set sh = CreateObject("WScript.Shell")
  snapBat = fso.BuildPath(root, "start\0_hta_snapshot.bat")
  If fso.FileExists(snapBat) Then
    cmd = sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & snapBat & Chr(34)
    sh.CurrentDirectory = root
    sh.Run cmd, 0, True
  End If
  On Error GoTo 0
End Sub

Sub ApplyHtmlFile(elId, fileName, root)
  On Error Resume Next
  Dim fso, p, html
  Set fso = CreateObject("Scripting.FileSystemObject")
  p = fso.BuildPath(fso.BuildPath(root, "data"), fileName)
  If fso.FileExists(p) Then
    html = ReadTextFile(p)
    If Len(Trim(html)) > 0 Then document.getElementById(elId).innerHTML = html
  End If
  On Error GoTo 0
End Sub

Sub SetBacktestDefaults
  On Error Resume Next
  Dim d
  d = Year(Now) & "-" & Right("0" & Month(Now), 2) & "-" & Right("0" & Day(Now), 2)
  document.getElementById("bt-start-date").value = d
  document.getElementById("bt-end-date").value = d
  On Error GoTo 0
End Sub

Sub RunBatFile(relativePath)
  Dim sh, fso, root, batPath, cmd
  Set sh = CreateObject("WScript.Shell")
  Set fso = CreateObject("Scripting.FileSystemObject")
  root = ProjectRoot()
  batPath = fso.BuildPath(root, relativePath)
  If Not fso.FileExists(batPath) Then
    document.getElementById("action-status").innerText = "Missing: " & relativePath
    Exit Sub
  End If
  sh.CurrentDirectory = root
  cmd = sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & batPath & Chr(34)
  sh.Run cmd, 1, False
End Sub

Sub RunStopBot()
  Dim sh, fso, root, batPath, cmd
  Set sh = CreateObject("WScript.Shell")
  Set fso = CreateObject("Scripting.FileSystemObject")
  root = ProjectRoot()
  batPath = fso.BuildPath(root, "start\5_stop_bot.bat")
  If fso.FileExists(batPath) Then
    sh.CurrentDirectory = root
    cmd = sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & batPath & Chr(34) & " --nopause"
    sh.Run cmd, 0, True
  End If
  RefreshLivePanel
End Sub

Sub ToggleBacktestPanel
  Dim p
  Set p = document.getElementById("backtest-panel")
  If p.style.display = "none" Then SetBacktestDefaults : p.style.display = "block" Else p.style.display = "none"
End Sub

Sub RunCustomBacktest
  Dim root, fso, sh, cfgPath, ts, json
  Set fso = CreateObject("Scripting.FileSystemObject")
  Set sh = CreateObject("WScript.Shell")
  root = ProjectRoot()
  cfgPath = fso.BuildPath(fso.BuildPath(root, "data"), "hta_backtest_request.json")
  json = "{""start"":""" & Trim(document.getElementById("bt-start-date").value) & """,""end"":""" & Trim(document.getElementById("bt-end-date").value) & """,""balance"":" & Trim(document.getElementById("bt-balance").value) & ",""symbol"":""" & Trim(document.getElementById("bt-symbol").value) & """" & "}"
  Set ts = fso.CreateTextFile(cfgPath, True, False)
  ts.Write json
  ts.Close
  sh.CurrentDirectory = root
  sh.Run sh.ExpandEnvironmentStrings("%COMSPEC%") & " /c call " & Chr(34) & fso.BuildPath(root, "start\8_backtest_custom.bat") & Chr(34), 1, False
End Sub

Sub RefreshLivePanel
  If gRefreshBusy Then Exit Sub
  gRefreshBusy = True
  On Error Resume Next
  Dim root, fso, cachePath, out, lines, i, line, parts
  Dim paPf, paExpR, paAccept, paTrades, mt5Ok, wdText, botText, procHtml, logHtml, alertsHtml
  Set fso = CreateObject("Scripting.FileSystemObject")
  root = ProjectRoot()
  cachePath = fso.BuildPath(fso.BuildPath(root, "data"), "hta_dashboard_snapshot.txt")
  out = ""
  If fso.FileExists(cachePath) Then out = ReadTextFile(cachePath)
  If Len(Trim(out)) = 0 Then RunSnapshotSync root : out = ReadTextFile(cachePath)
  KickSnapshotRefresh root
  paPf = "-" : paExpR = "-" : paAccept = "-" : paTrades = "0"
  mt5Ok = False : wdText = "-" : botText = "-" : procHtml = "" : logHtml = ""

  If Len(Trim(out)) = 0 Then
    document.getElementById("action-status").innerText = "Snapshot empty - run status_snapshot.py"
    document.getElementById("live-state").innerText = "OFFLINE"
    gRefreshBusy = False
    Exit Sub
  End If

  lines = NormalizeLines(out)
  For i = 0 To UBound(lines)
    line = Trim(lines(i))
    If LinePrefix(line, "STATE|") Then
      If InStr(line, "RUNNING") > 0 Then
        document.getElementById("live-state").innerText = "LIVE RUNNING"
        document.getElementById("sys-status").innerText = "ACTIVE"
      Else
        document.getElementById("live-state").innerText = "STOPPED"
        document.getElementById("sys-status").innerText = "STOPPED"
      End If
    ElseIf LinePrefix(line, "UTC|") Then
      document.getElementById("live-utc").innerText = Mid(line, 5) & " UTC"
    ElseIf LinePrefix(line, "WATCHDOG|") Then
      wdText = Mid(line, 10)
    ElseIf LinePrefix(line, "BOT|") Then
      botText = Mid(line, 5)
    ElseIf LinePrefix(line, "KERNEL|") Then
      procHtml = Mid(line, 8)
    ElseIf LinePrefix(line, "NOTE|") Then
      document.getElementById("demo-banner").className = "demo-banner show"
      document.getElementById("demo-banner").innerText = Mid(line, 6)
    ElseIf LinePrefix(line, "ACCOUNT|") Then
      parts = Split(line, "|")
      If UBound(parts) >= 2 Then
        mt5Ok = True
        document.getElementById("hero-equity").innerText = "$" & parts(2)
        document.getElementById("hero-pnl").innerText = "Balance $" & parts(1) & " | PnL " & parts(3)
      End If
    ElseIf LinePrefix(line, "ML|") Then
      parts = Split(line, "|")
      If UBound(parts) >= 1 Then document.getElementById("card-ml").innerText = parts(1)
      If UBound(parts) >= 3 Then document.getElementById("card-ml-detail").innerText = parts(2)
    ElseIf LinePrefix(line, "LOG|") Then
      parts = Split(line, "|")
      If UBound(parts) >= 3 Then logHtml = parts(3)
    ElseIf LinePrefix(line, "ENGINE|") Then
      parts = Split(line, "|")
      If UBound(parts) >= 7 And UCase(parts(1)) = "PA" Then
        paAccept = Replace(parts(4), "accept=", "") & "%"
        paTrades = Replace(parts(5), "trades=", "")
        paPf = Replace(parts(6), "PF=", "")
        paExpR = Replace(parts(7), "ExpR=", "") & "R"
      End If
    End If
  Next

  ApplyHtmlFile "engine-list", "hta_engine.html", root
  ApplyHtmlFile "task-list", "hta_tasks.html", root
  ApplyHtmlFile "signal-stream", "hta_signals.html", root
  ApplyHtmlFile "live-cycles", "hta_cycles.html", root
  ApplyHtmlFile "live-phase4", "hta_phase4.html", root
  alertsHtml = ReadTextFile(fso.BuildPath(fso.BuildPath(root, "data"), "hta_alerts.html"))
  If Len(Trim(alertsHtml)) > 0 Then
    document.getElementById("alert-banner").className = "alert-banner show alert-warn"
    document.getElementById("alert-banner").innerHTML = alertsHtml
  Else
    document.getElementById("alert-banner").className = "alert-banner"
    document.getElementById("alert-banner").innerHTML = ""
  End If

  document.getElementById("kpi-pf").innerText = paPf
  document.getElementById("kpi-expr").innerText = paExpR
  document.getElementById("kpi-accept").innerText = paAccept
  document.getElementById("kpi-pf-sub").innerText = paTrades & " trades | PA"
  document.getElementById("footer-watchdog").innerText = "WD: " & wdText
  document.getElementById("footer-bot").innerText = "BOT: " & botText
  document.getElementById("footer-latency").innerText = "REFRESH: 30s"
  document.getElementById("card-proc").innerText = procHtml
  If Len(logHtml) > 0 Then document.getElementById("live-log").innerText = logHtml
  If mt5Ok Then
    document.getElementById("footer-api").innerText = "API: MT5 LINK"
    document.getElementById("api-status").innerText = "LINK"
  Else
    document.getElementById("footer-api").innerText = "API: MT5 OFF"
    document.getElementById("api-status").innerText = "OFF"
  End If
  document.getElementById("action-status").innerText = "OK " & Len(out) & " bytes | " & root
  gRefreshBusy = False
  window.setTimeout GetRef("RefreshLivePanel"), 30000
  On Error GoTo 0
End Sub

Sub InitDashboard
  If gInitDone Then Exit Sub
  gInitDone = True
  gRefreshBusy = False
  On Error Resume Next
  document.title = "TradingBot v8.7.2-FIX [" & ProjectRoot() & "]"
  document.getElementById("action-status").innerText = "Booting v8.7.2-FIX..."
  SetBacktestDefaults
  RefreshLivePanel
  On Error GoTo 0
End Sub

Sub Window_OnLoad
  InitDashboard
End Sub

Sub btnGoLive_OnClick
  RunBatFile "start\START_BOT.bat"
End Sub

Sub btnStop_OnClick
  RunStopBot
End Sub

Sub btnPrepare_OnClick
  RunBatFile "start\GO_LIVE_FULL.bat"
End Sub

Sub btnCheck_OnClick
  RunBatFile "start\1_check_setup.bat"
End Sub

Sub btnStatus_OnClick
  RunBatFile "start\6_status.bat"
End Sub

Sub btnBacktest_OnClick
  ToggleBacktestPanel
End Sub

Sub btnDailyReport_OnClick
  RunBatFile "start\16_daily_report.bat"
End Sub

Sub btnRefresh_OnClick
  RefreshLivePanel
End Sub

Sub btnRunBacktest_OnClick
  RunCustomBacktest
End Sub

Sub btnCloseBacktest_OnClick
  ToggleBacktestPanel
End Sub
