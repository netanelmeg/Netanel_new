#Requires -Version 5.1
<#
.SYNOPSIS
    WPF sysadmin troubleshooting tool — Network, Services, and Storage diagnostics.
.DESCRIPTION
    Provides a GUI for diagnosing network connectivity, managing Windows services,
    and analysing disk/storage. Supports local and remote machines via CIM/WinRM.
    Long-running operations run on a RunspacePool; results return to the UI thread
    via a DispatcherTimer so the window stays responsive throughout.
.PARAMETER ComputerName
    Hostname pre-filled in the connection bar (default: localhost).
#>
[CmdletBinding()]
param([string]$ComputerName = 'localhost')

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

$moduleRoot = Join-Path $PSScriptRoot 'Modules'
Import-Module (Join-Path $moduleRoot 'Helpers.psm1')  -Force
Import-Module (Join-Path $moduleRoot 'Network.psm1')  -Force
Import-Module (Join-Path $moduleRoot 'Services.psm1') -Force
Import-Module (Join-Path $moduleRoot 'Storage.psm1')  -Force

# ── Shared script-scope state ──────────────────────────────────────────────
$script:CimSession   = $null          # $null => all CIM calls target local machine
$script:RunspacePool = New-RunspacePool -MinRunspaces 1 -MaxRunspaces 4
$script:AllServices  = @()            # cached list for the live service filter
$script:CancelToken  = [pscustomobject]@{ Cancel = $false }  # shared cancellation flag

# ── Load window from XAML ─────────────────────────────────────────────────
[xml]$xaml = Get-Content (Join-Path $PSScriptRoot 'SysAdminTool.xaml') -Encoding UTF8
$window    = [System.Windows.Markup.XamlReader]::Load([System.Xml.XmlNodeReader]::new($xaml))

# ── Bind named controls ────────────────────────────────────────────────────
$txtComputerName     = $window.FindName('txtComputerName')
$btnConnect          = $window.FindName('btnConnect')
$ellConnectionBadge  = $window.FindName('ellConnectionBadge')
$txtConnectionStatus = $window.FindName('txtConnectionStatus')
$txtStatusBar        = $window.FindName('txtStatusBar')
$pbStatusBar         = $window.FindName('pbStatusBar')

# Network tab
$txtPingTarget       = $window.FindName('txtPingTarget')
$numPingCount        = $window.FindName('numPingCount')
$btnPing             = $window.FindName('btnPing')
$dgPingResults       = $window.FindName('dgPingResults')
$txtDnsName          = $window.FindName('txtDnsName')
$txtDnsServer        = $window.FindName('txtDnsServer')
$btnDnsLookup        = $window.FindName('btnDnsLookup')
$dgDnsResults        = $window.FindName('dgDnsResults')
$txtPortTarget       = $window.FindName('txtPortTarget')
$txtPortNumber       = $window.FindName('txtPortNumber')
$numPortTimeout      = $window.FindName('numPortTimeout')
$btnPortTest         = $window.FindName('btnPortTest')
$txtPortResult       = $window.FindName('txtPortResult')
$txtTraceTarget      = $window.FindName('txtTraceTarget')
$btnTraceroute       = $window.FindName('btnTraceroute')
$btnCancelTrace      = $window.FindName('btnCancelTrace')
$dgTraceResults      = $window.FindName('dgTraceResults')
$btnRefreshAdapters  = $window.FindName('btnRefreshAdapters')
$dgAdapters          = $window.FindName('dgAdapters')

# Services tab
$txtServiceFilter    = $window.FindName('txtServiceFilter')
$btnRefreshServices  = $window.FindName('btnRefreshServices')
$btnStartService     = $window.FindName('btnStartService')
$btnStopService      = $window.FindName('btnStopService')
$btnRestartService   = $window.FindName('btnRestartService')
$dgServices          = $window.FindName('dgServices')

