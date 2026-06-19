@echo off
REM Convenience wrapper so you can double-click to launch debug Chrome.
REM Delegates to start_chrome_debug.ps1 (see that file for details).
powershell -ExecutionPolicy Bypass -File "%~dp0start_chrome_debug.ps1" %*
