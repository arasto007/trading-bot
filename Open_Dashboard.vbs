Option Explicit

Dim sh, fso, root, py, cmd

Set sh = CreateObject("WScript.Shell")

Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)



If Not fso.FolderExists(fso.BuildPath(root, "data")) Then

  fso.CreateFolder fso.BuildPath(root, "data")

End If



py = "python"

If fso.FileExists(fso.BuildPath(root, ".venv\Scripts\python.exe")) Then

  py = fso.BuildPath(root, ".venv\Scripts\python.exe")

End If



cmd = """" & py & """ """ & fso.BuildPath(root, "scripts\dashboard_server.py") & """"

sh.CurrentDirectory = root

sh.Run cmd, 1, False