# Storage tab
$btnRefreshDrives      = $window.FindName('btnRefreshDrives')
$dgDrives              = $window.FindName('dgDrives')
$txtScanPath           = $window.FindName('txtScanPath')
$txtMinSizeMB          = $window.FindName('txtMinSizeMB')
$btnScanFiles          = $window.FindName('btnScanFiles')
$btnCancelScan         = $window.FindName('btnCancelScan')
$dgLargeFiles          = $window.FindName('dgLargeFiles')
$btnCalculateTempSize  = $window.FindName('btnCalculateTempSize')
$btnCleanTemp          = $window.FindName('btnCleanTemp')
$dgTempInfo            = $window.FindName('dgTempInfo')
$btnRefreshDiskHealth  = $window.FindName('btnRefreshDiskHealth')
$dgDiskHealth          = $window.FindName('dgDiskHealth')

# ── Tiny UI helpers ────────────────────────────────────────────────────────
function Set-Status([string]$msg, [bool]$busy = $false) {
    $txtStatusBar.Text    = $msg
    $pbStatusBar.Visibility = if ($busy) { 'Visible' } else { 'Collapsed' }
}

function Set-Badge([string]$color, [string]$text) {
    $ellConnectionBadge.Fill  = $color
    $txtConnectionStatus.Text = $text
}

