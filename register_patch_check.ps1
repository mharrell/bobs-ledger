# Register a weekly Windows Task Scheduler task that runs the patch-notes check.
#
# Review-first: the task only writes a report to patch_reports/ and shows a
# toast; it never edits the meta DB. To apply a detected patch, review the
# report and run `python patch_notes.py <url> --apply` yourself.
#
# Run from PowerShell (as your normal user, not admin):
#     powershell -ExecutionPolicy Bypass -File register_patch_check.ps1
#
# The task runs in your interactive session, so it inherits your user
# environment. For the LLM extraction to work, set DEEPSEEK_API_KEY (e.g.
# `setx DEEPSEEK_API_KEY <key>`) or drop a meta/.patch_config.json with
# {"api_key": "..."}. Without a key the check still writes the Battlegrounds
# section for manual review.
param(
    # Resolved from this script's own location, so it works on any machine
    # and the file carries no local profile path.
    [string]$Python = (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    [string]$Script = (Join-Path $PSScriptRoot "check_patch_notes.py"),
    [string]$TaskName = "HearthCoachPatchCheck",
    [string]$Days = "Monday",
    [string]$At = "09:00"
)

if (-not (Test-Path $Python)) {
    Write-Error "Python not found at $Python"
    exit 1
}
if (-not (Test-Path $Script)) {
    Write-Error "Script not found at $Script"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $At
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Description "Check Hearthstone patch notes and write a review report" -Force

Write-Host "Registered scheduled task '$TaskName' (weekly $Days at $At)."
Write-Host "  Runs: $Python `"$Script`""
Write-Host "To test it now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To remove it:    Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
