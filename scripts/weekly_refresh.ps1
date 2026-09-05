# Weekly fantasy report: pull live ESPN roster/free-agent data, regenerate
# docs/fantasy/index.html (start/sit + waiver targets), publish if changed.
# Run by three Windows Task Scheduler triggers (Tue/Thu 9am, Sun 11am -
# see fantasy-football/README.md for exact setup). Safe to run more often
# than that; it just regenerates the same report from whatever ESPN
# returns at the time.
#
# Mirrors scripts/daily_refresh.ps1's structure (repo path, log file,
# branch guard, commit-only-if-changed) - see that file for the reasoning
# behind each piece.

$Repo = "C:\Users\Diggs\Dropbox\PC\Documents\Claude\mlb_elo"
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
if ($CurrentBranch -ne "master") {
    Log "FAILED: repo is on branch '$CurrentBranch', not master - aborting so this doesn't land on a stray branch unnoticed (see daily_refresh.ps1's comment for why this guard exists). Run 'git checkout master' in $Repo and re-run this script."
    exit 1
}

Set-Location "$Repo\fantasy-football\src"
Log "--- weekly_report.py ---"
& $Python weekly_report.py *>> $LogFile
if ($LASTEXITCODE -ne 0) {
    Log "FAILED: weekly_report.py (exit $LASTEXITCODE) - aborting, nothing will be committed/pushed."
    exit 1
}

Set-Location $Repo
$changes = & $Git status --porcelain docs/fantasy/index.html
if (-not $changes) {
    Log "No change in docs/fantasy/index.html - nothing to commit. Done."
    exit 0
}

Log "Committing and pushing docs/fantasy/index.html"
& $Git add docs/fantasy/index.html *>> $LogFile
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
