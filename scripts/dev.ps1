<#
.SYNOPSIS
  Hybrid local development: Postgres in Docker, backend and frontend native with hot reload.
.DESCRIPTION
  dev.ps1          start (idempotent): db, migrations, uvicorn --reload, vite
  dev.ps1 -Down    stop the two processes and the db container (keeps the volume)
  dev.ps1 -Reset   -Down plus drop the db volume
  dev.ps1 -Smoke   run scripts/smoke.ps1 after start
  Settings come from the process environment or the root .env (copied from .env.example
  when neither exists). Secrets are never printed. Logs and PIDs live in .dev/.
#>
[CmdletBinding()]
param([switch]$Down, [switch]$Reset, [switch]$Smoke, [int]$TimeoutSec = 90)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$DevDir = Join-Path $Root '.dev'
$BackendUrl = 'http://127.0.0.1:8000'
$FrontendUrl = 'http://127.0.0.1:5173'
Set-Location $Root

function Stop-Tracked([string]$Name) {
  $pidFile = Join-Path $DevDir "$Name.pid"
  if (-not (Test-Path $pidFile)) { return }
  $procId = [int](Get-Content $pidFile -TotalCount 1)
  if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
    & taskkill /PID $procId /T /F *> $null
    Write-Host "stopped $Name (pid $procId)"
  }
  Remove-Item $pidFile -Force
}

function Start-Tracked([string]$Name, [string]$File, [string[]]$ProcArgs, [string]$Dir) {
  $pidFile = Join-Path $DevDir "$Name.pid"
  if (Test-Path $pidFile) {
    $existing = Get-Process -Id ([int](Get-Content $pidFile -TotalCount 1)) -ErrorAction SilentlyContinue
    if ($existing) { Write-Host "$Name already running (pid $($existing.Id))"; return }
  }
  $p = Start-Process -FilePath $File -ArgumentList $ProcArgs -WorkingDirectory $Dir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $DevDir "$Name.log") -RedirectStandardError (Join-Path $DevDir "$Name.err.log")
  Set-Content -Path $pidFile -Value $p.Id
  Write-Host "started $Name (pid $($p.Id)), logs in .dev/$Name*.log"
}

function Wait-Url([string]$Name, [string]$Url) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      if ((Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { return }
    } catch { Start-Sleep -Seconds 1 }
  }
  foreach ($f in "$Name.log", "$Name.err.log") {
    $path = Join-Path $DevDir $f
    if (Test-Path $path) { Write-Host "--- tail of .dev/$f"; Get-Content $path -Tail 15 }
  }
  throw "$Name did not answer 200 at $Url within ${TimeoutSec}s"
}

if ($Down -or $Reset) {
  Stop-Tracked 'frontend'; Stop-Tracked 'backend'
  if ($Reset) { & docker compose down -v } else { & docker compose stop db }
  exit $LASTEXITCODE
}

# Settings: real environment wins; otherwise the root .env; otherwise create it from the example.
if (-not $env:DATABASE_URL -and -not (Test-Path (Join-Path $Root '.env'))) {
  Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
  Write-Host 'Created .env from .env.example. Review it (ports, passwords) before relying on it.'
}
New-Item -ItemType Directory -Force $DevDir | Out-Null

& docker compose up -d --wait db
if ($LASTEXITCODE -ne 0) { throw 'docker compose failed: is Docker Desktop running?' }

Push-Location (Join-Path $Root 'backend')
try {
  & uv sync; if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
  & uv run alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }
} finally { Pop-Location }

if (-not (Test-Path (Join-Path $Root 'frontend/node_modules'))) {
  Push-Location (Join-Path $Root 'frontend')
  try { & npm ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' } } finally { Pop-Location }
}

Start-Tracked 'backend' 'uv' @('run', 'uvicorn', 'eventssound.entrypoints.api.app:create_app', '--factory',
  '--reload', '--host', '127.0.0.1', '--port', '8000') (Join-Path $Root 'backend')
# npm is npm.cmd on Windows; cmd.exe resolves it without depending on PowerShell script policy.
Start-Tracked 'frontend' 'cmd.exe' @('/c', 'npm', 'run', 'dev', '--', '--host', '127.0.0.1') (Join-Path $Root 'frontend')

Wait-Url 'backend' "$BackendUrl/health"
Wait-Url 'backend' "$BackendUrl/health/db"
Wait-Url 'frontend' $FrontendUrl

Write-Host ''
Write-Host "Backend : $BackendUrl  (docs: $BackendUrl/docs)"
Write-Host "Frontend: $FrontendUrl"
Write-Host 'Stop: scripts/dev.ps1 -Down   Reset db: scripts/dev.ps1 -Reset'

if ($Smoke) {
  & (Join-Path $PSScriptRoot 'smoke.ps1') -BackendUrl $BackendUrl -FrontendUrl $FrontendUrl
  exit $LASTEXITCODE
}
