@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m scrollferry.app
if errorlevel 1 goto failed
exit /b 0
:failed
echo Launch failed. Install Python 3.11 or newer with Tcl/Tk and the Python launcher.
pause
exit /b 1
