#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function Test-PingTarget {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Target,
        [int]$Count = 4,
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    $results = [System.Collections.Generic.List[object]]::new()
    for ($i = 1; $i -le $Count; $i++) {
        try {
            if ($CimSession) {
                $ping = Get-CimInstance -ClassName Win32_PingStatus `
                    -Filter "Address='$Target'" -CimSession $CimSession -ErrorAction Stop
                $results.Add([pscustomobject]@{
                    Seq         = $i
                    Address     = if ($ping.ProtocolAddress) { $ping.ProtocolAddress } else { $Target }
                    RoundtripMs = if ($ping.StatusCode -eq 0) { $ping.ResponseTime } else { $null }
                    Status      = if ($ping.StatusCode -eq 0) { 'Success' } else { "Failed (code $($ping.StatusCode))" }
                })
            }
            else {
                $r = Test-NetConnection -ComputerName $Target -WarningAction SilentlyContinue -ErrorAction Stop
                $results.Add([pscustomobject]@{
                    Seq         = $i
                    Address     = if ($r.RemoteAddress) { $r.RemoteAddress.ToString() } else { $Target }
                    RoundtripMs = if ($r.PingSucceeded) { $r.PingReplyDetails.RoundtripTime } else { $null }
                    Status      = if ($r.PingSucceeded) { 'Success' } else { 'Failed' }
                })
            }
        }
        catch {
            $results.Add([pscustomobject]@{
                Seq = $i; Address = $Target; RoundtripMs = $null; Status = "Error: $_"
            })
        }
    }
    return $results.ToArray()
}

function Resolve-DnsName_Safe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$Server = '',
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    $results = [System.Collections.Generic.List[object]]::new()
    try {
        if ($CimSession) {
            # CIM doesn't expose DNS resolution; use .NET on the local machine for the target name
            $entry = [System.Net.Dns]::GetHostEntry($Name)
            foreach ($addr in $entry.AddressList) {
                $results.Add([pscustomobject]@{
                    Name    = $Name
                    Type    = $addr.AddressFamily.ToString()
                    Address = $addr.ToString()
                    TTL     = 'N/A'
                })
            }
        }
        else {
            $resolveArgs = @{ Name = $Name; ErrorAction = 'Stop' }
            if ($Server) { $resolveArgs['Server'] = $Server }
            foreach ($r in (Resolve-DnsName @resolveArgs)) {
                $results.Add([pscustomobject]@{
                    Name    = $r.Name
                    Type    = $r.Type
                    Address = if ($r.PSObject.Properties['IPAddress'])  { $r.IPAddress }
                              elseif ($r.PSObject.Properties['NameHost']) { $r.NameHost }
                              else { '' }
                    TTL     = $r.TTL
                })
            }
        }
    }
    catch {
        Write-Warning "DNS lookup for '$Name' failed: $_"
        $results.Add([pscustomobject]@{
            Name = $Name; Type = 'Error'; Address = $_.ToString(); TTL = ''
        })
    }
    return $results.ToArray()
}

function Test-TcpPort {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][ValidateRange(1, 65535)][int]$Port,
        [int]$TimeoutMs = 3000,
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    $sw  = [System.Diagnostics.Stopwatch]::StartNew()
    $tcp = [System.Net.Sockets.TcpClient]::new()
    try {
        $ar = $tcp.BeginConnect($Target, $Port, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne($TimeoutMs)
        $sw.Stop()
        if ($ok -and $tcp.Connected) {
            try { $tcp.EndConnect($ar) } catch { }
            return [pscustomobject]@{
                Target = $Target; Port = $Port; Open = $true
                RoundtripMs = $sw.ElapsedMilliseconds; Error = ''
            }
        }
        return [pscustomobject]@{
            Target = $Target; Port = $Port; Open = $false
            RoundtripMs = $sw.ElapsedMilliseconds; Error = 'Timed out or refused'
        }
    }
    catch {
        $sw.Stop()
        return [pscustomobject]@{
            Target = $Target; Port = $Port; Open = $false
            RoundtripMs = $sw.ElapsedMilliseconds; Error = $_.ToString()
        }
    }
    finally {
        $tcp.Close()
    }
}

function Get-Traceroute {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Target,
        [object]$CancelToken,
        [Microsoft.Management.Infrastructure.CimSession]$CimSession
    )
    $results = [System.Collections.Generic.List[object]]::new()
    try {
        # tracert.exe is always local; for remote targets the hops are the same from any machine
        $output = & tracert.exe -d -w 2000 $Target 2>&1
        # Pattern matches lines like: "  1    <1 ms    <1 ms    <1 ms  192.168.1.1"
        $hopRx  = '^\s*(\d+)\s+(?:(?:<?\d+)\s+ms\s+){1,3}\s*(\S+)'
        $starRx = '^\s*(\d+)\s+(?:\*\s+){1,3}Request timed out'
        foreach ($line in $output) {
            if ($CancelToken -and $CancelToken.Cancel) { break }
            if ($line -match $hopRx) {
                $hopNum  = [int]$Matches[1]
                $addr    = $Matches[2]
                $allMs   = [regex]::Matches($line, '(\d+)\s+ms') | ForEach-Object { [int]$_.Groups[1].Value }
                $avgMs   = if ($allMs) { [math]::Round(($allMs | Measure-Object -Average).Average, 0) } else { $null }
                $hostname = try { [System.Net.Dns]::GetHostEntry($addr).HostName } catch { $addr }
                $results.Add([pscustomobject]@{
                    Hop = $hopNum; Address = $addr; RoundtripMs = $avgMs; Hostname = $hostname
                })
            }
            elseif ($line -match $starRx) {
                $results.Add([pscustomobject]@{
                    Hop = [int]$Matches[1]; Address = '*'; RoundtripMs = $null; Hostname = '*'
                })
            }
        }
    }
    catch {
        Write-Warning "Traceroute to $Target failed: $_"
    }
    return $results.ToArray()
}

function Get-NetworkAdapters {
    [CmdletBinding()]
    param([Microsoft.Management.Infrastructure.CimSession]$CimSession)
    $results = [System.Collections.Generic.List[object]]::new()
    try {
        $adapterArgs = @{ ClassName = 'MSFT_NetAdapter'; Namespace = 'ROOT/StandardCimv2' }
        $ipArgs      = @{ ClassName = 'MSFT_NetIPAddress'; Namespace = 'ROOT/StandardCimv2' }
        if ($CimSession) {
            $adapterArgs['CimSession'] = $CimSession
            $ipArgs['CimSession']      = $CimSession
        }
        $adapters    = Get-CimInstance @adapterArgs
        $ipAddresses = Get-CimInstance @ipArgs

        foreach ($a in $adapters) {
            $ips  = @($ipAddresses | Where-Object InterfaceIndex -eq $a.InterfaceIndex)
            $ipv4 = ($ips | Where-Object AddressFamily -eq 2  | Select-Object -ExpandProperty IPAddress) -join ', '
            $ipv6 = ($ips | Where-Object AddressFamily -eq 23 | Select-Object -ExpandProperty IPAddress) -join ', '
            $mac  = if ($a.PermanentAddress) {
                ($a.PermanentAddress -split '(?<=\G.{2})(?=.)') -join ':'
            } else { '' }
            $results.Add([pscustomobject]@{
                Name          = $a.Name
                Status        = if ($a.MediaConnectState -eq 1) { 'Connected' } else { 'Disconnected' }
                IPv4Address   = $ipv4
                IPv6Address   = $ipv6
                MACAddress    = $mac
                LinkSpeedMbps = if ($a.TransmitLinkSpeed) { [math]::Round($a.TransmitLinkSpeed / 1MB, 0) } else { 0 }
            })
        }
    }
    catch {
        Write-Warning "Get-NetworkAdapters failed: $_"
    }
    return $results.ToArray()
}
