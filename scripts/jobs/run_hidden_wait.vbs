' Hidden launcher - runs a .bat with no console window.
' Unlike run_hidden.vbs this WAITS for the job to finish and
' returns its exit code, so Task Scheduler still sees the real
' result and its "do not start a new instance" rule still works.
Set sh = CreateObject("WScript.Shell")
args = ""
For i = 1 To WScript.Arguments.Count - 1
  args = args & " " & WScript.Arguments(i)
Next
rc = sh.Run("""" & WScript.Arguments(0) & """" & args, 0, True)
WScript.Quit rc
