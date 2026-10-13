<#
.SYNOPSIS
  Compact test runner: executes the suites and prints a short summary instead of the full log.
.DESCRIPTION
  Runs the backend (pytest via uv) and/or the frontend (vitest via npm) suites, captures all
  output internally and prints: STATUS, SUITE, MODE, DURATION, TESTS, FIRST_FAILURE, ERROR and
  a bounded number of context lines. On failure the full log is saved to a temp file whose path
  is printed (LOG:), so the complete output can be inspected only when the summary is not enough.
  The exit code is the real exit code of the suite (124 = timeout), for automation.
  It only ever runs the known commands (uv pytest, npm test); it does not accept arbitrary
  commands, and it never prints environment variables, connection URLs, tokens or credentials.
.EXAMPLE
  scripts/test-summary.ps1 -Suite backend -Filter tests/unit/test_agent_nodes.py
  scripts/test-summary.ps1 -Suite backend -Mode full
  scripts/test-summary.ps1 -Suite frontend -Filter App.test
  scripts/test-summary.ps1 -Suite all -MaxFail1
#>
[CmdletBinding()]
param(
  [ValidateSet('backend', 'frontend', 'all')]
  [string]$Suite = 'all',
  [ValidateSet('focused', 'full')]
  [string]$Mode = 'focused',
  [string]$Filter = '',
  [int]$TimeoutSec = 300,
  [switch]$MaxFail1
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

# --- Pure parsers (extracted by test-summary.tests.ps1) ------------------------------------

function Get-PytestSummary([string[]]$Lines) {
  $tests = 'not parsed'
  $duration = 'not parsed'
  $firstFailure = ''
  $error = ''
  $context = @()
  $tail = $Lines | Where-Object { $_ -match '\d+ (passed|failed|error|skipped|deselected)' } | Select-Object -Last 1
  if ($tail) {
    $parts = @()
    foreach ($kind in 'passed', 'failed', 'error', 'skipped') {
      if ($tail -match "(\d+) $kind") { $parts += "$($matches[1]) $kind" }
    }
    if ($parts.Count -gt 0) { $tests = ($parts -join ', ') }
    if ($tail -match 'in ([\d.]+)s') { $duration = "$($matches[1])s" }
  }
  $failIdx = -1
  for ($i = 0; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match '^(FAILED|ERROR) ') { $failIdx = $i; break }
  }
  if ($failIdx -ge 0) {
    $id = $Lines[$failIdx] -replace '^(FAILED|ERROR) ', ''
    $id = $id -replace ' - .*$', ''
    foreach ($line in $Lines) {
      if ($line -match '^(\S+\.py):(\d+):(.*)$') {
        $firstFailure = "$($matches[1])`:$($matches[2])"
        $error = $matches[3].Trim()
        break
      }
    }
    $start = [Math]::Max(0, $failIdx - 1)
    $end = [Math]::Min($Lines.Count - 1, $failIdx + 2)
    $context = @($Lines[$start..$end])
    if ($firstFailure -eq '' -and $id -match '^(\S+?\.py)::') { $firstFailure = $matches[1] }
  }
  [pscustomobject]@{ Tests = $tests; Duration = $duration; FirstFailure = $firstFailure; Error = $error; Context = $context }
}

function Get-VitestSummary([string[]]$Lines) {
  $tests = 'not parsed'
  $files = ''
  $duration = 'not parsed'
  $firstFailure = ''
  $error = ''
  $context = @()
  foreach ($line in $Lines) {
    if ($line -match 'Test Files\s+(.+)') { $files = $matches[1].Trim() }
    if ($line -match '^\s*Tests\s+(.+)') { $tests = $matches[1].Trim() }
    if ($line -match 'Duration\s+([\d.]+)s') { $duration = "$($matches[1])s" }
  }
  $failIdx = -1
  for ($i = 0; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match '^\s*FAIL\s+(\S+)') { $failIdx = $i; $firstFailure = $matches[1]; break }
  }
  if ($failIdx -ge 0) {
    for ($i = $failIdx + 1; $i -lt $Lines.Count; $i++) {
      if ($Lines[$i] -match '\b(\w*Error)\b') { $error = $Lines[$i].Trim(); break }
    }
    $end = [Math]::Min($Lines.Count - 1, $failIdx + 2)
    $context = @($Lines[$failIdx..$end])
  }
  [pscustomobject]@{ Files = $files; Tests = $tests; Duration = $duration; FirstFailure = $firstFailure; Error = $error; Context = $context }
}

# --- Execution (captured, never streamed to the console) ------------------------------------

