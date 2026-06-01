#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function New-CimSessionSafe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ComputerName,
        [System.Management.Automation.PSCredential]$Credential
    )
    try {
        $sessionArgs = @{ ComputerName = $ComputerName }
        if ($Credential) { $sessionArgs['Credential'] = $Credential }
        $session = New-CimSession @sessionArgs
        return [pscustomobject]@{ Success = $true; Session = $session; Error = '' }
    }
    catch {
        return [pscustomobject]@{ Success = $false; Session = $null; Error = $_.ToString() }
    }
}

function Remove-CimSessionSafe {
    [CmdletBinding()]
    param([Microsoft.Management.Infrastructure.CimSession]$Session)
    if (-not $Session) { return }
    try { Remove-CimSession -CimSession $Session -ErrorAction SilentlyContinue } catch { }
}

function New-RunspacePool {
    [CmdletBinding()]
    param(
        [int]$MinRunspaces = 1,
        [int]$MaxRunspaces = 4
    )
    $iss = [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault()
    foreach ($mod in @('Network.psm1', 'Services.psm1', 'Storage.psm1')) {
        $path = Join-Path $PSScriptRoot $mod
        if (Test-Path $path) { $iss.ImportPSModule($path) }
    }
    $pool = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspacePool(
        $MinRunspaces, $MaxRunspaces, $iss, $Host)
    $pool.Open()
    return $pool
}

function Invoke-BackgroundTask {
    <#
    .SYNOPSIS
        Runs a scriptblock on the RunspacePool and calls back on the WPF UI thread when done.
    .DESCRIPTION
        Uses a DispatcherTimer (100ms poll) to avoid blocking the WPF message pump.
        OnComplete and OnError run on the UI thread — direct WPF control access is safe.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][System.Management.Automation.Runspaces.RunspacePool]$Pool,
        [Parameter(Mandatory)][scriptblock]$ScriptBlock,
        [hashtable]$Arguments = @{},
        [Parameter(Mandatory)][scriptblock]$OnComplete,
        [scriptblock]$OnError
    )
    if (-not $OnError) {
        $OnError = { param($e) Write-Warning "Background task failed: $e" }
    }

    $ps = [System.Management.Automation.PowerShell]::Create()
    $ps.RunspacePool = $Pool
    [void]$ps.AddScript($ScriptBlock)
    foreach ($kv in $Arguments.GetEnumerator()) {
        [void]$ps.AddParameter($kv.Key, $kv.Value)
    }
    $handle = $ps.BeginInvoke()

    # Capture locals for the closure
    $capturedPs     = $ps
    $capturedHandle = $handle
    $capturedOk     = $OnComplete
    $capturedErr    = $OnError

    $timer = [System.Windows.Threading.DispatcherTimer]::new()
    $timer.Interval = [TimeSpan]::FromMilliseconds(100)

    $capturedTimer = $timer
    $timer.Add_Tick({
        if (-not $capturedHandle.IsCompleted) { return }
        $capturedTimer.Stop()
        try {
            $results = $capturedPs.EndInvoke($capturedHandle)
            & $capturedOk $results
        }
        catch {
            & $capturedErr $_
        }
        finally {
            $capturedPs.Dispose()
        }
    })
    $timer.Start()
}

function Get-CredentialIfNeeded {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ComputerName)
    $localNames = @('localhost', '.', '127.0.0.1', '::1', $env:COMPUTERNAME)
    if ($ComputerName.Trim() -in $localNames) { return $null }
    try {
        return Get-Credential -Message "Enter credentials for $ComputerName"
    }
    catch {
        return $null
    }
}
