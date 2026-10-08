Option Explicit

Dim shell
Dim command
Dim index

If WScript.Arguments.Count = 0 Then
    WScript.Quit 2
End If

command = ""
For index = 0 To WScript.Arguments.Count - 1
    If index > 0 Then
        command = command & " "
    End If
    command = command & Quote(WScript.Arguments(index))
Next

Set shell = CreateObject("WScript.Shell")
WScript.Quit shell.Run(command, 0, True)

Function Quote(value)
    Quote = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
