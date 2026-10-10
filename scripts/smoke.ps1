<#
.SYNOPSIS
  Smoke check for a running stack (local by default, or deployed URLs).
.EXAMPLE
  scripts/smoke.ps1 -BackendUrl https://api.example.com -FrontendUrl https://app.example.com -Origin https://app.example.com
#>
[CmdletBinding()]
param(
  [string]$BackendUrl = 'http://127.0.0.1:8000',
  [string]$FrontendUrl = 'http://127.0.0.1:5173',
  [string]$Origin = 'http://localhost:5173'
)

$ErrorActionPreference = 'Stop'
$BackendUrl = $BackendUrl.TrimEnd('/')
$FrontendUrl = $FrontendUrl.TrimEnd('/')

function Get-Safe([string]$Url, [hashtable]$Headers = @{}) {
  try {
    Invoke-WebRequest -Uri $Url -Headers $Headers -UseBasicParsing -TimeoutSec 15
  } catch {
    if ($_.Exception.Response) { return [pscustomobject]@{ StatusCode = [int]$_.Exception.Response.StatusCode; Content = ''; Headers = @{} } }
    [pscustomobject]@{ StatusCode = 0; Content = ''; Headers = @{} }
  }
}

$results = @()
function Add-Check([string]$Name, [bool]$Ok, [string]$Detail) {
  $script:results += [pscustomobject]@{ Check = $Name; Result = $(if ($Ok) { 'PASS' } else { 'FAIL' }); Detail = $Detail }
}

$r = Get-Safe "$BackendUrl/health"
$body = $r.Content -replace '\s', ''
Add-Check 'backend /health' ($r.StatusCode -eq 200 -and $body -eq '{"status":"ok"}') "HTTP $($r.StatusCode)"

$r = Get-Safe "$BackendUrl/health/db"
Add-Check 'backend /health/db' ($r.StatusCode -eq 200) "HTTP $($r.StatusCode)"

$r = Get-Safe $FrontendUrl
Add-Check 'frontend root' ($r.StatusCode -eq 200 -and $r.Content -match 'id="root"') "HTTP $($r.StatusCode), mount point $(if ($r.Content -match 'id="root"') { 'found' } else { 'missing' })"

$r = Get-Safe "$BackendUrl/health" @{ Origin = $Origin }
$allow = [string]$r.Headers['Access-Control-Allow-Origin']
Add-Check 'CORS allow-origin' ($allow -eq $Origin) "Origin $Origin -> '$allow'"

$results | Format-Table -AutoSize | Out-String | Write-Host
if ($results | Where-Object Result -eq 'FAIL') { exit 1 }
exit 0
