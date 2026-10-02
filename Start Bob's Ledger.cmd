@echo off
rem ====================================================================
rem  Bob's Ledger - double-click launcher
rem
rem  Does the four things that actually go wrong on a fresh machine:
rem  finds Python, checks the one dependency, says where the log folder
rem  should be, and offers a Desktop shortcut wearing the icon. Then it
rem  starts the coach and opens the overlay.
rem
rem  Usage:
rem    Start Bob's Ledger.cmd              start the coach
rem    Start Bob's Ledger.cmd --check      report and exit, start nothing
rem    Start Bob's Ledger.cmd --shortcut   (re)create the Desktop shortcut
rem    Start Bob's Ledger.cmd --no-update  any live.py flag passes through
rem ====================================================================
setlocal EnableExtensions
title Bob's Ledger
cd /d "%~dp0"

echo ============================================================
echo   Bob's Ledger - Hearthstone Battlegrounds coach
echo ============================================================
echo.

rem --- 1. Python ------------------------------------------------------
rem A dev checkout's own venv wins; otherwise the py launcher, which is
rem what the python.org installer provides. `python` last, since on some
rem machines it is the Microsoft Store stub.
rem PY holds a whole COMMAND, quotes included for a path (this repo's own
rem path has a space in it) and bare words for `py -3` - so it is expanded
rem unquoted everywhere below.
set "PY="
if exist "%~dp0hearth-coach\.venv\Scripts\python.exe" set PY="%~dp0hearth-coach\.venv\Scripts\python.exe"
if defined PY goto :have_python
py -3 --version >nul 2>&1
if not errorlevel 1 set PY=py -3
if defined PY goto :have_python
python --version >nul 2>&1
if not errorlevel 1 set PY=python
if defined PY goto :have_python

echo Python 3 was not found on this PC, and the coach needs it.
echo.
echo   1. Download it from https://www.python.org/downloads/
echo   2. In the installer, TICK "Add python.exe to PATH"
echo   3. Run this file again
echo.
choice /c YN /n /m "Open the download page now? [Y/N] "
if errorlevel 2 goto :end
start "" "https://www.python.org/downloads/"
goto :end

:have_python
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo Python:       %PYVER%
echo               %PY%

rem --- 2. the one dependency ------------------------------------------
rem Asked, never assumed: this file is downloaded from the internet, and
rem one that silently runs pip is the kind people are right to distrust.
%PY% -c "import requests" >nul 2>&1
if not errorlevel 1 goto :deps_ok
echo.
echo The coach needs one Python package: requests
echo.
echo   %PY% -m pip install -r "%~dp0hearth-coach\requirements.txt"
echo.
choice /c YN /n /m "Install it now? [Y/N] "
if errorlevel 2 goto :no_deps
%PY% -m pip install -r "%~dp0hearth-coach\requirements.txt"
if errorlevel 1 goto :fail
goto :deps_ok

:no_deps
echo.
echo Skipped. The coach will not start without it; run the pip line above
echo when you are ready.
goto :end

:deps_ok
echo Dependencies: ok

rem --- 3. Hearthstone's log folder ------------------------------------
rem Told, not written. live.py reports the same thing when it finds no
rem Power.log, and the README documents the log.config block; creating a
rem file inside the game's own folder would break the uninstall promise.
set "LOGDIR=%ProgramFiles(x86)%\Hearthstone\Logs"
if exist "%LOGDIR%" goto :shortcut_step
echo.
echo Note: no Hearthstone log folder at
echo   %LOGDIR%
echo If the game lives elsewhere that is fine - the coach looks in the
echo standard place and can be pointed with HEARTHSTONE_HOME. What it does
echo need is file logging turned ON (README, Quick start step 2).

:shortcut_step
if /i "%~1"=="--check" goto :report
set "WANT_SHORTCUT=0"
if /i "%~1"=="--shortcut" set "WANT_SHORTCUT=1"
if "%WANT_SHORTCUT%"=="1" goto :make_shortcut
if exist "%USERPROFILE%\Desktop\Bob's Ledger.lnk" goto :run
echo.
choice /c YN /n /m "Put a Bob's Ledger shortcut with its icon on your Desktop? [Y/N] "
if errorlevel 2 goto :run
:make_shortcut
rem Built on THIS machine on purpose: a shortcut file embeds absolute
rem paths, so one shipped inside the zip would point at the packager's
rem disk. GetFolderPath('Desktop') also survives a redirected Desktop.
rem SELF/HERE are apostrophe-doubled before they reach PowerShell: this
rem file's own name contains one ("Bob's Ledger.cmd"), and a single-quoted
rem PowerShell string ends at the first apostrophe - so the unescaped path
rem made the whole command a parse error and no shortcut ever appeared.
set "SELF=%~f0"
set "SELF=%SELF:'=''%"
set "HERE=%~dp0"
set "HERE=%HERE:'=''%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Bob''s Ledger.lnk')); $s.TargetPath='%SELF%'; $s.WorkingDirectory='%HERE%'; $s.IconLocation='%HERE%bobs-ledger.ico'; $s.Description='Bobs Ledger - Hearthstone Battlegrounds coach'; $s.Save(); Write-Host ('shortcut created: ' + (Join-Path $d 'Bob''s Ledger.lnk'))"
if errorlevel 1 echo Could not create the shortcut - dragging this file to the Desktop works too.
goto :run

:report
echo.
echo --check only, nothing was started.
if exist "%USERPROFILE%\Desktop\Bob's Ledger.lnk" goto :rep_yes
echo Desktop shortcut: no
goto :rep_end
:rep_yes
echo Desktop shortcut: yes
:rep_end
echo Next: double-click this file with no arguments to start the coach.
goto :end

:run
echo.
echo Starting the coach. The overlay opens in your browser.
echo Leave this window open while you play; Ctrl+C here stops it.
echo.
set "PASS=%*"
set "PASS=%PASS:--check=%"
set "PASS=%PASS:--shortcut=%"
%PY% "%~dp0hearth-coach\live.py" --open %PASS%
if errorlevel 1 goto :fail
goto :end

:fail
echo.
echo Something went wrong above - the message is the reason.
echo Run with --check to see the environment this file found.
:end
echo.
pause
endlocal
