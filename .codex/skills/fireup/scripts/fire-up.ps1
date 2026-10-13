[CmdletBinding()]
param(
    [ValidateRange(30, 900)]
    [int]$StartupTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$dashboardUrl = "http://localhost:5173"
$apiUrl = "http://127.0.0.1:8000"
$dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
$dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"
$composeAttempted = $false
$nativeMode = $false

# A long-running Codex session may keep the PATH it had before Docker Desktop was
# installed. Make the newly installed CLI immediately available in that session.
if (-not (Get-Command docker -ErrorAction SilentlyContinue) -and
    (Test-Path -LiteralPath (Join-Path $dockerBin "docker.exe"))) {
    $env:Path = "$dockerBin;$env:Path"
}

function Test-DockerEngine {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = (Get-Command docker).Source
    $startInfo.Arguments = 'info --format "{{json .ServerVersion}}"'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $null = $process.Start()
    if (-not $process.WaitForExit(5000)) {
        $process.Kill()
        return $false
    }

    return $process.ExitCode -eq 0
}

function Wait-ForCondition {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Condition,
        [Parameter(Mandatory)]
        [string]$Description,
        [Parameter(Mandatory)]
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (& $Condition) {
            return
        }
        Start-Sleep -Seconds 2
    }

    throw "Timed out after $TimeoutSeconds seconds waiting for $Description."
}

function Test-HttpEndpoint {
    param([Parameter(Mandatory)][string]$Uri)

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Test-PendingWindowsRestart {
    return (
        (Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending") -or
        (Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired") -or
        $null -ne (Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue)
    )
}

function Stop-ProcessTree {
    param([Parameter(Mandatory)][int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId $child.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-ProjectNativeStack {
    $runDirectory = Join-Path $repositoryRoot "artifacts\fireup"
    foreach ($pidFile in @("api.pid", "dashboard.pid")) {
        $pidPath = Join-Path $runDirectory $pidFile
        if (-not (Test-Path -LiteralPath $pidPath)) {
            continue
        }

        $storedPid = [int](Get-Content -LiteralPath $pidPath)
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $storedPid" -ErrorAction SilentlyContinue
        $ownedByProject = $process -and (
            $process.ExecutablePath -like "$repositoryRoot*" -or
            $process.CommandLine -like "*$repositoryRoot*"
        )
        if ($ownedByProject) {
            Stop-ProcessTree -ProcessId $storedPid
        }
        Remove-Item -LiteralPath $pidPath -Force
    }
}

function Start-NativeStack {
    $python = Join-Path $repositoryRoot ".venv\python.exe"
    $alembic = Join-Path $repositoryRoot ".venv\Scripts\alembic.exe"
    $npm = Join-Path $repositoryRoot ".venv\npm.cmd"
    $dashboardDirectory = Join-Path $repositoryRoot "dashboard"
    $nodeModules = Join-Path $dashboardDirectory "node_modules"
    $runDirectory = Join-Path $repositoryRoot "artifacts\fireup"

    foreach ($requiredPath in @($python, $alembic, $npm, $nodeModules)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Docker needs a Windows restart, and the native fallback is missing '$requiredPath'. Restart Windows, then run `$fireup again."
        }
    }

    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    $databasePath = (Join-Path $repositoryRoot "artifacts\local.db").Replace("\", "/")
    $previousDatabaseUrl = $env:DATABASE_URL
    $previousPath = $env:Path
    $env:DATABASE_URL = "sqlite+pysqlite:///$databasePath"
    $env:DASHBOARD_ORIGIN = $dashboardUrl
    $env:VITE_API_BASE_URL = $apiUrl
    $env:Path = "$(Join-Path $repositoryRoot '.venv');$env:Path"

    try {
        Write-Host "Docker needs a Windows restart; starting the installed native toolchain for this session..."
        & $alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "The local database migration failed with exit code $LASTEXITCODE."
        }

        if (-not (Test-HttpEndpoint "$apiUrl/ready")) {
            $apiProcess = Start-Process -FilePath $python `
                -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000") `
                -WorkingDirectory $repositoryRoot `
                -RedirectStandardOutput (Join-Path $runDirectory "api.stdout.log") `
                -RedirectStandardError (Join-Path $runDirectory "api.stderr.log") `
                -WindowStyle Hidden `
                -PassThru
            Set-Content -LiteralPath (Join-Path $runDirectory "api.pid") -Value $apiProcess.Id
        }

        if (-not (Test-HttpEndpoint $dashboardUrl)) {
            $dashboardProcess = Start-Process -FilePath $npm `
                -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort") `
                -WorkingDirectory $dashboardDirectory `
                -RedirectStandardOutput (Join-Path $runDirectory "dashboard.stdout.log") `
                -RedirectStandardError (Join-Path $runDirectory "dashboard.stderr.log") `
                -WindowStyle Hidden `
                -PassThru
            Set-Content -LiteralPath (Join-Path $runDirectory "dashboard.pid") -Value $dashboardProcess.Id
        }
    }
    finally {
        $env:DATABASE_URL = $previousDatabaseUrl
        $env:Path = $previousPath
    }
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand -and (Test-DockerEngine)) {
    Stop-ProjectNativeStack
}
elseif (-not $dockerCommand) {
    if (Test-PendingWindowsRestart) {
        $nativeMode = $true
    }
    else {
        throw "Docker is not installed. Install Docker Desktop, then run `$fireup again."
    }
}
elseif (-not (Test-Path -LiteralPath $dockerDesktop)) {
    throw "Docker Desktop is installed incompletely or cannot be found at '$dockerDesktop'."
}
else {
    Stop-ProjectNativeStack
    Write-Host "Starting Docker Desktop..."
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    try {
        Wait-ForCondition -Description "the Docker engine" -TimeoutSeconds $StartupTimeoutSeconds -Condition { Test-DockerEngine }
    }
    catch {
        if (-not (Test-PendingWindowsRestart)) {
            throw
        }
        $nativeMode = $true
    }
}

Push-Location $repositoryRoot
try {
    if (-not (Test-Path -LiteralPath ".env")) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
        Write-Host "Created .env from .env.example."
    }

    if ($nativeMode) {
        Start-NativeStack
    }
    else {
        Write-Host "Building and starting Workstation Test Lab..."
        $composeAttempted = $true
        & docker compose up --build --detach
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up failed with exit code $LASTEXITCODE."
        }
    }

    Wait-ForCondition -Description "the API database readiness check" -TimeoutSeconds $StartupTimeoutSeconds -Condition {
        Test-HttpEndpoint "$apiUrl/ready"
    }
    Wait-ForCondition -Description "the dashboard" -TimeoutSeconds $StartupTimeoutSeconds -Condition {
        Test-HttpEndpoint $dashboardUrl
    }

    Write-Host ""
    Write-Host "Workstation Test Lab is ready."
    Write-Host "Dashboard: $dashboardUrl"
    Write-Host "API docs:  $apiUrl/docs"
}
catch {
    if ($composeAttempted) {
        Write-Host ""
        Write-Host "Current service state:"
        & docker compose ps
    }
    throw
}
finally {
    Pop-Location
}
