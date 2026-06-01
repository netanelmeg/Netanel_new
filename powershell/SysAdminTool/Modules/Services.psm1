#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function Get-ServiceList {
    [CmdletBinding()]
    param([Microsoft.Management.Infrastructure.CimSession]$CimSession)
    try {
        $cimArgs = @{ ClassName = 'Win32_Service' }
        if ($CimSession) { $cimArgs['CimSession'] = $CimSession }
        return Get-CimInstance @cimArgs |
            Sort-Object DisplayName |
            ForEach-Object {
                [pscustomobject]@{
                    Name        = $_.Name
                    DisplayName = $_.DisplayName
                    Status      = $_.State
                    StartType   = $_.StartMode
                    ProcessId   = $_.ProcessId
                }
            }
    }
    catch {
        Write-Warning "Get-ServiceList failed: $_"
        return @()
    }
}

function Start-ServiceSafe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ServiceName,
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    try {
        $cimArgs = @{ ClassName = 'Win32_Service'; Filter = "Name='$ServiceName'" }
        if ($CimSession) { $cimArgs['CimSession'] = $CimSession }
        $svc = Get-CimInstance @cimArgs
        if (-not $svc) { throw "Service '$ServiceName' not found." }
        $r = Invoke-CimMethod -InputObject $svc -MethodName 'StartService'
        return [pscustomobject]@{
            Success     = ($r.ReturnValue -eq 0)
            ReturnValue = $r.ReturnValue
            Error       = if ($r.ReturnValue -ne 0) { "Win32 return code $($r.ReturnValue)" } else { '' }
        }
    }
    catch {
        return [pscustomobject]@{ Success = $false; ReturnValue = -1; Error = $_.ToString() }
    }
}

function Stop-ServiceSafe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ServiceName,
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    try {
        $cimArgs = @{ ClassName = 'Win32_Service'; Filter = "Name='$ServiceName'" }
        if ($CimSession) { $cimArgs['CimSession'] = $CimSession }
        $svc = Get-CimInstance @cimArgs
        if (-not $svc) { throw "Service '$ServiceName' not found." }
        $r = Invoke-CimMethod -InputObject $svc -MethodName 'StopService'
        return [pscustomobject]@{
            Success     = ($r.ReturnValue -eq 0)
            ReturnValue = $r.ReturnValue
            Error       = if ($r.ReturnValue -ne 0) { "Win32 return code $($r.ReturnValue)" } else { '' }
        }
    }
    catch {
        return [pscustomobject]@{ Success = $false; ReturnValue = -1; Error = $_.ToString() }
    }
}

function Restart-ServiceSafe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ServiceName,
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    $stopResult  = Stop-ServiceSafe  -ServiceName $ServiceName -CimSession $CimSession
    Start-Sleep -Milliseconds 800
    $startResult = Start-ServiceSafe -ServiceName $ServiceName -CimSession $CimSession
    return [pscustomobject]@{
        Success     = ($stopResult.Success -and $startResult.Success)
        StopResult  = $stopResult
        StartResult = $startResult
        Error       = if (-not $stopResult.Success)  { "Stop: $($stopResult.Error)" }
                      elseif (-not $startResult.Success) { "Start: $($startResult.Error)" }
                      else { '' }
    }
}

function Get-ServicesByFilter {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object[]]$Services,
        [string]$FilterText
    )
    if ([string]::IsNullOrWhiteSpace($FilterText)) { return $Services }
    $p = "*$FilterText*"
    return @($Services | Where-Object { $_.Name -like $p -or $_.DisplayName -like $p })
}