function Invoke-Captured([string]$Exe, [string[]]$Arguments, [string]$Workdir, [int]$TimeoutSec) {
  $stamp = [guid]::NewGuid().ToString('N')
  $out = Join-Path ([IO.Path]::GetTempPath()) ("ts-out-$stamp.log")
  $err = Join-Path ([IO.Path]::GetTempPath()) ("ts-err-$stamp.log")
  $proc = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $Workdir `
    -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
  # Windows PowerShell 5.1: without a cached handle, Start-Process -PassThru leaves ExitCode $null
  # once the process exits, which made every green run report FAIL. Touching .Handle fixes it.
  $null = $proc.Handle
  $exited = $proc.WaitForExit($TimeoutSec * 1000)
  if (-not $exited) {
    try { taskkill /PID $proc.Id /T /F | Out-Null } catch { try { Stop-Process -Id $proc.Id -Force } catch { } }
  }
  $stdout = if (Test-Path $out) { [IO.File]::ReadAllText($out, [System.Text.Encoding]::UTF8) } else { '' }
  $stderr = if (Test-Path $err) { [IO.File]::ReadAllText($err, [System.Text.Encoding]::UTF8) } else { '' }
  Remove-Item $out, $err -Force -ErrorAction SilentlyContinue
  $lines = @(($stdout -split "`r?`n") + ($stderr -split "`r?`n")) | Where-Object { $_.Trim() -ne '' }
  [pscustomobject]@{
    Lines = @($lines)
    ExitCode = if (-not $exited) { 124 } elseif ($null -eq $proc.ExitCode) { 1 } else { [int]$proc.ExitCode }
    TimedOut = -not $exited
    DurationSec = 0
  }
}

function Write-Summary([string]$Name, [string]$ModeName, [bool]$Ok, [double]$DurationSec, $S, [bool]$TimedOut) {
  $status = if ($Ok) { 'PASS' } else { 'FAIL' }
  Write-Host "STATUS: $status"
  Write-Host "SUITE: $Name"
  Write-Host "MODE: $ModeName"
  Write-Host "DURATION: $([Math]::Round($DurationSec, 1))s"
  if ($TimedOut) { Write-Host "TIMEOUT: killed after ${TimeoutSec}s" }
  $testsValue = $S.Tests
  if ($S.Files) { $testsValue = "files $($S.Files); tests $testsValue" }
  Write-Host "TESTS: $testsValue"
  if (-not $Ok) {
    if ($S.FirstFailure) { Write-Host "FIRST_FAILURE: $($S.FirstFailure)" }
    if ($S.Error) { Write-Host "ERROR: $([string]($S.Error).Substring(0, [Math]::Min(200, [string]($S.Error).Length)))" }
    if ($S.Context.Count -gt 0) { Write-Host "OUTPUT: $($S.Context.Count) relevant lines retained" }
  }
  if ($script:LogPath) { Write-Host "LOG: $script:LogPath" }
}

function Run-Suite([string]$Name, [string]$ModeName, [string]$Exe, [string[]]$Arguments, [string]$Workdir, $Parse) {
  $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  $result = Invoke-Captured $Exe $Arguments $Workdir $TimeoutSec
  $stopwatch.Stop()
  $result.DurationSec = $stopwatch.Elapsed.TotalSeconds
  $ok = ($result.ExitCode -eq 0)
  $summary = & $Parse $result.Lines
  if (-not $ok) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $script:LogPath = Join-Path ([IO.Path]::GetTempPath()) "test-summary-$Name`-$stamp.log"
    Set-Content -Path $script:LogPath -Value ($result.Lines -join "`n") -Encoding UTF8
  } else {
    $script:LogPath = $null
  }
  Write-Summary $Name $ModeName $ok $result.DurationSec $summary $result.TimedOut
  if ($result.TimedOut) { $result.ExitCode = 124 }
  return $result.ExitCode
}

# --- Suite definitions (known commands only) -------------------------------------------------

$fail = 0
function Run-Backend([string]$ModeName, [string]$FilterValue, [switch]$StopAtFirst) {
  $argv = @('run', '--project', 'backend', 'pytest')
  if ($FilterValue -match '\.(py|ts|tsx)$' -or $FilterValue -match '[/\\]') { $argv += $FilterValue }
  else { $argv += 'backend/tests'; if ($FilterValue -ne '') { $argv += @('-k', $FilterValue) } }
  $argv += @('-q', '--tb=line', '--color', 'no')
  if ($StopAtFirst) { $argv += '--maxfail=1' }
  $parse = { param($L) Get-PytestSummary $L }
  return (Run-Suite 'backend' $ModeName 'uv.exe' $argv $Root $parse)
}

function Test-FrontendDependencies([string]$FrontendDir) {
  return (Test-Path -LiteralPath (Join-Path $FrontendDir 'node_modules') -PathType Container)
}

function Run-Frontend([string]$ModeName, [string]$FilterValue) {
  if (-not (Test-FrontendDependencies (Join-Path $Root 'frontend'))) {
    Write-Host 'STATUS: FAIL'
    Write-Host 'SUITE: frontend'
    Write-Host "MODE: $ModeName"
    Write-Host "ERROR: frontend dependencies are missing: run 'npm ci' inside frontend/ first (nothing was executed)"
    return 2
  }
  $argv = @('run', 'test', '--', '--run')
  if ($FilterValue -ne '') { $argv += $FilterValue }
  $parse = { param($L) Get-VitestSummary $L }
  return (Run-Suite 'frontend' $ModeName 'npm.cmd' $argv (Join-Path $Root 'frontend') $parse)
}

if ($Suite -in 'backend', 'all') {
  $fail = [Math]::Max($fail, (Run-Backend $Mode $Filter $MaxFail1))
}
if ($Suite -in 'frontend', 'all') {
  $fail = [Math]::Max($fail, (Run-Frontend $Mode $Filter))
}
exit $fail
