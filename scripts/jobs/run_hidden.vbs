' Hidden launcher - runs a .bat with no console window
Set sh = CreateObject("WScript.Shell")
args = ""
For i = 1 To WScript.Arguments.Count - 1
  args = args & " " & WScript.Arguments(i)
Next
sh.Run """" & WScript.Arguments(0) & """" & args, 0, False
