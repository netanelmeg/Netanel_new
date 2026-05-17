<#
.SYNOPSIS
    Build Azure Secret Monitor executables with PyInstaller.

.DESCRIPTION
    Produces:
        dist\AzureSecretMonitor.exe     (windowed GUI)
        dist\AzureSecretMonitorCli.exe  (console CLI)
    Run from any working directory; output is relative to the repo root.

.PARAMETER PythonPath
    Path to python.exe. Defaults to whatever is on PATH.

.PARAMETER Clean
    Remove existing build/dist folders before building.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Build-Exe.ps1
#>

[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

if (-not $PythonPath) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { throw 'python.exe not found on PATH. Pass -PythonPath.' }
    $PythonPath = $cmd.Source
}

$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    if ($Clean) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
    }

    Write-Host "Installing build dependencies..." -ForegroundColor Cyan
    & $PythonPath -m pip install --upgrade pip pyinstaller
    & $PythonPath -m pip install -r python\requirements.txt

    Write-Host "Running PyInstaller..." -ForegroundColor Cyan
    & $PythonPath -m PyInstaller `
        --noconfirm `
        --distpath dist `
        --workpath build `
        windows\AzureSecretMonitor.spec

    $gui = Resolve-Path dist\AzureSecretMonitor.exe
    $cli = Resolve-Path dist\AzureSecretMonitorCli.exe
    Write-Host ""
    Write-Host "Built:" -ForegroundColor Green
    Write-Host "  $gui"
    Write-Host "  $cli"
}
finally {
    Pop-Location
}
