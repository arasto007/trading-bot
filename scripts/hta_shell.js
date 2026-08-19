// HTA dashboard shell - JScript (reliable in mshta.exe).
var gBusy = false;
var gBooted = false;
var REFRESH_MS = 30000;
var SOON_MS = 8000;

function ProjectRoot() {
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  var href = String(document.location.href);
  href = href.replace(/^file:\/\//i, "").replace(/\//g, "\\");
  if (href.charAt(0) === "\\" && href.charAt(2) === ":") {
    href = href.substring(1);
  }
  var htaDir;
  if (fso.FileExists(href)) {
    htaDir = fso.GetParentFolderName(fso.GetAbsolutePathName(href));
  } else {
    htaDir = fso.GetParentFolderName(href);
  }
  var rootFile = fso.BuildPath(fso.BuildPath(htaDir, "data"), "hta_root.txt");
  if (fso.FileExists(rootFile)) {
    var ts = fso.OpenTextFile(rootFile, 1, false, 0);
    var cached = String(ts.ReadAll()).replace(/^\s+|\s+$/g, "");
    ts.Close();
    if (cached.length > 0 && fso.FolderExists(cached)) {
      return fso.GetAbsolutePathName(cached);
    }
  }
  return htaDir;
}

function ReadUtcFromCache(root) {
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  var p = fso.BuildPath(fso.BuildPath(root, "data"), "hta_dashboard_snapshot.txt");
  if (!fso.FileExists(p)) return "-";
  try {
    var ts = fso.OpenTextFile(p, 1, false, 0);
    var txt = ts.ReadAll();
    ts.Close();
    var lines = String(txt).split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var line = String(lines[i]).replace(/^\s+|\s+$/g, "");
      if (line.indexOf("UTC|") === 0) return line.substring(4);
    }
  } catch (e) {}
  return "-";
}

function SetStatus(msg) {
  try {
    document.getElementById("status").innerText = msg;
    document.title = "TradingBot v9.0.2 | " + msg;
  } catch (e) {}
}

function ReloadFrame() {
  try {
    var fr = document.getElementById("liveframe");
    fr.src = "data/dashboard_live.html?t=" + String(new Date().getTime());
  } catch (e) {}
}

function RunSnapshotSync() {
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  var sh = new ActiveXObject("WScript.Shell");
  var root = ProjectRoot();
  var bat = fso.BuildPath(root, "start\\0_hta_snapshot.bat");
  if (fso.FileExists(bat)) {
    sh.CurrentDirectory = root;
    sh.Run('cmd /c call "' + bat + '"', 0, true);
  }
}

function RefreshAll() {
  if (gBusy) return;
  gBusy = true;
  try {
    var fso = new ActiveXObject("Scripting.FileSystemObject");
    var root = ProjectRoot();
    SetStatus("Refreshing snapshot...");
    RunSnapshotSync();
    var htmlPath = fso.BuildPath(fso.BuildPath(root, "data"), "dashboard_live.html");
    if (!fso.FileExists(htmlPath)) {
      SetStatus("Missing dashboard_live.html");
      return;
    }
    ReloadFrame();
    var utc = ReadUtcFromCache(root);
    var sz = fso.GetFile(htmlPath).Size;
    SetStatus("OK " + sz + " bytes | UTC " + utc + " | next " + (REFRESH_MS / 1000) + "s");
    window.setTimeout(RefreshAll, REFRESH_MS);
  } catch (e) {
    SetStatus("Refresh error: " + e.message);
  } finally {
    gBusy = false;
  }
}

function RunBat(relativePath, windowStyle, wait) {
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  var sh = new ActiveXObject("WScript.Shell");
  var root = ProjectRoot();
  var bat = fso.BuildPath(root, relativePath.replace(/\//g, "\\"));
  if (!fso.FileExists(bat)) {
    SetStatus("Missing " + relativePath);
    return false;
  }
  sh.CurrentDirectory = root;
  sh.Run('cmd /c call "' + bat + '"', windowStyle || 1, wait ? true : false);
  SetStatus("Launched " + relativePath);
  return true;
}

function RunBatSync(relativePath, extraArgs) {
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  var sh = new ActiveXObject("WScript.Shell");
  var root = ProjectRoot();
  var bat = fso.BuildPath(root, relativePath.replace(/\//g, "\\"));
  if (!fso.FileExists(bat)) {
    SetStatus("Missing " + relativePath);
    return false;
  }
  sh.CurrentDirectory = root;
  var cmd = 'cmd /c call "' + bat + '"';
  if (extraArgs && String(extraArgs).length > 0) cmd += " " + extraArgs;
  sh.Run(cmd, 0, true);
  SetStatus("Done " + relativePath);
  return true;
}

function RefreshSoon() {
  window.setTimeout(RefreshAll, SOON_MS);
}

function BootDashboard() {
  if (gBooted) return;
  gBooted = true;
  RefreshAll();
}

function BtnGoLive() {
  RunBat("start\\START_BOT.bat", 1, false);
  SetStatus("START sent - refresh in " + (SOON_MS / 1000) + "s");
  RefreshSoon();
}

function BtnStop() {
  RunBatSync("start\\5_stop_bot.bat", "--nopause");
  RefreshAll();
}

function BtnPrepare() {
  RunBat("start\\GO_LIVE_FULL.bat", 1, false);
  RefreshSoon();
}

function BtnCheck() {
  RunBat("start\\1_check_setup.bat", 1, false);
}

function BtnStatus() {
  RunBat("start\\6_status.bat", 1, false);
  RefreshSoon();
}

function BtnDailyReport() {
  RunBat("start\\16_daily_report.bat", 1, false);
}

function BtnRefresh() {
  RefreshAll();
}

window.onload = BootDashboard;
window.setTimeout(BootDashboard, 250);
