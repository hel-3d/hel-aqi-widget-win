Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

cmd = """" & scriptDir & "\update_aqi.bat"""

shell.Run cmd, 0, False

