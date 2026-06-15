<#
.SYNOPSIS
    Register a Windows Scheduled Task that runs the mdconvert Telegram bot
    continuously (always-on, auto-restart, survives reboots).

.DESCRIPTION
    Registers (or replaces) a Scheduled Task named "MdConvertBot" that runs
    `python -m mdconvert.bot` under the current user. Unlike the secret-monitor
    task (which runs once a day), this task is long-running: it starts at boot
    and at logon, restarts automatically if it stops, and has no execution time
    limit.

    The bot reads its token from the TELEGRAM_BOT_TOKEN environment variable.
    This script stores the token as a *User* environment variable for the
    account that runs the task (so it is not written into the task definition
    in clear text), and validates it against Telegram's getMe API first.

.PARAMETER Token
    Your Telegram bot token (from @BotFather). If omitted you'll be prompted
    for it securely.

.PARAMETER PythonPath
    Full path to python.exe. Defaults to the first python on PATH.

.PARAMETER TaskName
    Name of the Scheduled Task. Default: MdConvertBot.

.PARAMETER RunOnlyWhenLoggedOn
    Run the task only while this user is interactively logged on (simpler, but
    the bot stops when you log off). By default the task runs whether or not
    the user is logged on (S4U).

.PARAMETER SkipValidation
    Skip the getMe token check (e.g. if the install host has no Internet).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Install-Bot-ScheduledTask.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Install-Bot-ScheduledTask.ps1 -Token "123456:ABC-DEF..."

.NOTES
    To remove later:  Unregister-ScheduledTask -TaskName MdConvertBot -Confirm:$false
    Live log:         %ProgramData%\MdConvertBot\logs\bot.log
#>

[CmdletBinding()]
param(
    [string]$Token,
    [string]$PythonPath,
    [string]$TaskName = 'MdConvertBot',
    [switch]$RunOnlyWhenLoggedOn,
    [switch]$SkipValidation
)

$ErrorActionPreference = 'Stop'

# --- Resolve python + the package directory ------------------------------- #
if (-not $PythonPath) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { throw 'python.exe not found on PATH. Pass -PythonPath explicitly.' }
    $PythonPath = $cmd.Source
}
$repoRoot  = Split-Path -Parent $PSScriptRoot
$pythonDir = Join-Path $repoRoot 'python'
if (-not (Test-Path (Join-Path $pythonDir 'mdconvert'))) {
    throw "mdconvert package not found under $pythonDir"
}

# --- Get the token -------------------------------------------------------- #
if (-not $Token) {
    $secure = Read-Host -AsSecureString -Prompt 'Paste your Telegram bot token (from @BotFather)'
    $bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try   { $Token = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
$Token = $Token.Trim()
if (-not $Token) { throw 'No token provided.' }

# --- Validate the token (getMe) ------------------------------------------- #
if (-not $SkipValidation) {
    try {
        $me = Invoke-RestMethod -Uri "https://api.telegram.org/bot$Token/getMe" -TimeoutSec 15
        if (-not $me.ok) { throw 'Telegram getMe returned ok=false.' }
        Write-Host "Token OK - bot @$($me.result.username) (id $($me.result.id))." -ForegroundColor Green
    } catch {
        throw "Token validation failed: $($_.Exception.Message). Use -SkipValidation to bypass."
    }
}

# --- Persist the token for the task's user -------------------------------- #
[Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', $Token, 'User')
$env:TELEGRAM_BOT_TOKEN = $Token   # current session too
Write-Host "Stored TELEGRAM_BOT_TOKEN in the user environment for $env:USERNAME." -ForegroundColor Green

# --- Build the action (wrap in cmd to capture a log) ---------------------- #
$logDir  = Join-Path $env:ProgramData 'MdConvertBot\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir 'bot.log'

$cmdArgs = "/c `"`"$PythonPath`" -m mdconvert.bot >> `"$logFile`" 2>&1`""
$action  = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $cmdArgs -WorkingDirectory $pythonDir

# --- Triggers: start at boot and at logon --------------------------------- #
$triggers = @(
    New-ScheduledTaskTrigger -AtStartup
    New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
)

# --- Settings: keep it alive, no time limit, auto-restart ----------------- #
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

# --- Principal ------------------------------------------------------------ #
$logonType = if ($RunOnlyWhenLoggedOn) { 'Interactive' } else { 'S4U' }
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType $logonType -RunLevel Limited

# --- Register (replace if it exists) -------------------------------------- #
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
    -Description 'Runs the mdconvert Telegram bot (file -> Markdown) continuously.' | Out-Null

Write-Host ""
Write-Host "Scheduled Task '$TaskName' registered (runs as $env:USERNAME, logon type $logonType)." -ForegroundColor Green
Write-Host "Make sure the bot dependency is installed:" -ForegroundColor Yellow
Write-Host "    `"$PythonPath`" -m pip install `"python-telegram-bot>=20`"" -ForegroundColor Yellow
Write-Host "    `"$PythonPath`" -m pip install -r `"$(Join-Path $pythonDir 'mdconvert\requirements.txt')`"   # PDF/Excel/Word/PowerPoint" -ForegroundColor Yellow
Write-Host ""
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Live log:           $logFile"
