@echo off
REM Double-click this. It asks for admin, then repoints the SectorFlow
REM scheduled tasks so their console windows stop popping up.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"%~dp0apply_hidden_jobs.ps1\"'"
