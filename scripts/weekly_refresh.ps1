# Weekly fantasy report: pull live ESPN roster/free-agent data, regenerate
# docs/index.html (start/sit + waiver targets), publish if changed.
# Run by three Windows Task Scheduler triggers (Tue/Thu 9am, Sun 11am -
# see README.md for exact setup). Safe to run more often than that; it
# just regenerates the same report from whatever ESPN returns at the time.
#
# Structure (repo path, log file, branch guard, commit-only-if-changed,
# abort loudly rather than push something broken) borrowed from the
# sibling MLB Elo project's daily_refresh.ps1, which uses the same
# pattern for its own scheduled GitHub Pages publish.

$Repo = "C:\Users\Diggs\Dropbox\PC\Documents\Claude\fantasy_football"
$Python = "C:\Users\Diggs\venvs\fantasy_football\Scripts\python.exe"
$Git = "C:\Program Files\Git\cmd\git.exe"

$LogDir = "$env:LOCALAPPDATA\fantasy_football\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("weekly_refresh_{0}.log" -f (Get-Date -Format "yyyy-MM-dd_HHmmss"))

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Output $line | Tee-Object -FilePath $LogFile -Append
}

Set-Location $Repo
Log "Starting weekly fantasy refresh in $Repo"

$CurrentBranch = & $Git rev-parse --abbrev-ref HEAD
if ($CurrentBranch -ne "main") {
    Log "FAILED: repo is on branch '$CurrentBranch', not main - aborting so this doesn't land on a stray branch unnoticed (GitHub Pages only serves main). Run 'git checkout main' in $Repo and re-run this script."
    exit 1
}

Set-Location "$Repo\src"
Log "--- weekly_report.py ---"
& $Python weekly_report.py *>> $LogFile
if ($LASTEXITCODE -ne 0) {
    Log "FAILED: weekly_report.py (exit $LASTEXITCODE) - aborting, nothing will be committed/pushed."
    exit 1
}

Set-Location $Repo
$changes = & $Git status --porcelain docs/index.html
if (-not $changes) {
    Log "No change in docs/index.html - nothing to commit. Done."
    exit 0
}

Log "Committing and pushing docs/index.html"
& $Git add docs/index.html *>> $LogFile
$dateStr = Get-Date -Format "yyyy-MM-dd HH:mm"
& $Git commit -m "Automated weekly fantasy refresh: $dateStr" *>> $LogFile
if ($LASTEXITCODE -ne 0) {
    Log "FAILED: git commit (exit $LASTEXITCODE)"
    exit 1
}
& $Git push *>> $LogFile
if ($LASTEXITCODE -ne 0) {
    Log "FAILED: git push (exit $LASTEXITCODE) - commit succeeded locally but did NOT reach GitHub."
    exit 1
}

Log "Done - pushed successfully."
