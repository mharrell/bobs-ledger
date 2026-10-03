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

rem --- 0. an interrupted update ---------------------------------------
rem An update moves a release into place file by file, setting the replaced
rem copies aside in .staging\old and dropping an APPLYING marker first. If
rem that marker is still here the process died mid-commit, and this install
rem may be part old and part new - which is how a coach stops starting. The
rem set-aside copies are enough to make it run again, and update.py finishes
rem the job properly (removing files the new version added) once Python is
rem up. APPLIED, not APPLYING, means the update finished: never undo that.
if not exist "%~dp0.staging\APPLYING" goto :update_recovery_done
echo An earlier update was interrupted. Restoring the version that worked...
xcopy /E /Y /I /Q "%~dp0.staging\old\*" "%~dp0" >nul 2>&1
echo Done.
echo.
:update_recovery_done

rem The program lives in app\, so this folder shows almost nothing: the
rem launcher, the README, the licence and docs\. Checked BEFORE the Python
rem work, because the usual reason it is missing is that Windows is running
rem this file straight out of the .zip - and telling someone to install
rem Python when the real problem is an unextracted archive wastes their time.
if not exist "%~dp0app\live.py" goto :no_program

rem --- 1. Python ------------------------------------------------------
rem A dev checkout's own venv wins; otherwise the py launcher, which is
rem what the python.org installer provides. `python` last, since on some
rem machines it is the Microsoft Store stub.
rem PY holds a whole COMMAND, quotes included for a path (this repo's own
rem path has a space in it) and bare words for `py -3` - so it is expanded
rem unquoted everywhere below.
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set PY="%~dp0.venv\Scripts\python.exe"
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
echo   %PY% -m pip install -r "%~dp0app\requirements.txt"
echo.
choice /c YN /n /m "Install it now? [Y/N] "
if errorlevel 2 goto :no_deps
%PY% -m pip install -r "%~dp0app\requirements.txt"
if errorlevel 1 goto :fail
goto :deps_ok

:no_deps
echo.
echo Skipped. The coach will not start without it; run the pip line above
echo when you are ready.
goto :end

:deps_ok
echo Dependencies: ok

rem --- 3. Hearthstone's file logging ----------------------------------
rem The step nearly everyone misses, and the difference between a coach that
rem advises and one that shows an empty card forever. So it is OFFERED rather
rem than described: setup_logging.py makes the edit, because log.config has
rem other sections that must survive (anyone using Deck Tracker or Firestone
rem already has one, and replacing it would break their logging), and it
rem touches that single file and nothing else - keeping a backup first.
%PY% "%~dp0app\setup_logging.py" --check >nul 2>&1
if not errorlevel 1 goto :logging_done
echo.
echo Hearthstone's file logging is OFF, and the coach cannot advise without it.
echo.
choice /c YN /n /m "Turn it on for me now? [Y/N] "
if errorlevel 2 goto :logging_manual
%PY% "%~dp0app\setup_logging.py" --apply
if errorlevel 1 goto :logging_failed
goto :logging_done

