#!/bin/bash
# ====================================================================
#  Bob's Ledger - double-click launcher (macOS)
#
#  The twin of "Start Bob's Ledger.cmd", doing the same four things that
#  go wrong on a fresh machine: finds Python, checks the one dependency,
#  offers to turn Hearthstone's file logging on, says where the log
#  folder is. Then it starts the coach and opens the overlay in your
#  browser.
#
#  NOT YET VERIFIED ON A MAC. This file has never been run - or even
#  parsed by a shell, because the machine it was written on has no bash
#  at all. Treat the first run as the test and expect the Python or venv
#  step to need a fix. It is deliberately written for bash 3.2, which is
#  what /bin/bash still is on macOS: no associative arrays, no ${x,,}.
#
#  If double-clicking does nothing or macOS refuses to open it, run it
#  from Terminal instead - that path is never blocked:
#      bash "Start Bob's Ledger.command"
#
#  Usage:
#    Start Bob's Ledger.command              start the coach
#    Start Bob's Ledger.command --check      report and exit, start nothing
#    Start Bob's Ledger.command --no-update  any live.py flag passes through
# ====================================================================
set -u

cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

echo "============================================================"
echo "  Bob's Ledger - Hearthstone Battlegrounds coach"
echo "============================================================"
echo

# --- 0. an interrupted update ---------------------------------------
# An update moves a release into place file by file, setting the replaced
# copies aside in .staging/old and dropping an APPLYING marker first. If that
# marker is still here the process died mid-commit, and this install may be
# part old and part new - which is how a coach stops starting. The set-aside
# copies are enough to make it run again, and update.py finishes the job
# properly (removing files the new version added) once Python is up. APPLIED,
# not APPLYING, means the update finished: never undo that.
if [ -f "$HERE/.staging/APPLYING" ]; then
	echo "An earlier update was interrupted. Restoring the version that worked..."
	cp -Rf "$HERE/.staging/old/." "$HERE/" 2>/dev/null || true
	echo "Done."
	echo
fi

# The program lives in app/, so this folder shows almost nothing. Checked
# BEFORE the Python work: the usual reason it is missing is that Finder is
# running this file straight out of the .zip, and telling someone to
# install Python when the real problem is an unextracted archive wastes
# their time.
if [ ! -f "$HERE/app/live.py" ]; then
	echo "This file has to run from inside the extracted folder."
	echo
	echo "  Double-click the downloaded .zip first, then run this file from"
	echo "  the folder that makes."
	echo
	printf "Press Return to close."
	read -r _dummy || true
	exit 1
fi

# --check reports and starts nothing. It is matched on a PREFIX, because a
# shell that hands over "--check=" used to fall through on the Windows
# launcher and silently START the coach instead of reporting (2026-10-02).
CHECK_ONLY=0
for arg in "$@"; do
	case "$arg" in
		--check*) CHECK_ONLY=1 ;;
		*) ;;
	esac
done

# --- 1. Python ------------------------------------------------------
# A venv from an earlier run wins, because that is where pip will have put
# requests. Then python3: macOS only has it once the Command Line Tools are
# installed, and running it is what offers to install them.
PY=""
if [ -x "$HERE/.venv/bin/python3" ]; then
	PY="$HERE/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
	PY="$(command -v python3)"
fi

if [ -z "$PY" ]; then
	echo "Python 3 was not found, and the coach needs it."
	echo
	echo "  1. Download it from https://www.python.org/downloads/macos/"
	echo "  2. Run the installer, then run this file again"
	echo
	echo "  Or, in Terminal:  xcode-select --install"
	echo
	printf "Open the download page now? [y/N] "
	read -r answer || answer=""
	case "$answer" in
		[Yy]*) open "https://www.python.org/downloads/macos/" || true ;;
		*) ;;
	esac
	exit 1
fi

echo "Python:       $("$PY" --version 2>&1)"
echo "              $PY"

# --- 2. the one dependency ------------------------------------------
# Asked, never assumed: this file arrived from the internet, and one that
# silently runs pip is the kind people are right to distrust. The install
# goes into a venv beside the coach rather than --user, because Homebrew's
# Python refuses to install packages system-wide (PEP 668) - and this way
# the dependency stays out of everything else on the machine.
if "$PY" -c "import requests" >/dev/null 2>&1; then
	echo "Dependencies: ok"
