<#
.SYNOPSIS
  Smoke check for a running stack (local by default, or deployed URLs).
.EXAMPLE
  Deployed free-tier hosts can take 60-90 s to wake up, so allow retries:
  scripts/smoke.ps1 -BackendUrl https://api.example.com -FrontendUrl https://app.example.com `
    -Origin https://app.example.com -TimeoutSec 30 -Retries 12 -RetryDelaySec 10
#>
[CmdletBinding()]
param(
  [string]$BackendUrl = 'http://127.0.0.1:8000',
  [string]$FrontendUrl = 'http://localhost:5173',
  [string]$Origin = 'http://localhost:5173',
  [string]$DisallowedOrigin = 'http://evil.example',
  [int]$TimeoutSec = 15,
  [int]$Retries = 0,
  [int]$RetryDelaySec = 5,
  [switch]$AllowWildcardCors
)

$ErrorActionPreference = 'Stop'
$BackendUrl = $BackendUrl.TrimEnd('/')
$FrontendUrl = $FrontendUrl.TrimEnd('/')
$localTarget = ([uri]$BackendUrl).Host -in @('127.0.0.1', 'localhost')
$wildcardOk = $AllowWildcardCors -or $localTarget

# Never throws: returns status, body and headers, also for non-2xx and connection failures.
function Get-Safe([string]$Url, [string]$Method = 'GET', [hashtable]$Headers = @{}) {
  try {
    Invoke-WebRequest -Uri $Url -Method $Method -Headers $Headers -UseBasicParsing -TimeoutSec $TimeoutSec
  } catch {
    $resp = $_.Exception.Response
    if ($resp) { return [pscustomobject]@{ StatusCode = [int]$resp.StatusCode; Content = ''; Headers = $resp.Headers } }
    [pscustomobject]@{ StatusCode = 0; Content = ''; Headers = @{} }
  }
}

function Get-Header($Response, [string]$Name) { [string]@($Response.Headers[$Name])[0] }

# A test scriptblock returns @(ok, detail); it is retried so cold starts do not give false FAILs.
$results = @()
function Add-Check([string]$Name, [scriptblock]$Test) {
  for ($i = 0; $i -le $Retries; $i++) {
    $ok, $detail = & $Test
    if ($ok -or $i -eq $Retries) { break }
    Start-Sleep -Seconds $RetryDelaySec
  }
  $script:results += [pscustomobject]@{ Check = $Name; Result = $(if ($ok) { 'PASS' } else { 'FAIL' }); Detail = $detail }
}

function Test-Allowed([string]$Allow, [string]$Expected) { $Allow -eq $Expected -or ($wildcardOk -and $Allow -eq '*') }

Add-Check 'backend /health' {
  $r = Get-Safe "$BackendUrl/health"
  try { $status = ($r.Content | ConvertFrom-Json).status } catch { $status = $null }
  ($r.StatusCode -eq 200 -and $status -eq 'ok'), "HTTP $($r.StatusCode), status '$status'"
}
Add-Check 'backend /health/db' {
  $r = Get-Safe "$BackendUrl/health/db"
  ($r.StatusCode -eq 200), "HTTP $($r.StatusCode)"
}
Add-Check 'backend /docs (public Swagger)' {
  $r = Get-Safe "$BackendUrl/docs"
  ($r.StatusCode -eq 200), "HTTP $($r.StatusCode)"
}
Add-Check 'backend login rejects bad credentials (401, not 503)' {
  try {
    $r = Invoke-WebRequest "$BackendUrl/auth/login" -Method Post -ContentType 'application/json' -Body '{"email":"nobody@smoke.invalid","password":"not-a-password"}' -UseBasicParsing -TimeoutSec 30
    $code = [int]$r.StatusCode
  } catch { $code = [int]$_.Exception.Response.StatusCode }
  ($code -eq 401), "HTTP $code (503 means JWT_SECRET is missing or weak)"
}
Add-Check 'frontend root' {
  $r = Get-Safe $FrontendUrl
  $mount = $r.Content -match 'id="root"'
  ($r.StatusCode -eq 200 -and $mount), "HTTP $($r.StatusCode), mount point $(if ($mount) { 'found' } else { 'missing' })"
}
Add-Check 'CORS simple request' {
  $allow = Get-Header (Get-Safe "$BackendUrl/health" 'GET' @{ Origin = $Origin }) 'Access-Control-Allow-Origin'
  (Test-Allowed $allow $Origin), "Origin $Origin -> '$allow'"
}
Add-Check 'CORS preflight' {
  $r = Get-Safe "$BackendUrl/health" 'OPTIONS' @{ Origin = $Origin; 'Access-Control-Request-Method' = 'GET'; 'Access-Control-Request-Headers' = 'content-type' }
  $allow = Get-Header $r 'Access-Control-Allow-Origin'
  ($r.StatusCode -eq 200 -and (Test-Allowed $allow $Origin)), "HTTP $($r.StatusCode), allow-origin '$allow'"
}
Add-Check 'CORS rejects other origin' {
  $allow = Get-Header (Get-Safe "$BackendUrl/health" 'GET' @{ Origin = $DisallowedOrigin }) 'Access-Control-Allow-Origin'
  ($allow -ne $DisallowedOrigin -and ($allow -eq '' -or ($allow -eq '*' -and $wildcardOk))), "Origin $DisallowedOrigin -> '$allow'"
}

$results | Format-Table -AutoSize | Out-String | Write-Host
if ($results | Where-Object Result -eq 'FAIL') { exit 1 }
exit 0
