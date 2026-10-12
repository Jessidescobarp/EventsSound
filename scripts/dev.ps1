<#
.SYNOPSIS
  Hybrid local development: Postgres in Docker, backend and frontend native with hot reload.
.DESCRIPTION
  dev.ps1          start (idempotent): db, migrations, uvicorn --reload, vite
  dev.ps1 -Down    stop the two processes and the db container (keeps the volume)
  dev.ps1 -Reset   -Down plus drop the db volume
  dev.ps1 -Smoke   run scripts/smoke.ps1 after start
  -Mocks           start the frontend with VITE_USE_MOCKS=true: the catalog is served from a fake
                   API with demo data and every page shows a 'Datos de demostracion' banner.
                   Stop first (-Down) if the frontend is already running without it.
  -AllowRemoteDb   permit a DATABASE_URL whose host is not 127.0.0.1/localhost (dangerous)
  Settings come from the process environment or the root .env (copied from .env.example
  when neither exists). Secrets are never printed. Logs and PIDs live in .dev/.
#>
[CmdletBinding()]
param([switch]$Down, [switch]$Reset, [switch]$Smoke, [switch]$Mocks, [switch]$AllowRemoteDb, [int]$TimeoutSec = 90)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$DevDir = Join-Path $Root '.dev'
$BackendUrl = 'http://127.0.0.1:8000'
# Must equal the origin in CORS_ALLOWED_ORIGINS / VITE_API_BASE_URL defaults (.env.example).
$FrontendUrl = 'http://localhost:5173'
Set-Location $Root

# Runs a native command with errors non-terminating; the caller checks $LASTEXITCODE.
function Invoke-Native([scriptblock]$Cmd) {
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $Cmd } finally { $ErrorActionPreference = $prev }
}

function Read-Tracked([string]$Name) {
  $file = Join-Path $DevDir "$Name.pid"
  if (-not (Test-Path $file)) { return $null }
  $parts = "$(Get-Content $file -TotalCount 1)".Trim() -split '\s+'
  $procId = 0; $ticks = [long]0
  if ($parts.Count -eq 2 -and [int]::TryParse($parts[0], [ref]$procId) -and [long]::TryParse($parts[1], [ref]$ticks)) {
    return [pscustomobject]@{ Id = $procId; Ticks = $ticks; File = $file }
  }
  Remove-Item $file -Force
  Write-Host "ignored unreadable .dev/$Name.pid (removed, nothing killed)"
  return $null
}

# Returns the live process only if PID, start time and command line all match what we started.
function Get-Tracked([string]$Name, [string]$Pattern) {
  $t = Read-Tracked $Name
  if (-not $t) { return $null }
  $proc = Get-Process -Id $t.Id -ErrorAction SilentlyContinue
  if ($proc) {
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($t.Id)" -ErrorAction SilentlyContinue
    try { $same = $proc.StartTime.ToUniversalTime().Ticks -eq $t.Ticks } catch { $same = $false }
    if ($same -and $cim -and $cim.CommandLine -match $Pattern) { return $proc }
    Write-Host "pid $($t.Id) from .dev/$Name.pid now belongs to another process (stale file removed, nothing killed)"
  }
  Remove-Item $t.File -Force
  return $null
}

function Stop-Tracked([string]$Name, [string]$Pattern) {
  $proc = Get-Tracked $Name $Pattern
  if (-not $proc) { return }
  Invoke-Native { & taskkill /PID $proc.Id /T /F *> $null }
  Remove-Item (Join-Path $DevDir "$Name.pid") -Force
  Write-Host "stopped $Name (pid $($proc.Id))"
}

function Assert-PortFree([int]$Port, [string]$Label) {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) {
    $owner = (Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    throw "Port $Port ($Label) is already in use by '$owner' (pid $($c.OwningProcess)). Free it and retry."
  }
}

function Start-Tracked([string]$Name, [string]$File, [string[]]$ProcArgs, [string]$Dir) {
  $p = Start-Process -FilePath $File -ArgumentList $ProcArgs -WorkingDirectory $Dir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $DevDir "$Name.log") -RedirectStandardError (Join-Path $DevDir "$Name.err.log")
  Set-Content -Path (Join-Path $DevDir "$Name.pid") -Value "$($p.Id) $($p.StartTime.ToUniversalTime().Ticks)"
  Write-Host "started $Name (pid $($p.Id)), logs in .dev/$Name*.log"
}

function Show-Tails([string]$Name) {
  foreach ($f in "$Name.log", "$Name.err.log") {
    $path = Join-Path $DevDir $f
    if (Test-Path $path) { Write-Host "--- tail of .dev/$f"; Get-Content $path -Tail 15 }
  }
}

function Wait-Url([string]$Name, [string]$Url) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $t = Read-Tracked $Name
    if (-not $t -or -not (Get-Process -Id $t.Id -ErrorAction SilentlyContinue)) {
      Show-Tails $Name; throw "$Name exited before answering at $Url"
    }
    try { if ((Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { return } } catch { }
    Start-Sleep -Seconds 1
  }
  Show-Tails $Name
  throw "$Name did not answer 200 at $Url within ${TimeoutSec}s"
}

