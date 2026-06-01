#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function Get-DriveSummary {
    [CmdletBinding()]
    param([Microsoft.Management.Infrastructure.CimSession]$CimSession)
    try {
        $cimArgs = @{ ClassName = 'Win32_LogicalDisk'; Filter = 'DriveType=3' }
        if ($CimSession) { $cimArgs['CimSession'] = $CimSession }
        return Get-CimInstance @cimArgs | ForEach-Object {
            $totalGB = [math]::Round($_.Size / 1GB, 2)
            $freeGB  = [math]::Round($_.FreeSpace / 1GB, 2)
            $usedPct = if ($totalGB -gt 0) { [math]::Round((($totalGB - $freeGB) / $totalGB) * 100, 1) } else { 0 }
            [pscustomobject]@{
                Drive   = $_.DeviceID
                Label   = $_.VolumeName
                TotalGB = $totalGB
                FreeGB  = $freeGB
                UsedPct = $usedPct
            }
        }
    }
    catch {
        Write-Warning "Get-DriveSummary failed: $_"
        return @()
    }
}

function Find-LargeFiles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RootPath,
        [int]$MinSizeMB = 100,
        [object]$CancelToken,
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    $results  = [System.Collections.Generic.List[object]]::new()
    $minBytes = $MinSizeMB * 1MB
    try {
        Get-ChildItem -Path $RootPath -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Length -ge $minBytes } |
            Sort-Object Length -Descending |
            ForEach-Object {
                if ($CancelToken -and $CancelToken.Cancel) { return }
                $results.Add([pscustomobject]@{
                    FullName      = $_.FullName
                    SizeMB        = [math]::Round($_.Length / 1MB, 2)
                    LastWriteTime = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
                })
            }
    }
    catch {
        Write-Warning "Find-LargeFiles in '$RootPath' failed: $_"
    }
    return $results.ToArray()
}

function Get-TempDirectorySize {
    [CmdletBinding()]
    param([Microsoft.Management.Infrastructure.CimSession]$CimSession)
    $results = [System.Collections.Generic.List[object]]::new()
    foreach ($dir in (@($env:TEMP, 'C:\Windows\Temp') | Select-Object -Unique)) {
        if (-not (Test-Path $dir)) { continue }
        try {
            $files  = @(Get-ChildItem -Path $dir -Recurse -File -ErrorAction SilentlyContinue)
            $sizeMB = [math]::Round(($files | Measure-Object -Property Length -Sum).Sum / 1MB, 2)
            $results.Add([pscustomobject]@{
                TempDir   = $dir
                SizeMB    = $sizeMB
                FileCount = $files.Count
            })
        }
        catch {
            Write-Warning "Could not measure '$dir': $_"
        }
    }
    return $results.ToArray()
}

function Clear-TempDirectories {
    [CmdletBinding()]
    param([Microsoft.Management.Infrastructure.CimSession]$CimSession)
    $deletedCount = 0; $failedCount = 0; $freedBytes = 0L
    foreach ($dir in (@($env:TEMP, 'C:\Windows\Temp') | Select-Object -Unique)) {
        if (-not (Test-Path $dir)) { continue }
        foreach ($f in (Get-ChildItem -Path $dir -Recurse -File -ErrorAction SilentlyContinue)) {
            try {
                $freedBytes += $f.Length
                Remove-Item -Path $f.FullName -Force -ErrorAction Stop
                $deletedCount++
            }
            catch { $failedCount++ }
        }
    }
    return [pscustomobject]@{
        DeletedCount = $deletedCount
        FailedCount  = $failedCount
        FreedMB      = [math]::Round($freedBytes / 1MB, 2)
    }
}

function Get-DiskHealth {
    [CmdletBinding()]
    param([Microsoft.Management.Infrastructure.CimSession]$CimSession)
    $results = [System.Collections.Generic.List[object]]::new()
    try {
        $cimArgs = @{ ClassName = 'MSFT_Disk'; Namespace = 'ROOT/Microsoft/Windows/Storage' }
        if ($CimSession) { $cimArgs['CimSession'] = $CimSession }
        foreach ($d in (Get-CimInstance @cimArgs)) {
            $results.Add([pscustomobject]@{
                FriendlyName      = $d.FriendlyName
                Model             = $d.Model
                SizeGB            = [math]::Round($d.Size / 1GB, 2)
                HealthStatus      = $d.HealthStatus
                OperationalStatus = $d.OperationalStatus
            })
        }
    }
    catch {
        Write-Warning "MSFT_Disk unavailable, falling back to Win32_DiskDrive: $_"
        try {
            $cimArgs2 = @{ ClassName = 'Win32_DiskDrive' }
            if ($CimSession) { $cimArgs2['CimSession'] = $CimSession }
            foreach ($d in (Get-CimInstance @cimArgs2)) {
                $results.Add([pscustomobject]@{
                    FriendlyName      = $d.Caption
                    Model             = $d.Model
                    SizeGB            = [math]::Round($d.Size / 1GB, 2)
                    HealthStatus      = $d.Status
                    OperationalStatus = $d.StatusInfo
                })
            }
        }
        catch {
            Write-Warning "Get-DiskHealth fallback also failed: $_"
        }
    }
    return $results.ToArray()
}
