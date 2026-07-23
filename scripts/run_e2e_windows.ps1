[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $projectRoot "frontend"
$validationRoot = Join-Path $projectRoot "dist\validation"
$canonicalDatabase = Join-Path $projectRoot "backend\sigra.db"
$packageLock = Join-Path $frontendRoot "package-lock.json"
$nodeModules = Join-Path $frontendRoot "node_modules"
$backendPort = 8010
$frontendPort = 4183
$runId = "windows-{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), $PID
$temporaryDatabase = Join-Path $projectRoot "tmp\sigra-e2e-$runId.db"
$startedAt = Get-Date
$testLog = Join-Path $validationRoot "e2e-windows.log"
$reportPath = Join-Path $validationRoot "e2e-local-report.json"
$testExitCode = 1
$portsReleased = $false

function Get-ListeningProcesses {
    param([int[]]$Ports)
    return @(
        Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in $Ports } |
            Select-Object LocalAddress, LocalPort, OwningProcess
    )
}

function Wait-PortsReleased {
    param(
        [int[]]$Ports,
        [int]$MaxAttempts = 20,
        [int]$BaseDelayMilliseconds = 250
    )
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        if ((Get-ListeningProcesses -Ports $Ports).Count -eq 0) {
            return $true
        }
        if ($attempt -lt $MaxAttempts) {
            $delay = [math]::Min($BaseDelayMilliseconds * $attempt, 1000)
            Start-Sleep -Milliseconds $delay
        }
    }
    return $false
}

function Get-CanonicalSnapshot {
    param(
        [string]$Python,
        [string]$DatabasePath
    )
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $DatabasePath).Hash.ToLowerInvariant()
    $code = @"
import json
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    counts = {
        'vehicles': connection.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0],
        'motorcycles': connection.execute('SELECT COUNT(*) FROM motorcycles').fetchone()[0],
    }
print(json.dumps(counts))
"@
    $counts = (& $Python -c $code $DatabasePath | ConvertFrom-Json)
    return [ordered]@{
        sha256 = $hash
        size_bytes = (Get-Item -LiteralPath $DatabasePath).Length
        vehicles = $counts.vehicles
        motorcycles = $counts.motorcycles
    }
}

function Restore-EnvironmentValue {
    param(
        [string]$Name,
        [AllowNull()][string]$Value
    )
    if ($null -eq $Value) {
        Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
    } else {
        Set-Item "Env:$Name" $Value
    }
}

New-Item -ItemType Directory -Force -Path $validationRoot | Out-Null

$node = (Get-Command node -ErrorAction Stop).Source
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$npx = (Get-Command npx.cmd -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $packageLock)) {
    throw "frontend/package-lock.json nao encontrado."
}

$pythonCandidates = @(
    (Join-Path $projectRoot ".venv-validation\Scripts\python.exe"),
    (Join-Path $projectRoot "backend\.venv\Scripts\python.exe")
)
$python = $pythonCandidates |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $python) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