else
	echo
	echo "The coach needs one Python package: requests"
	echo
	printf "Install it into a private folder beside the coach? [y/N] "
	read -r answer || answer=""
	case "$answer" in
		[Yy]*)
			if ! "$PY" -m venv "$HERE/.venv"; then
				echo
				echo "Could not create the private folder. Install Python from"
				echo "python.org (step 1) and run this file again."
				exit 1
			fi
			PY="$HERE/.venv/bin/python3"
			if ! "$PY" -m pip install --quiet --upgrade pip \
				|| ! "$PY" -m pip install --quiet -r "$HERE/app/requirements.txt"; then
				echo
				echo "pip could not install it - the message above is the reason."
				exit 1
			fi
			echo "Dependencies: ok"
			;;
		*)
			echo
			echo "Skipped. The coach will not start without it; run this file"
			echo "again when you are ready."
			exit 1
			;;
	esac
fi

# --- 3. Hearthstone's file logging ----------------------------------
# The step nearly everyone misses, and the difference between a coach that
# advises and one that shows an empty card forever. So it is OFFERED rather
# than described: setup_logging.py makes the edit, because log.config has
# other sections that must survive (anyone using a Deck Tracker already has
# one, and replacing it would break their logging), and it touches that
# single file and nothing else - keeping a backup first. On macOS that file
# lives under ~/Library/Preferences, not AppData.
LOGGING_OK=0
if "$PY" "$HERE/app/setup_logging.py" --check >/dev/null 2>&1; then
	LOGGING_OK=1
else
	echo
	echo "Hearthstone's file logging is OFF, and the coach cannot advise without it."
	echo
	printf "Turn it on for me now? [y/N] "
	read -r answer || answer=""
	case "$answer" in
		[Yy]*)
			if "$PY" "$HERE/app/setup_logging.py" --apply; then
				LOGGING_OK=1
			else
				echo
				echo "Could not set it up. Close Hearthstone and run this file again"
				echo "- or use the block in the README (Turn on Hearthstone's logging)."
			fi
			;;
		*)
			echo
			echo "No problem. By hand: open this folder"
			echo "  $HOME/Library/Preferences/Blizzard/Hearthstone"
			echo "and make sure [Power] has LogLevel=1 and FilePrinting=true. The"
			echo "README has the full block."
			open "$HOME/Library/Preferences/Blizzard/Hearthstone" 2>/dev/null || true
			;;
	esac
fi

# Where the game writes the log the coach reads. Told, not created: if it
# is not there the game is probably installed elsewhere, which is fine, but
# the coach has to be pointed at it.
LOGDIR="/Applications/Hearthstone/Logs"
if [ ! -d "$LOGDIR" ]; then
	echo
	echo "Note: no Hearthstone log folder at"
	echo "  $LOGDIR"
	echo "If the game lives elsewhere that is fine - the coach looks in the"
	echo "standard place and can be pointed with HEARTHSTONE_HOME."
fi

if [ "$CHECK_ONLY" = "1" ]; then
	echo
	echo "--check only, nothing was started, nothing was written."
	if [ "$LOGGING_OK" = "1" ]; then
		echo "File logging: on"
	else
		echo "File logging: OFF  (the coach cannot advise until it is on)"
	fi
	echo "Next: double-click this file to start."
	echo
	printf "Press Return to close."
	read -r _dummy || true
	exit 0
fi

echo
echo "Starting the coach. The overlay opens in your browser."
echo "Leave this window open while you play; Ctrl+C here stops it."
echo

# The reporting flag is dropped before passing anything through: live.py
# ignores unknown flags, so a stray one is a silent no-op rather than an
# error. (macOS has no Desktop-shortcut step: a double-clickable file in
# this folder is already the shortcut.)
PASS=()
for arg in "$@"; do
	case "$arg" in
		--check|--check=*|--shortcut) ;;
		*) PASS[${#PASS[@]}]="$arg" ;;
	esac
done

if [ "${#PASS[@]}" -gt 0 ]; then
	"$PY" "$HERE/app/live.py" --open "${PASS[@]}"
else
	"$PY" "$HERE/app/live.py" --open
fi
code=$?

if [ "$code" -ne 0 ]; then
	echo
	echo "Something went wrong above - the message is the reason."
	echo "Run with --check to see the environment this file found."
fi
echo
printf "Press Return to close."
read -r _dummy || true
exit "$code"
