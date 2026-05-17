<#
.SYNOPSIS
    Register a Windows Scheduled Task that runs the Azure Secret Monitor CLI.

.DESCRIPTION
    Registers (or replaces) a daily Scheduled Task named "AzureSecretMonitor"
    that runs python.exe cli.py under the current user. The task uses the
    encrypted config saved by the GUI (in %APPDATA%\AzureSecretMonitor).

.PARAMETER PythonPath
    Full path to python.exe. Defaults to the first python on PATH.

.PARAMETER Time
    Daily run time, HH:mm. Default: 08:00.

.PARAMETER TaskName
    Name of the Scheduled Task. Default: AzureSecretMonitor.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Install-ScheduledTask.ps1 -Time 07:30
#>

[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$Time = '08:00',
    [string]$TaskName = 'AzureSecretMonitor'
)

$ErrorActionPreference = 'Stop'

# Pick CLI runner: prefer the bundled EXE (MSI install), fall back to
# python.exe + cli.py (source layout).
$cliExe = Join-Path $PSScriptRoot 'AzureSecretMonitorCli.exe'
if (Test-Path $cliExe) {
    $execute = $cliExe
    $arguments = $null
    $workDir = Split-Path -Parent $cliExe
} else {
    if (-not $PythonPath) {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $cmd) { throw 'python.exe not found on PATH. Pass -PythonPath explicitly.' }
        $PythonPath = $cmd.Source
    }
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $cliScript = Join-Path $repoRoot 'python\cli.py'
    if (-not (Test-Path $cliScript)) { throw "cli.py not found at $cliScript" }
    $execute = $PythonPath
    $arguments = "`"$cliScript`""
    $workDir = Split-Path -Parent $cliScript
}

$logDir  = Join-Path $env:ProgramData 'AzureSecretMonitor\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

if ($arguments) {
    $action = New-ScheduledTaskAction -Execute $execute -Argument $arguments -WorkingDirectory $workDir
} else {
    $action = New-ScheduledTaskAction -Execute $execute -WorkingDirectory $workDir
}

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Scans Azure for expiring secrets and sends notifications.'

Write-Host "Scheduled Task '$TaskName' registered. Runs daily at $Time as $env:USERNAME." -ForegroundColor Green
Write-Host "Logs: $logFile"
