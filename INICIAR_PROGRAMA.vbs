Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "pyw """ & folder & "\app.py"""
result = sh.Run(cmd, 0, False)
If result <> 0 Then
    sh.Run "pythonw """ & folder & "\app.py""", 0, False
End If