# Host of DATABASE_URL (process env wins over the root .env). Never prints the URL.
function Get-DatabaseHost {
  $url = $env:DATABASE_URL
  $envFile = Join-Path $Root '.env'
  if (-not $url -and (Test-Path $envFile)) {
    $line = Get-Content $envFile | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -Last 1
    if ($line) { $url = ($line -replace '^\s*DATABASE_URL\s*=\s*', '').Trim().Trim('"', "'") }
  }
  if ($url -match '^[A-Za-z0-9+._-]+://(?:[^@/]*@)?(\[[^\]]+\]|[^:/?#]+)') { return $Matches[1] }
  return $null
}

$BackendPattern = 'uvicorn'
$FrontendPattern = 'npm.*run dev'

if ($Down -or $Reset) {
  New-Item -ItemType Directory -Force $DevDir | Out-Null
  Stop-Tracked 'frontend' $FrontendPattern; Stop-Tracked 'backend' $BackendPattern
  # --profile app so a backend container started with that profile is stopped/removed too.
  if ($Reset) { Invoke-Native { & docker compose --profile app down -v } } else { Invoke-Native { & docker compose --profile app stop } }
  exit $LASTEXITCODE
}

# Settings: real environment wins; otherwise the root .env; otherwise create it from the example.
if (-not $env:DATABASE_URL -and -not (Test-Path (Join-Path $Root '.env'))) {
  Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
  Write-Host 'Created .env from .env.example. Review it (ports, passwords) before relying on it.'
}
$dbHost = Get-DatabaseHost
if ($dbHost -notin @('127.0.0.1', 'localhost')) {
  if (-not $AllowRemoteDb) {
    throw 'DATABASE_URL is missing, unparseable or points to a non-local host. Refusing to run migrations or the backend against it. Use -AllowRemoteDb to override.'
  }
  Write-Warning 'DATABASE_URL points to a NON-LOCAL database and -AllowRemoteDb was given: migrations will run against it.'
}

New-Item -ItemType Directory -Force $DevDir | Out-Null
$backendUp = Get-Tracked 'backend' $BackendPattern
$frontendUp = Get-Tracked 'frontend' $FrontendPattern
if (-not $backendUp) { Assert-PortFree 8000 'backend' }
if (-not $frontendUp) { Assert-PortFree 5173 'frontend' }

$out = Invoke-Native { & docker compose up -d --wait db 2>&1 | ForEach-Object { "$_" } }
if ($LASTEXITCODE -ne 0) {
  $err = $out | Where-Object { $_ -match 'error|failed|denied|allocated|daemon|port' } | Select-Object -First 1
  throw "docker compose failed (exit $LASTEXITCODE): $err"
}
Write-Host 'db is healthy'

Push-Location (Join-Path $Root 'backend')
try {
  Invoke-Native { & uv sync }; if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
  Invoke-Native { & uv run alembic upgrade head }; if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }
} finally { Pop-Location }

if (-not (Test-Path (Join-Path $Root 'frontend/node_modules'))) {
  Push-Location (Join-Path $Root 'frontend')
  try { Invoke-Native { & npm ci }; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' } } finally { Pop-Location }
}

if ($backendUp) { Write-Host "backend already running (pid $($backendUp.Id))" } else {
  Start-Tracked 'backend' 'uv' @('run', 'uvicorn', 'eventssound.entrypoints.api.app:create_app', '--factory',
    '--reload', '--host', '127.0.0.1', '--port', '8000') (Join-Path $Root 'backend')
}
# Demo data is opt-in. Only -Mocks sets the flag (process environment, inherited by vite; never
# written to a file); a value inherited from the caller's shell is cleared so it cannot leak in.
if ($Mocks) { $env:VITE_USE_MOCKS = 'true' } else { Remove-Item Env:VITE_USE_MOCKS -ErrorAction SilentlyContinue }
if ($frontendUp) {
  Write-Host "frontend already running (pid $($frontendUp.Id))"
  if ($Mocks) { Write-Warning 'The running frontend keeps its old settings: run -Down first for -Mocks to take effect.' }
} else {
  # npm is npm.cmd on Windows; cmd.exe resolves it regardless of PowerShell script policy.
  Start-Tracked 'frontend' 'cmd.exe' @('/c', 'npm', 'run', 'dev', '--', '--host', 'localhost', '--port', '5173', '--strictPort') (Join-Path $Root 'frontend')
}

Wait-Url 'backend' "$BackendUrl/health"
Wait-Url 'backend' "$BackendUrl/health/db"
Wait-Url 'frontend' $FrontendUrl

Write-Host ''
Write-Host "Backend : $BackendUrl  (docs: $BackendUrl/docs)"
Write-Host "Frontend: $FrontendUrl$(if ($Mocks) { '  (demo data: VITE_USE_MOCKS=true)' })"
Write-Host 'Stop: scripts/dev.ps1 -Down   Reset db: scripts/dev.ps1 -Reset'

if ($Smoke) {
  & (Join-Path $PSScriptRoot 'smoke.ps1') -BackendUrl $BackendUrl -FrontendUrl $FrontendUrl -Origin $FrontendUrl
  exit $LASTEXITCODE
}
