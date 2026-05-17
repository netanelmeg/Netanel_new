<#
.SYNOPSIS
    Build the Azure Secret Monitor MSI installer.

.DESCRIPTION
    Requires WiX Toolset v3 (https://wixtoolset.org/releases/) with
    candle.exe and light.exe on PATH. Builds the EXEs first via
    Build-Exe.ps1, then compiles the WiX manifest into
    dist\AzureSecretMonitor.msi.

.PARAMETER Version
    Four-part product version (e.g. 1.2.3.0). Bumped on every release;
    the upgrade detection in the MSI relies on this monotonically
    increasing.

.PARAMETER SkipExeBuild
    Skip the PyInstaller step (use an existing dist\*.exe).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Build-Msi.ps1 -Version 1.0.0.0
#>

[CmdletBinding()]
param(
    [string]$Version = '1.0.0.0',
    [switch]$SkipExeBuild
)

$ErrorActionPreference = 'Stop'

foreach ($tool in 'candle.exe','light.exe') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool not found on PATH. Install WiX Toolset v3 from https://wixtoolset.org/releases/."
    }
}

if (-not $SkipExeBuild) {
    & "$PSScriptRoot\Build-Exe.ps1"
}

$repo = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $repo 'dist'
if (-not (Test-Path (Join-Path $dist 'AzureSecretMonitor.exe'))) {
    throw "dist\AzureSecretMonitor.exe not found. Run Build-Exe.ps1 first."
}

Push-Location $PSScriptRoot
try {
    $wixObj = Join-Path $env:TEMP 'AzureSecretMonitor.wixobj'
    $wixPdb = Join-Path $env:TEMP 'AzureSecretMonitor.wixpdb'

    Write-Host "Compiling WiX manifest (v$Version)..." -ForegroundColor Cyan
    & candle.exe installer.wxs `
        -dProductVersion=$Version `
        -dDistDir=$dist `
        -out $wixObj

    $msiPath = Join-Path $dist 'AzureSecretMonitor.msi'
    Write-Host "Linking MSI to $msiPath..." -ForegroundColor Cyan
    & light.exe $wixObj `
        -ext WixUIExtension `
        -out $msiPath `
        -pdbout $wixPdb

    Remove-Item -ErrorAction SilentlyContinue $wixObj, $wixPdb

    Write-Host ""
    Write-Host "Built $msiPath" -ForegroundColor Green
}
finally {
    Pop-Location
}
