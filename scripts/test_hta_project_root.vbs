Option Explicit
Dim fso, scriptsDir, rootDir
Set fso = CreateObject("Scripting.FileSystemObject")
scriptsDir = fso.GetParentFolderName(WScript.ScriptFullName)
rootDir = fso.GetParentFolderName(scriptsDir)
Dim rootFile, root
rootFile = fso.BuildPath(fso.BuildPath(rootDir, "data"), "hta_root.txt")
If Not fso.FileExists(rootFile) Then
  WScript.Echo "FAIL|missing hta_root.txt"
  WScript.Quit 1
End If
root = Trim(fso.OpenTextFile(rootFile, 1).ReadAll)
If Not fso.FolderExists(root) Then
  WScript.Echo "FAIL|bad root " & root
  WScript.Quit 1
End If
Dim bat
bat = fso.BuildPath(root, "start\START_BOT.bat")
If Not fso.FileExists(bat) Then
  WScript.Echo "FAIL|missing " & bat
  WScript.Quit 1
End If
WScript.Echo "OK|" & root
