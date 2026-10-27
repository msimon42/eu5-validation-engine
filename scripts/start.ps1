param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Tools = Join-Path $ProjectRoot '.tools'
New-Item -ItemType Directory -Force -Path $Tools | Out-Null
$Architecture = if (($env:PROCESSOR_ARCHITECTURE -match 'ARM64') -or ($env:PROCESSOR_ARCHITEW6432 -match 'ARM64')) { 'arm64' } else { 'x64' }

function Get-VerifiedArchive([string]$Url, [string]$ChecksumsUrl, [string]$Filename, [string]$Destination) {
    $Archive = Join-Path $Tools $Filename
    Write-Host "Downloading $Filename ..."
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Archive
    $Checksums = (Invoke-WebRequest -UseBasicParsing -Uri $ChecksumsUrl).Content
    $Line = ($Checksums -split "`n" | Where-Object { $_ -match [regex]::Escape($Filename) } | Select-Object -First 1)
    if (-not $Line) { $Line = $Checksums.Trim() }
    $Expected = [regex]::Match($Line, '(?i)[a-f0-9]{64}').Value.ToLowerInvariant()
    $Actual = (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLowerInvariant()
    if ((-not $Expected) -or $Expected -ne $Actual) { throw "Checksum verification failed for $Filename" }
    Expand-Archive -Path $Archive -DestinationPath $Destination -Force
    Remove-Item $Archive
}

# All downloaded tools, environments, caches and app state stay in this clone.
$Uv = Join-Path $Tools 'uv\uv.exe'
if (-not (Test-Path $Uv)) {
    $UvTarget = if ($Architecture -eq 'arm64') { 'aarch64' } else { 'x86_64' }
    $UvArchive = "uv-$UvTarget-pc-windows-msvc.zip"
    $UvRelease = 'https://github.com/astral-sh/uv/releases/download/0.13.6'
    Get-VerifiedArchive "$UvRelease/$UvArchive" "$UvRelease/$UvArchive.sha256" $UvArchive (Join-Path $Tools 'uv')
    if (-not (Test-Path $Uv)) { throw 'The downloaded uv archive did not contain uv.exe' }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools 'python'
$env:UV_CACHE_DIR = Join-Path $ProjectRoot '.cache\uv'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $ProjectRoot '.venv'
Write-Host 'Preparing locked Python environment ...'
& $Uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Python dependency setup failed' }

$NodeVersion = '22.22.0'
$NodeDirectory = Join-Path $Tools "node-v$NodeVersion-win-$Architecture"
if (-not (Test-Path (Join-Path $NodeDirectory 'node.exe'))) {
    $NodeArchive = "node-v$NodeVersion-win-$Architecture.zip"
    $NodeRelease = "https://nodejs.org/dist/v$NodeVersion"
    Get-VerifiedArchive "$NodeRelease/$NodeArchive" "$NodeRelease/SHASUMS256.txt" $NodeArchive $Tools
}
$env:PATH = "$NodeDirectory;$env:PATH"
$Npm = Join-Path $NodeDirectory 'npm.cmd'
$LockHash = (Get-FileHash (Join-Path $ProjectRoot 'frontend\package-lock.json') -Algorithm SHA256).Hash
$Marker = Join-Path $Tools 'frontend-lock.sha256'
Push-Location (Join-Path $ProjectRoot 'frontend')
try {
    if ((-not (Test-Path 'node_modules')) -or (-not (Test-Path $Marker)) -or (Get-Content $Marker -Raw).Trim() -ne $LockHash) {
        Write-Host 'Preparing locked frontend dependencies ...'
        & $Npm ci --include=dev --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency setup failed' }
        Set-Content -Path $Marker -Value $LockHash
    }
    Write-Host 'Building local workbench ...'
    & $Npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }

$Url = "http://127.0.0.1:$Port"
Write-Host "Starting EU5 Mod Engine at $Url"
Write-Host 'State stays in .workspace. Press Ctrl+C to stop. No game installation is modified.'
$BrowserJob = $null
if (-not $NoBrowser) {
    $BrowserJob = Start-Job -ArgumentList $Url -ScriptBlock {
        param($Target)
        for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
            try {
                Invoke-WebRequest -UseBasicParsing -Uri "$Target/api/health" -TimeoutSec 1 | Out-Null
                Start-Process $Target
                break
            } catch { Start-Sleep -Seconds 1 }
        }
    }
}
try {
    & $Uv run --frozen eu5 serve --data-dir (Join-Path $ProjectRoot '.workspace') --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'The application stopped with an error' }
} finally {
    if ($BrowserJob) { Stop-Job $BrowserJob -ErrorAction SilentlyContinue; Remove-Job $BrowserJob -Force -ErrorAction SilentlyContinue }
}
