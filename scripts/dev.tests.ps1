<#
.SYNOPSIS
  Tests for the helper functions of scripts/dev.ps1 (Windows PowerShell 5.1 compatible).
.DESCRIPTION
  dev.ps1 starts real processes, so it is never run here. The helpers are extracted from its
  AST and exercised in isolation. Run: powershell -NoProfile -File scripts/dev.tests.ps1
#>
$ErrorActionPreference = 'Stop'
$devScript = Join-Path $PSScriptRoot 'dev.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($devScript, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "dev.ps1 has $($errors.Count) parse error(s)" }

$wanted = 'Invoke-WithMocksEnv', 'Get-FrontendMocks', 'Set-FrontendMocks', 'Get-MocksMismatchWarning'
$defs = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in $wanted }, $true)
foreach ($name in $wanted) {
  $def = $defs | Where-Object Name -eq $name
  if (-not $def) { throw "dev.ps1 does not define $name" }
  . ([scriptblock]::Create($def.Extent.Text))
}

$failures = 0
function Check([string]$Name, $Actual, $Expected) {
  if ("$Actual" -eq "$Expected") { Write-Host "PASS  $Name" } else { Write-Host "FAIL  $Name (expected '$Expected', got '$Actual')"; $script:failures++ }
}
function Get-Var { [Environment]::GetEnvironmentVariable('VITE_USE_MOCKS', 'Process') }
function Set-Var($v) { [Environment]::SetEnvironmentVariable('VITE_USE_MOCKS', $v, 'Process') }
function Get-ChildSees { "$(cmd /c 'if defined VITE_USE_MOCKS (echo %VITE_USE_MOCKS%) else (echo unset)')".Trim() }

$original = Get-Var
try {
  # --- Invoke-WithMocksEnv ---
  Set-Var $null
  $seen = Invoke-WithMocksEnv $true { Get-ChildSees }
  Check 'enabled: child process sees true' $seen 'true'
  Check 'enabled: caller variable unset again afterwards' (Get-Var) ''

  Set-Var 'true'
  $seen = Invoke-WithMocksEnv $false { Get-ChildSees }
  Check 'disabled: inherited true is cleared for the child' $seen 'unset'
  Check 'disabled: caller keeps its own true afterwards' (Get-Var) 'true'

  Set-Var 'false'
  [void](Invoke-WithMocksEnv $true { 1 })
  Check 'enabled: caller value false restored' (Get-Var) 'false'

  Set-Var $null
  $threw = $false
  try { Invoke-WithMocksEnv $true { throw 'boom' } } catch { $threw = $true }
  Check 'action failure propagates' $threw $true
  Check 'action failure still restores (unset)' (Get-Var) ''

  Set-Var 'true'
  try { Invoke-WithMocksEnv $false { throw 'boom' } } catch { }
  Check 'action failure still restores (true)' (Get-Var) 'true'

  # --- marker file and mismatch warnings ---
  $DevDir = Join-Path ([IO.Path]::GetTempPath()) ("devtests-" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force $DevDir | Out-Null
  Check 'no marker means mocks off' (Get-FrontendMocks) $false
  Set-FrontendMocks $true
  Check 'marker records mocks on' (Get-FrontendMocks) $true
  Set-FrontendMocks $false
  Check 'marker records mocks off' (Get-FrontendMocks) $false
  Remove-Item $DevDir -Recurse -Force

  Check 'same state, nothing to warn' (Get-MocksMismatchWarning $false $false) ''
  Check 'same state (mocks), nothing to warn' (Get-MocksMismatchWarning $true $true) ''
  Check 'plain run over a mocked Vite warns about DEMO' ((Get-MocksMismatchWarning $false $true) -match 'DEMO') $true
  Check '-Mocks over a plain Vite warns' ((Get-MocksMismatchWarning $true $false) -match 'WITHOUT') $true

  # --- -Mocks with -Down/-Reset is an explicit warning, not silently ignored ---
  $downIf = $ast.FindAll({ param($n)
      $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Clauses[0].Item1.Extent.Text -match '\$Down\s+-or\s+\$Reset' }, $false) | Select-Object -First 1
  $body = $downIf.Clauses[0].Item2.Extent.Text
  Check '-Down/-Reset block warns when -Mocks is given' ($body -match 'Write-Warning' -and $body -match '\$Mocks') $true
}
finally {
  Set-Var $original
}

if ($failures -gt 0) { Write-Host "$failures check(s) failed"; exit 1 }
Write-Host 'all checks passed'
