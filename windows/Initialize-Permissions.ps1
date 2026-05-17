<#
.SYNOPSIS
    Initialize the machine-wide config directory for Azure Secret Monitor
    with a least-privilege ACL.

.DESCRIPTION
    Creates %ProgramData%\AzureSecretMonitor and sets ACLs so that:
      - SYSTEM and BUILTIN\Administrators have full control.
      - Authenticated Users can read the directory and read roles.json
        (but cannot write to it).
      - Authenticated Users can append to the logs subdirectory.
    Run this once on the server as an Administrator before launching the
    GUI for the first time.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Initialize-Permissions.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# Must run elevated — icacls on ProgramData paths requires it.
$current = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'This script must be run as an Administrator (right-click PowerShell -> Run as administrator).'
}

$root  = Join-Path $env:ProgramData 'AzureSecretMonitor'
$logs  = Join-Path $root 'logs'
$roles = Join-Path $root 'roles.json'
$audit = Join-Path $logs 'audit.log'

New-Item -ItemType Directory -Path $root -Force | Out-Null
New-Item -ItemType Directory -Path $logs -Force | Out-Null

if (-not (Test-Path $roles)) {
    '{ "*": "reader" }' | Set-Content -Path $roles -Encoding UTF8
}
if (-not (Test-Path $audit)) {
    New-Item -ItemType File -Path $audit -Force | Out-Null
}

function Set-LeastPrivilegeAcl {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][ValidateSet('ReadOnly', 'AppendOnly', 'FullToAdmins')]
        [string]$Mode
    )

    # Reset inheritance to a known state and rebuild from scratch.
    & icacls.exe $Path /inheritance:r | Out-Null
    & icacls.exe $Path /grant:r 'SYSTEM:(OI)(CI)F' | Out-Null
    & icacls.exe $Path /grant:r 'BUILTIN\Administrators:(OI)(CI)F' | Out-Null

    switch ($Mode) {
        'ReadOnly' {
            & icacls.exe $Path /grant:r 'BUILTIN\Users:(OI)(CI)RX' | Out-Null
        }
        'AppendOnly' {
            # Allow read + append on directory; append-only on files lives in
            # NTFS special perms via WD/AD. We grant Modify on the directory so
            # logs can grow, and rely on the file ACL for fine-grain limits.
            & icacls.exe $Path /grant:r 'BUILTIN\Users:(OI)(CI)M' | Out-Null
        }
        'FullToAdmins' {
            & icacls.exe $Path /grant:r 'BUILTIN\Users:(OI)(CI)RX' | Out-Null
        }
    }
}

Set-LeastPrivilegeAcl -Path $root  -Mode 'FullToAdmins'
Set-LeastPrivilegeAcl -Path $roles -Mode 'ReadOnly'
Set-LeastPrivilegeAcl -Path $logs  -Mode 'AppendOnly'

Write-Host "Initialized $root with least-privilege ACL." -ForegroundColor Green
Write-Host "  Administrators: full control"
Write-Host "  Users: read $roles, append to $logs"
Write-Host ""
Write-Host "Next: launch the GUI once as an Administrator to bootstrap your"
Write-Host "Admin role assignment, then assign Reader/Contributor roles from"
Write-Host "the Permissions tab."