:logging_failed
echo.
echo Could not set it up. Close Hearthstone and run this file again - or use
echo the block in the README (Turn on Hearthstone's logging).
goto :logging_done

:logging_manual
echo.
echo No problem. By hand: open this folder
echo   %LOCALAPPDATA%\Blizzard\Hearthstone
echo and make sure [Power] has LogLevel=1 and FilePrinting=true. The README
echo has the full block.
if exist "%LOCALAPPDATA%\Blizzard\Hearthstone" start "" "%LOCALAPPDATA%\Blizzard\Hearthstone"

:logging_done
rem Where the game writes the log the coach reads. Told, not created: if it is
rem not there the game is probably installed elsewhere, which is fine, but the
rem coach has to be pointed at it.
set "LOGDIR=%ProgramFiles(x86)%\Hearthstone\Logs"
if exist "%LOGDIR%" goto :shortcut_step
echo.
echo Note: no Hearthstone log folder at
echo   %LOGDIR%
echo If the game lives elsewhere that is fine - the coach looks in the
echo standard place and can be pointed with HEARTHSTONE_HOME.

:shortcut_step
rem Paths for the shortcut step. ROOT/SELFRAW stay raw for batch use; HERE/
rem SELF are apostrophe-doubled for the PowerShell strings below, because a
rem single-quoted PowerShell string ends at the first apostrophe - and this
rem file's own name contains one ("Start Bob's Ledger.cmd").
set "ROOT=%~dp0"
set "SELFRAW=%~f0"
set "HERE=%ROOT:'=''%"
set "SELF=%SELFRAW:'=''%"

rem The Desktop is often redirected (OneDrive is the common one), so
rem %USERPROFILE%\Desktop is NOT reliably where shortcuts land. Every
rem candidate is checked: reading only the unredirected path made --check
rem report "no" on a machine whose shortcut was sitting in OneDrive\Desktop,
rem and would have re-offered it on every single start.
set "DESKTOP="
if exist "%USERPROFILE%\Desktop" set "DESKTOP=%USERPROFILE%\Desktop"
if exist "%USERPROFILE%\OneDrive\Desktop" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if defined OneDrive if exist "%OneDrive%\Desktop" set "DESKTOP=%OneDrive%\Desktop"

rem One prompt, both shortcuts: Windows never draws an icon on a .cmd, so a
rem shortcut is the ONLY way to hand someone something clickable that wears
rem the icon. The copy in this folder is the one that always makes sense (it
rem travels with the install); the Desktop one is convenience. Asked rather
rem than assumed, and --check below reports without writing anything.
rem Match on a PREFIX: a shell that hands over "--check=" (which happened)
rem used to miss the exact-match test and fall through to the run below, so
rem asking for a report silently STARTED the coach instead. Two of those were
rem left running and held the install directory open (2026-10-02). ARG1 is given
rem a placeholder when there are no arguments, and that is not cosmetic: cmd
rem mangles an UNDEFINED variable in the "%ARG1:~0,8%" test below into "The syntax
rem of the command is incorrect." and kills the batch on the spot - so every plain
rem double-click died right after "Dependencies: ok" (found 2026-10-02).
if "%~1"=="" (set "ARG1=.") else set "ARG1=%~1"
if /i "%ARG1%"=="--check" goto :report
if /i "%ARG1:~0,8%"=="--check=" goto :report
set "WANT_SHORTCUT=0"
if /i "%~1"=="--shortcut" set "WANT_SHORTCUT=1"
if "%WANT_SHORTCUT%"=="1" goto :make_shortcuts
if not exist "%ROOT%Bob's Ledger.lnk" goto :ask_shortcuts
if not defined DESKTOP goto :run
if not exist "%DESKTOP%\Bob's Ledger.lnk" goto :ask_shortcuts
goto :run
:ask_shortcuts
echo.
choice /c YN /n /m "Create a 'Bob's Ledger' shortcut with its icon, here and on your Desktop? [Y/N] "
if errorlevel 2 goto :run
:make_shortcuts
call :make_lnk "%ROOT%Bob's Ledger.lnk"
if defined DESKTOP call :make_lnk "%DESKTOP%\Bob's Ledger.lnk"
goto :run

rem ---------------------------------------------------------------- helpers
rem Written on THIS machine on purpose: a shortcut embeds absolute paths, so
rem one shipped inside the zip would point at the packager's disk. (No -ExecutionPolicy Bypass: inline -Command is not governed by execution policy, verified under Restricted - and the flag is what security tooling scores.)
:make_lnk
set "LNK=%~1"
set "LNK=%LNK:'=''%"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%'); $s.TargetPath='%SELF%'; $s.WorkingDirectory='%HERE%'; $s.IconLocation='%HERE%app\bobs-ledger.ico'; $s.Description='Bobs Ledger - Hearthstone Battlegrounds coach'; $s.Save()"
if errorlevel 1 echo Could not create a shortcut at %~1 - dragging this file where you want it works too.
exit /b 0

:report
echo.
echo --check only, nothing was started, nothing was written.
if exist "%ROOT%Bob's Ledger.lnk" goto :rep_folder_yes
echo Shortcut in this folder: no  (a normal start offers to create it)
goto :rep_desk
:rep_folder_yes
echo Shortcut in this folder: yes
:rep_desk
if defined DESKTOP goto :rep_desk_known
echo Desktop shortcut: unknown (no Desktop folder found)
goto :rep_end
:rep_desk_known
if exist "%DESKTOP%\Bob's Ledger.lnk" goto :rep_desk_yes
echo Desktop shortcut: no   (looked in %DESKTOP%)
goto :rep_end
:rep_desk_yes
echo Desktop shortcut: yes
:rep_end
echo Next: double-click "Bob's Ledger" (the shortcut) or this file to start.
goto :end

:run
echo.
echo Starting the coach. The overlay opens in your browser.
echo Leave this window open while you play; Ctrl+C here stops it.
echo.
set "PASS=%*"
set "PASS=%PASS:--check=%"
set "PASS=%PASS:--shortcut=%"
rem Stripping a substring leaves debris when the token was "--check=": a lone
rem "=" would be handed to live.py, which ignores unknown flags - the same
rem silent-start failure by another door.
if "%PASS%"=="=" set "PASS="
%PY% "%~dp0app\live.py" --open %PASS%
if errorlevel 1 goto :fail
goto :end

:no_program
echo This file has to run from inside the extracted folder.
echo.
echo   Windows extracts only this one file when you run it straight out of
echo   the .zip, and the coach itself lives in app\ next to it. Right-click
echo   the downloaded .zip, choose "Extract All...", and run this file from
echo   the folder that makes.
echo.
goto :end

:fail
echo.
echo Something went wrong above - the message is the reason.
echo Run with --check to see the environment this file found.
:end
echo.
pause
endlocal
