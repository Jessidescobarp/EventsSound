<#
.SYNOPSIS
  Tests for the pure parsers of scripts/test-summary.ps1 (Windows PowerShell 5.1 compatible).
.DESCRIPTION
  test-summary.ps1 launches real test processes, so it is never run here. The two pure parser
  functions (Get-PytestSummary, Get-VitestSummary) are extracted from its AST and exercised in
  isolation. Run: powershell -NoProfile -File scripts/test-summary.tests.ps1
#>
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'test-summary.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "test-summary.ps1 has $($errors.Count) parse error(s)" }

$wanted = 'Get-PytestSummary', 'Get-VitestSummary', 'Invoke-Captured', 'Test-FrontendDependencies'
$defs = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in $wanted }, $true)
foreach ($name in $wanted) {
  $def = $defs | Where-Object Name -eq $name
  if (-not $def) { throw "test-summary.ps1 does not define $name" }
  . ([scriptblock]::Create($def.Extent.Text))
}

$failures = 0
function Check([string]$Name, $Actual, $Expected) {
  if ("$Actual" -eq "$Expected") { Write-Host "PASS  $Name" } else { Write-Host "FAIL  $Name (expected '$Expected', got '$Actual')"; $script:failures++ }
}

# --- pytest: pass (no failures) -------------------------------------------
$pytestPass = @(
  'tests/unit/test_agent_nodes.py .........'
  'tests/unit/test_agent_graph.py ..........'
  '============================= summary =============================='
  '2122 passed, 148 skipped in 45.32s'
)
$p = Get-PytestSummary $pytestPass
Check 'pytest pass: tests' $p.Tests '2122 passed, 148 skipped'
Check 'pytest pass: duration' $p.Duration '45.32s'
Check 'pytest pass: no first failure' $p.FirstFailure ''
Check 'pytest pass: no error' $p.Error ''

# --- pytest: fail (tb=line) -----------------------------------------------
$pytestFail = @(
  '=================================== FAILURES ===================================='
  '__________________________________ test_total ____________________________________'
  'backend/tests/unit/test_quote.py:87: AssertionError: expected total 1200, got 1400'
  '=========================== short test summary info =============================='
  'FAILED tests/unit/test_quote.py::test_total - AssertionError: expected total 1200, got 1400'
  '========================= 1 failed, 42 passed in 4.8s =========================='
)
$f = Get-PytestSummary $pytestFail
Check 'pytest fail: tests' $f.Tests '42 passed, 1 failed'
Check 'pytest fail: duration' $f.Duration '4.8s'
Check 'pytest fail: first failure' $f.FirstFailure 'backend/tests/unit/test_quote.py:87'
Check 'pytest fail: error' $f.Error 'AssertionError: expected total 1200, got 1400'
Check 'pytest fail: context lines' $f.Context.Count 3

# --- pytest: unparseable ---------------------------------------------------
$pn = Get-PytestSummary @('no recognizable pytest output here')
Check 'pytest unparseable: tests flagged' $pn.Tests 'not parsed'
Check 'pytest unparseable: no first failure' $pn.FirstFailure ''

# --- vitest: pass (no failures) -------------------------------------------
$vitestPass = @(
  ' RUN  v3.0.0 /frontend'
  ' Test Files  2 passed (2)'
  '      Tests  7 passed (7)'
  '   Duration  0.85s (transform 20ms)'
)
$vp = Get-VitestSummary $vitestPass
Check 'vitest pass: files' $vp.Files '2 passed (2)'
Check 'vitest pass: tests' $vp.Tests '7 passed (7)'
Check 'vitest pass: duration' $vp.Duration '0.85s'
Check 'vitest pass: no first failure' $vp.FirstFailure ''

# --- vitest: fail ----------------------------------------------------------
$vitestFail = @(
  ' RUN  v3.0.0 /frontend'
  ' FAIL  src/App.test.tsx > renders the quote form'
  'AssertionError: expected total 1200, got 1400'
  ' Test Files  1 failed | 1 passed (2)'
  '      Tests  1 failed | 2 passed (3)'
  '   Duration  0.9s'
)
$vf = Get-VitestSummary $vitestFail
Check 'vitest fail: files' $vf.Files '1 failed | 1 passed (2)'
Check 'vitest fail: tests' $vf.Tests '1 failed | 2 passed (3)'
Check 'vitest fail: first failure' $vf.FirstFailure 'src/App.test.tsx'
Check 'vitest fail: error' $vf.Error 'AssertionError: expected total 1200, got 1400'

# --- real processes: the exit code must survive. Windows PowerShell 5.1 returns $null from
# Start-Process -PassThru unless the process handle is cached before it exits, which made a
# fully green suite report FAIL. These checks launch real (harmless) processes on purpose.
$procOk = Invoke-Captured 'cmd.exe' @('/c', 'exit 0') $PSScriptRoot 20
Check 'process exit 0: exit code' $procOk.ExitCode 0
Check 'process exit 0: not timed out' $procOk.TimedOut $false
$procBad = Invoke-Captured 'cmd.exe' @('/c', 'exit 3') $PSScriptRoot 20
Check 'process exit 3: exit code' $procBad.ExitCode 3
$procSlow = Invoke-Captured 'cmd.exe' @('/c', 'ping -n 8 127.0.0.1 >nul') $PSScriptRoot 1
Check 'process timeout: exit code 124' $procSlow.ExitCode 124
Check 'process timeout: flagged' $procSlow.TimedOut $true

# --- frontend dependencies: a missing node_modules must be reported clearly, not as a failing suite
$feDir = Join-Path ([IO.Path]::GetTempPath()) ('ts-fe-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $feDir | Out-Null
Check 'frontend deps: missing node_modules' (Test-FrontendDependencies $feDir) $false
New-Item -ItemType Directory -Path (Join-Path $feDir 'node_modules') | Out-Null
Check 'frontend deps: present' (Test-FrontendDependencies $feDir) $true
Remove-Item $feDir -Recurse -Force

if ($failures -gt 0) { Write-Host "$failures check(s) failed"; exit 1 }
Write-Host 'all checks passed'
