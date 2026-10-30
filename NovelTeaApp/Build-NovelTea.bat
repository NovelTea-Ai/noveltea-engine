@echo off
REM Double-click to rebuild NovelTea Engine (frontend + backend exe) and relaunch it.
REM Same script the Build button on the Workspace Assistant page runs.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-NovelTea.ps1" %*
pause