# ════════════════════════════════════════════════════════════════════════════
# CONNECTION
# ════════════════════════════════════════════════════════════════════════════
$btnConnect.Add_Click({
    $target = $txtComputerName.Text.Trim()
    if ([string]::IsNullOrEmpty($target)) { $target = 'localhost' }

    $localNames = @('localhost', '.', '127.0.0.1', '::1', $env:COMPUTERNAME)
    if ($target -in $localNames) {
        if ($script:CimSession) {
            Remove-CimSessionSafe -Session $script:CimSession
            $script:CimSession = $null
        }
        Set-Badge '#808080' 'Local'
        Set-Status 'Using local machine.'
        return
    }

    # Credential prompt must happen on the UI thread before dispatching
    $cred = Get-CredentialIfNeeded -ComputerName $target
    Set-Status "Connecting to $target ..." $true
    $btnConnect.IsEnabled = $false

    $capturedTarget = $target
    $capturedCred   = $cred

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($ComputerName, $Credential)
            New-CimSessionSafe -ComputerName $ComputerName -Credential $Credential
        } `
        -Arguments @{ ComputerName = $capturedTarget; Credential = $capturedCred } `
        -OnComplete {
            param($results)
            $r = $results | Select-Object -First 1
            if ($r.Success) {
                if ($script:CimSession) { Remove-CimSessionSafe -Session $script:CimSession }
                $script:CimSession = $r.Session
                Set-Badge '#27AE60' "Connected: $capturedTarget"
                Set-Status "Connected to $capturedTarget."
            }
            else {
                Set-Badge '#E74C3C' "Failed: $capturedTarget"
                Set-Status "Connection failed: $($r.Error)"
            }
            $btnConnect.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Badge '#E74C3C' 'Connection error'
            Set-Status "Connection error: $ex"
            $btnConnect.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# NETWORK — PING
# ════════════════════════════════════════════════════════════════════════════
$btnPing.Add_Click({
    $target = $txtPingTarget.Text.Trim()
    if ([string]::IsNullOrEmpty($target)) { return }
    $count  = [int]([regex]::Match($numPingCount.Text, '\d+').Value)
    if ($count -lt 1 -or $count -gt 100) { $count = 4 }

    $dgPingResults.ItemsSource = $null
    Set-Status "Pinging $target ($count packets) ..." $true
    $btnPing.IsEnabled = $false
    $capturedSession   = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($Target, $Count, $CimSession)
            Test-PingTarget -Target $Target -Count $Count -CimSession $CimSession
        } `
        -Arguments @{ Target = $target; Count = $count; CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $dgPingResults.ItemsSource = $rows
            $ok = ($rows | Where-Object { $_.Status -eq 'Success' }).Count
            Set-Status "Ping complete — $ok/$($rows.Count) succeeded."
            $btnPing.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "Ping failed: $ex"
            $btnPing.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# NETWORK — DNS
# ════════════════════════════════════════════════════════════════════════════
$btnDnsLookup.Add_Click({
    $name   = $txtDnsName.Text.Trim()
    $server = $txtDnsServer.Text.Trim()
    if ([string]::IsNullOrEmpty($name)) { return }

    $dgDnsResults.ItemsSource = $null
    Set-Status "Resolving '$name' ..." $true
    $btnDnsLookup.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($Name, $Server, $CimSession)
            Resolve-DnsName_Safe -Name $Name -Server $Server -CimSession $CimSession
        } `
        -Arguments @{ Name = $name; Server = $server; CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $dgDnsResults.ItemsSource = $rows
            Set-Status "Resolved '$name' — $($rows.Count) record(s)."
            $btnDnsLookup.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "DNS lookup failed: $ex"
            $btnDnsLookup.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# NETWORK — PORT TEST
# ════════════════════════════════════════════════════════════════════════════
$btnPortTest.Add_Click({
    $target  = $txtPortTarget.Text.Trim()
    $portStr = [regex]::Match($txtPortNumber.Text, '\d+').Value
    $timeStr = [regex]::Match($numPortTimeout.Text, '\d+').Value
    if ([string]::IsNullOrEmpty($target) -or [string]::IsNullOrEmpty($portStr)) { return }
    $port    = [int]$portStr
    $timeout = if ($timeStr) { [int]$timeStr } else { 3000 }
    if ($port -lt 1 -or $port -gt 65535) { Set-Status 'Invalid port number.'; return }

    $txtPortResult.Text = ''
    Set-Status "Testing $target : $port ..." $true
    $btnPortTest.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($Target, $Port, $TimeoutMs, $CimSession)
            Test-TcpPort -Target $Target -Port $Port -TimeoutMs $TimeoutMs -CimSession $CimSession
        } `
        -Arguments @{ Target = $target; Port = $port; TimeoutMs = $timeout; CimSession = $capturedSession } `
        -OnComplete {
            param($results)
            $r = $results | Select-Object -First 1
            if ($r.Open) {
                $txtPortResult.Text       = "Open  ($($r.RoundtripMs) ms)"
                $txtPortResult.Foreground = '#27AE60'
            }
            else {
                $txtPortResult.Text       = "Closed / Timed Out  —  $($r.Error)"
                $txtPortResult.Foreground = '#E74C3C'
            }
            Set-Status "Port test complete: $target : $port"
            $btnPortTest.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "Port test failed: $ex"
            $btnPortTest.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# NETWORK — TRACEROUTE
# ════════════════════════════════════════════════════════════════════════════
$btnTraceroute.Add_Click({
    $target = $txtTraceTarget.Text.Trim()
    if ([string]::IsNullOrEmpty($target)) { return }

    $script:CancelToken.Cancel = $false
    $dgTraceResults.ItemsSource  = $null
    $btnTraceroute.Visibility    = 'Collapsed'
    $btnCancelTrace.Visibility   = 'Visible'
    Set-Status "Tracing route to $target ..." $true
    $capturedSession = $script:CimSession
    $capturedToken   = $script:CancelToken

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($Target, $CancelToken, $CimSession)
            Get-Traceroute -Target $Target -CancelToken $CancelToken -CimSession $CimSession
        } `
        -Arguments @{ Target = $target; CancelToken = $capturedToken; CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $dgTraceResults.ItemsSource = $rows
            $btnTraceroute.Visibility   = 'Visible'
            $btnCancelTrace.Visibility  = 'Collapsed'
            Set-Status "Traceroute complete — $($rows.Count) hop(s)."
        } `
        -OnError {
            param($ex)
            $btnTraceroute.Visibility  = 'Visible'
            $btnCancelTrace.Visibility = 'Collapsed'
            Set-Status "Traceroute failed: $ex"
        }
})

$btnCancelTrace.Add_Click({
    $script:CancelToken.Cancel = $true
    Set-Status 'Traceroute cancelled.'
})

# ════════════════════════════════════════════════════════════════════════════
# NETWORK — ADAPTERS
# ════════════════════════════════════════════════════════════════════════════
$btnRefreshAdapters.Add_Click({
    $dgAdapters.ItemsSource = $null
    Set-Status 'Loading network adapters ...' $true
    $btnRefreshAdapters.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($CimSession)
            Get-NetworkAdapters -CimSession $CimSession
        } `
        -Arguments @{ CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $dgAdapters.ItemsSource = $rows
            Set-Status "Adapters loaded — $($rows.Count) adapter(s)."
            $btnRefreshAdapters.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "Adapter refresh failed: $ex"
            $btnRefreshAdapters.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# SERVICES
# ════════════════════════════════════════════════════════════════════════════
$btnRefreshServices.Add_Click({
    $dgServices.ItemsSource      = $null
    $script:AllServices          = @()
    Set-Status 'Loading services ...' $true
    $btnRefreshServices.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($CimSession)
            Get-ServiceList -CimSession $CimSession
        } `
        -Arguments @{ CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $script:AllServices = $rows
            # Respect any active filter text
            $filtered = Get-ServicesByFilter -Services $rows -FilterText $txtServiceFilter.Text
            $dgServices.ItemsSource = $filtered
            Set-Status "Services loaded — $($rows.Count) service(s)."
            $btnRefreshServices.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "Service refresh failed: $ex"
            $btnRefreshServices.IsEnabled = $true
        }
})

# Live filter — runs on the UI thread, no runspace needed
$txtServiceFilter.Add_TextChanged({
    $dgServices.ItemsSource = Get-ServicesByFilter `
        -Services $script:AllServices -FilterText $txtServiceFilter.Text
})

$btnStartService.Add_Click({
    $sel = $dgServices.SelectedItem
    if (-not $sel) { Set-Status 'Select a service first.'; return }

    Set-Status "Starting '$($sel.DisplayName)' ..." $true
    $btnStartService.IsEnabled = $false
    $capturedName    = $sel.Name
    $capturedDisplay = $sel.DisplayName
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($ServiceName, $CimSession)
            Start-ServiceSafe -ServiceName $ServiceName -CimSession $CimSession
        } `
        -Arguments @{ ServiceName = $capturedName; CimSession = $capturedSession } `
        -OnComplete {
            param($results)
            $r = $results | Select-Object -First 1
            Set-Status $(if ($r.Success) { "'$capturedDisplay' started." }
                         else { "Start failed: $($r.Error)" })
            $btnStartService.IsEnabled = $true
            $btnRefreshServices.RaiseEvent(
                [System.Windows.RoutedEventArgs]::new([System.Windows.Controls.Button]::ClickEvent))
        } `
        -OnError {
            param($ex)
            Set-Status "Start failed: $ex"
            $btnStartService.IsEnabled = $true
        }
})

$btnStopService.Add_Click({
    $sel = $dgServices.SelectedItem
    if (-not $sel) { Set-Status 'Select a service first.'; return }

    $confirm = [System.Windows.MessageBox]::Show(
        "Stop '$($sel.DisplayName)'?",
        'Confirm Stop',
        [System.Windows.MessageBoxButton]::YesNo,
        [System.Windows.MessageBoxImage]::Warning)
    if ($confirm -ne 'Yes') { return }

    Set-Status "Stopping '$($sel.DisplayName)' ..." $true
    $btnStopService.IsEnabled = $false
    $capturedName    = $sel.Name
    $capturedDisplay = $sel.DisplayName
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($ServiceName, $CimSession)
            Stop-ServiceSafe -ServiceName $ServiceName -CimSession $CimSession
        } `
        -Arguments @{ ServiceName = $capturedName; CimSession = $capturedSession } `
        -OnComplete {
            param($results)
            $r = $results | Select-Object -First 1
            Set-Status $(if ($r.Success) { "'$capturedDisplay' stopped." }
                         else { "Stop failed: $($r.Error)" })
            $btnStopService.IsEnabled = $true
            $btnRefreshServices.RaiseEvent(
                [System.Windows.RoutedEventArgs]::new([System.Windows.Controls.Button]::ClickEvent))
        } `
        -OnError {
            param($ex)
            Set-Status "Stop failed: $ex"
            $btnStopService.IsEnabled = $true
        }
})

$btnRestartService.Add_Click({
    $sel = $dgServices.SelectedItem
    if (-not $sel) { Set-Status 'Select a service first.'; return }

    $confirm = [System.Windows.MessageBox]::Show(
        "Restart '$($sel.DisplayName)'?",
        'Confirm Restart',
        [System.Windows.MessageBoxButton]::YesNo,
        [System.Windows.MessageBoxImage]::Question)
    if ($confirm -ne 'Yes') { return }

    Set-Status "Restarting '$($sel.DisplayName)' ..." $true
    $btnRestartService.IsEnabled = $false
    $capturedName    = $sel.Name
    $capturedDisplay = $sel.DisplayName
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($ServiceName, $CimSession)
            Restart-ServiceSafe -ServiceName $ServiceName -CimSession $CimSession
        } `
        -Arguments @{ ServiceName = $capturedName; CimSession = $capturedSession } `
        -OnComplete {
            param($results)
            $r = $results | Select-Object -First 1
            Set-Status $(if ($r.Success) { "'$capturedDisplay' restarted." }
                         else { "Restart failed: $($r.Error)" })
            $btnRestartService.IsEnabled = $true
            $btnRefreshServices.RaiseEvent(
                [System.Windows.RoutedEventArgs]::new([System.Windows.Controls.Button]::ClickEvent))
        } `
        -OnError {
            param($ex)
            Set-Status "Restart failed: $ex"
            $btnRestartService.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# STORAGE — DRIVES
# ════════════════════════════════════════════════════════════════════════════
$btnRefreshDrives.Add_Click({
    $dgDrives.ItemsSource = $null
    Set-Status 'Loading drive information ...' $true
    $btnRefreshDrives.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($CimSession)
            Get-DriveSummary -CimSession $CimSession
        } `
        -Arguments @{ CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $dgDrives.ItemsSource = $rows
            Set-Status "Drives loaded — $($rows.Count) volume(s)."
            $btnRefreshDrives.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "Drive refresh failed: $ex"
            $btnRefreshDrives.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# STORAGE — LARGE FILE FINDER
# ════════════════════════════════════════════════════════════════════════════
$btnScanFiles.Add_Click({
    $path  = $txtScanPath.Text.Trim()
    $minMB = [int]([regex]::Match($txtMinSizeMB.Text, '\d+').Value)
    if ([string]::IsNullOrEmpty($path)) { return }
    if ($minMB -lt 1) { $minMB = 100 }

    $script:CancelToken.Cancel    = $false
    $dgLargeFiles.ItemsSource     = $null
    $btnScanFiles.Visibility      = 'Collapsed'
    $btnCancelScan.Visibility     = 'Visible'
    Set-Status "Scanning '$path' for files > $minMB MB ..." $true
    $capturedSession = $script:CimSession
    $capturedToken   = $script:CancelToken

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($RootPath, $MinSizeMB, $CancelToken, $CimSession)
            Find-LargeFiles -RootPath $RootPath -MinSizeMB $MinSizeMB `
                            -CancelToken $CancelToken -CimSession $CimSession
        } `
        -Arguments @{
            RootPath = $path; MinSizeMB = $minMB
            CancelToken = $capturedToken; CimSession = $capturedSession
        } `
        -OnComplete {
            param($rows)
            $dgLargeFiles.ItemsSource = $rows
            $btnScanFiles.Visibility  = 'Visible'
            $btnCancelScan.Visibility = 'Collapsed'
            Set-Status "Scan complete — $($rows.Count) file(s) found."
        } `
        -OnError {
            param($ex)
            $btnScanFiles.Visibility  = 'Visible'
            $btnCancelScan.Visibility = 'Collapsed'
            Set-Status "File scan failed: $ex"
        }
})

$btnCancelScan.Add_Click({
    $script:CancelToken.Cancel = $true
    Set-Status 'Cancelling scan ...'
})

# ════════════════════════════════════════════════════════════════════════════
# STORAGE — TEMP CLEANUP
# ════════════════════════════════════════════════════════════════════════════
$btnCalculateTempSize.Add_Click({
    $dgTempInfo.ItemsSource = $null
    Set-Status 'Calculating temp directory sizes ...' $true
    $btnCalculateTempSize.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($CimSession)
            Get-TempDirectorySize -CimSession $CimSession
        } `
        -Arguments @{ CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $dgTempInfo.ItemsSource = $rows
            $totalMB = [math]::Round(($rows | Measure-Object SizeMB -Sum).Sum, 2)
            Set-Status "Temp total: $totalMB MB across $($rows.Count) director(ies)."
            $btnCalculateTempSize.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "Temp size calculation failed: $ex"
            $btnCalculateTempSize.IsEnabled = $true
        }
})

$btnCleanTemp.Add_Click({
    $confirm = [System.Windows.MessageBox]::Show(
        "Delete all files in temp directories?`nThis cannot be undone.",
        'Confirm Cleanup',
        [System.Windows.MessageBoxButton]::YesNo,
        [System.Windows.MessageBoxImage]::Warning)
    if ($confirm -ne 'Yes') { return }

    Set-Status 'Cleaning temp directories ...' $true
    $btnCleanTemp.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($CimSession)
            Clear-TempDirectories -CimSession $CimSession
        } `
        -Arguments @{ CimSession = $capturedSession } `
        -OnComplete {
            param($results)
            $r = $results | Select-Object -First 1
            Set-Status "Cleanup: $($r.DeletedCount) deleted, $($r.FailedCount) skipped, $($r.FreedMB) MB freed."
            $btnCleanTemp.IsEnabled = $true
            $btnCalculateTempSize.RaiseEvent(
                [System.Windows.RoutedEventArgs]::new([System.Windows.Controls.Button]::ClickEvent))
        } `
        -OnError {
            param($ex)
            Set-Status "Cleanup failed: $ex"
            $btnCleanTemp.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# STORAGE — DISK HEALTH
# ════════════════════════════════════════════════════════════════════════════
$btnRefreshDiskHealth.Add_Click({
    $dgDiskHealth.ItemsSource = $null
    Set-Status 'Loading disk health ...' $true
    $btnRefreshDiskHealth.IsEnabled = $false
    $capturedSession = $script:CimSession

    Invoke-BackgroundTask `
        -Pool    $script:RunspacePool `
        -ScriptBlock {
            param($CimSession)
            Get-DiskHealth -CimSession $CimSession
        } `
        -Arguments @{ CimSession = $capturedSession } `
        -OnComplete {
            param($rows)
            $dgDiskHealth.ItemsSource = $rows
            Set-Status "Disk health loaded — $($rows.Count) disk(s)."
            $btnRefreshDiskHealth.IsEnabled = $true
        } `
        -OnError {
            param($ex)
            Set-Status "Disk health refresh failed: $ex"
            $btnRefreshDiskHealth.IsEnabled = $true
        }
})

# ════════════════════════════════════════════════════════════════════════════
# WINDOW CLOSE — cleanup resources
# ════════════════════════════════════════════════════════════════════════════
$window.Add_Closing({
    $script:CancelToken.Cancel = $true
    if ($script:CimSession) { Remove-CimSessionSafe -Session $script:CimSession }
    $script:RunspacePool.Close()
    $script:RunspacePool.Dispose()
})

# ── Initial state ────────────────────────────────────────────────────────────
$txtComputerName.Text = $ComputerName
Set-Status 'Ready. Use buttons above to run diagnostics, or connect to a remote machine.'

[void]$window.ShowDialog()