Push-Location $frontendRoot
try {
    if (-not (Test-Path -LiteralPath $nodeModules)) {
        & $npm ci
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci falhou com exit code $LASTEXITCODE."
        }
    } else {
        & $npm ls --depth=0 *> $null
        if ($LASTEXITCODE -ne 0) {
            & $npm ci
            if ($LASTEXITCODE -ne 0) {
                throw "node_modules incompativel e npm ci falhou com exit code $LASTEXITCODE."
            }
        }
    }

    $chromiumPath = (& $node -e "const { chromium } = require('playwright'); console.log(chromium.executablePath())").Trim()
    if (-not (Test-Path -LiteralPath $chromiumPath)) {
        & $npx playwright install chromium
        if ($LASTEXITCODE -ne 0) {
            throw "A instalacao do Chromium falhou com exit code $LASTEXITCODE."
        }
        $chromiumPath = (& $node -e "const { chromium } = require('playwright'); console.log(chromium.executablePath())").Trim()
    }
    if (-not (Test-Path -LiteralPath $chromiumPath)) {
        throw "Executavel do Chromium nao encontrado apos a instalacao."
    }

    $listenersBefore = Get-ListeningProcesses -Ports @($backendPort, $frontendPort)
    if ($listenersBefore.Count -gt 0) {
        throw "As portas E2E 8010/4183 ja estao em uso. Encerre o processo listado antes de continuar."
    }

    $canonicalBefore = Get-CanonicalSnapshot -Python $python -DatabasePath $canonicalDatabase
    $databaseExistedBefore = Test-Path -LiteralPath $temporaryDatabase
    $previousRunId = $env:SIGRA_E2E_RUN_ID
    $previousPython = $env:SIGRA_PYTHON_BIN
    $previousBackendPort = $env:SIGRA_E2E_BACKEND_PORT
    $previousFrontendPort = $env:SIGRA_E2E_FRONTEND_PORT
    $previousFipe = $env:FIPE_AUTO_REFRESH

    $env:SIGRA_E2E_RUN_ID = $runId
    $env:SIGRA_PYTHON_BIN = $python
    $env:SIGRA_E2E_BACKEND_PORT = [string]$backendPort
    $env:SIGRA_E2E_FRONTEND_PORT = [string]$frontendPort
    $env:FIPE_AUTO_REFRESH = "false"

    $transcriptStarted = $false
    try {
        Start-Transcript -LiteralPath $testLog -Force | Out-Null
        $transcriptStarted = $true
        & $npm run test:e2e
        $testExitCode = $LASTEXITCODE
    } finally {
        if ($transcriptStarted) {
            Stop-Transcript | Out-Null
        }
        Restore-EnvironmentValue -Name "SIGRA_E2E_RUN_ID" -Value $previousRunId
        Restore-EnvironmentValue -Name "SIGRA_PYTHON_BIN" -Value $previousPython
        Restore-EnvironmentValue -Name "SIGRA_E2E_BACKEND_PORT" -Value $previousBackendPort
        Restore-EnvironmentValue -Name "SIGRA_E2E_FRONTEND_PORT" -Value $previousFrontendPort
        Restore-EnvironmentValue -Name "FIPE_AUTO_REFRESH" -Value $previousFipe
    }

    $portsReleased = Wait-PortsReleased -Ports @($backendPort, $frontendPort)
    $temporaryDatabaseArtifacts = @(
        $temporaryDatabase,
        "$temporaryDatabase-wal",
        "$temporaryDatabase-shm"
    )
    $remainingTemporaryArtifacts = @(
        $temporaryDatabaseArtifacts |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    )

    $canonicalAfter = Get-CanonicalSnapshot -Python $python -DatabasePath $canonicalDatabase
    $canonicalPreserved = (
        $canonicalBefore.sha256 -eq $canonicalAfter.sha256 -and
        $canonicalBefore.vehicles -eq $canonicalAfter.vehicles -and
        $canonicalBefore.motorcycles -eq $canonicalAfter.motorcycles
    )
    $finishedAt = Get-Date
    $logText = if (Test-Path -LiteralPath $testLog) {
        Get-Content -LiteralPath $testLog -Raw
    } else {
        ""
    }
    $passedMatch = [regex]::Match($logText, "(\d+)\s+passed")
    $failedMatch = [regex]::Match($logText, "(\d+)\s+failed")
    $skippedMatch = [regex]::Match($logText, "(\d+)\s+skipped")
    $report = [ordered]@{
        generated_at = $finishedAt.ToUniversalTime().ToString("o")
        status = if ($testExitCode -eq 0 -and $portsReleased -and $canonicalPreserved) { "passed" } else { "failed" }
        command = "npm run test:e2e"
        started_at = $startedAt.ToUniversalTime().ToString("o")
        finished_at = $finishedAt.ToUniversalTime().ToString("o")
        duration_seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
        exit_code = $testExitCode
        node_version = (& $node --version).Trim()
        npm_version = (& $npm --version).Trim()
        playwright_version = (Get-Content -LiteralPath (Join-Path $nodeModules "playwright\package.json") -Raw | ConvertFrom-Json).version
        chromium_path = $chromiumPath
        tests_discovered = 5
        tests_passed = if ($passedMatch.Success) { [int]$passedMatch.Groups[1].Value } else { 0 }
        tests_failed = if ($failedMatch.Success) { [int]$failedMatch.Groups[1].Value } else { 0 }
        tests_skipped = if ($skippedMatch.Success) { [int]$skippedMatch.Groups[1].Value } else { 0 }
        temporary_database = [ordered]@{
            relative_path = "tmp/sigra-e2e-$runId.db"
            existed_before = $databaseExistedBefore
            exists_after = $remainingTemporaryArtifacts.Count -gt 0
            remaining_artifacts = @(
                $remainingTemporaryArtifacts |
                    ForEach-Object { Split-Path -Leaf $_ }
            )
        }
        canonical_database = [ordered]@{
            preserved = $canonicalPreserved
            before = $canonicalBefore
            after = $canonicalAfter
        }
        backend_port = $backendPort
        frontend_port = $frontendPort
        ports_released = $portsReleased
        fipe_external_refresh = false
        artifacts_directory = "frontend/test-results/e2e"
        log = "dist/validation/e2e-windows.log"
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8

    if ($testExitCode -ne 0) {
        exit $testExitCode
    }
    if (
        -not $portsReleased -or
        -not $canonicalPreserved -or
        $remainingTemporaryArtifacts.Count -gt 0
    ) {
        exit 1
    }
    exit 0
} finally {
    Pop-Location
}
