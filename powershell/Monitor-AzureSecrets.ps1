<#
.SYNOPSIS
    Monitor Azure secret expirations and send notifications.

.DESCRIPTION
    Scans Entra ID (Azure AD) app registration client secrets and certificates,
    plus Azure Key Vault secrets / keys / certificates, and reports anything
    expiring within -ThresholdDays. Optionally sends an SMTP email and / or
    posts a Microsoft Teams Incoming Webhook message.

    Authentication uses the current Az PowerShell context. Run Connect-AzAccount
    (or rely on a Managed Identity in Azure / Az automation) before invoking.

.PARAMETER ThresholdDays
    Number of days ahead considered "expiring soon". Default: 30.

.PARAMETER KeyVault
    One or more Key Vault names to scan. Pass an empty array to skip vaults.

.PARAMETER SkipAppRegistrations
    Skip the Entra ID app registration scan.

.PARAMETER TeamsWebhook
    Microsoft Teams Incoming Webhook URL. If set, posts a summary message.

.PARAMETER SmtpHost
    SMTP relay hostname for email notifications.

.PARAMETER SmtpPort
    SMTP port. Default: 587.

.PARAMETER From
    Sender email address.

.PARAMETER To
    Recipient email address(es).

.PARAMETER SmtpCredential
    PSCredential for SMTP auth (optional).

.PARAMETER DryRun
    Print results but do not send notifications.

.EXAMPLE
    Connect-AzAccount
    ./Monitor-AzureSecrets.ps1 -KeyVault prod-kv,shared-kv -ThresholdDays 45 `
        -TeamsWebhook 'https://outlook.office.com/webhook/...'
#>

[CmdletBinding()]
param(
    [int]$ThresholdDays = 30,
    [string[]]$KeyVault = @(),
    [switch]$SkipAppRegistrations,
    [string]$TeamsWebhook,
    [string]$SmtpHost,
    [int]$SmtpPort = 587,
    [string]$From,
    [string[]]$To,
    [System.Management.Automation.PSCredential]$SmtpCredential,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Get-Status {
    param([int]$Days)
    if ($Days -lt 0)  { return 'EXPIRED' }
    if ($Days -le 7)  { return 'CRITICAL' }
    if ($Days -le 30) { return 'WARNING' }
    return 'OK'
}

function New-Item {
    param($Source, $Kind, $Name, $Container, [datetime]$ExpiresOn, $Identifier)
    $days = [int][math]::Floor(($ExpiresOn.ToUniversalTime() - (Get-Date).ToUniversalTime()).TotalDays)
    [pscustomobject]@{
        Source        = $Source
        Kind          = $Kind
        Name          = $Name
        Container     = $Container
        ExpiresOn     = $ExpiresOn.ToUniversalTime()
        DaysRemaining = $days
        Status        = Get-Status -Days $days
        Identifier    = $Identifier
    }
}

function Get-AppRegistrationCredentials {
    Write-Verbose "Scanning Entra ID app registrations..."
    $items = New-Object System.Collections.Generic.List[object]
    $apps = Get-AzADApplication
    foreach ($app in $apps) {
        try {
            $passwords = Get-AzADAppCredential -ObjectId $app.Id -ErrorAction Stop
        } catch {
            Write-Warning "Could not read credentials for app '$($app.DisplayName)': $_"
            continue
        }
        foreach ($pwd in $passwords) {
            if ($pwd.EndDateTime) {
                $kind = if ($pwd.Type -and $pwd.Type -match 'AsymmetricX509Cert') { 'Certificate' } else { 'ClientSecret' }
                $items.Add((New-Item -Source 'AppRegistration' -Kind $kind `
                    -Name ($pwd.DisplayName ?? $pwd.KeyId.ToString()) `
                    -Container $app.DisplayName `
                    -ExpiresOn $pwd.EndDateTime `
                    -Identifier $app.AppId)) | Out-Null
            }
        }
    }
    return $items
}

function Get-KeyVaultItems {
    param([string]$VaultName)
    Write-Verbose "Scanning Key Vault '$VaultName'..."
    $items = New-Object System.Collections.Generic.List[object]

    foreach ($s in Get-AzKeyVaultSecret -VaultName $VaultName) {
        if ($s.Expires) {
            $items.Add((New-Item -Source 'KeyVault' -Kind 'Secret' `
                -Name $s.Name -Container $VaultName -ExpiresOn $s.Expires `
                -Identifier $s.Id)) | Out-Null
        }
    }
    foreach ($k in Get-AzKeyVaultKey -VaultName $VaultName) {
        if ($k.Expires) {
            $items.Add((New-Item -Source 'KeyVault' -Kind 'Key' `
                -Name $k.Name -Container $VaultName -ExpiresOn $k.Expires `
                -Identifier $k.Id)) | Out-Null
        }
    }
    foreach ($c in Get-AzKeyVaultCertificate -VaultName $VaultName) {
        if ($c.Expires) {
            $items.Add((New-Item -Source 'KeyVault' -Kind 'Certificate' `
                -Name $c.Name -Container $VaultName -ExpiresOn $c.Expires `
                -Identifier $c.Id)) | Out-Null
        }
    }
    return $items
}

function Format-HtmlReport {
    param([object[]]$Items)
    if (-not $Items -or $Items.Count -eq 0) {
        return '<p>No expiring secrets within the threshold window.</p>'
    }
    $rowColor = @{
        'EXPIRED'  = '#ffb3b3'
        'CRITICAL' = '#ffd6a5'
        'WARNING'  = '#fff3b0'
        'OK'       = '#d8f3dc'
    }
    $rows = foreach ($i in $Items) {
        $bg = $rowColor[$i.Status]
        "<tr style='background:$bg'><td>$($i.Status)</td><td>$($i.DaysRemaining)</td>" +
        "<td>$($i.Source)</td><td>$($i.Kind)</td><td>$($i.Container)</td>" +
        "<td>$($i.Name)</td><td>$($i.ExpiresOn.ToString('yyyy-MM-dd HH:mm'))</td></tr>"
    }
    $head = '<tr><th>Status</th><th>Days</th><th>Source</th><th>Kind</th>' +
            '<th>Container</th><th>Name</th><th>Expires (UTC)</th></tr>'
    return "<table border='1' cellpadding='6' cellspacing='0' " +
           "style='border-collapse:collapse;font-family:Segoe UI,Arial'>$head$($rows -join '')</table>"
}

function Send-TeamsNotification {
    param([string]$WebhookUrl, [object[]]$Items)
    if (-not $Items -or $Items.Count -eq 0) {
        $text = 'No Azure secrets expiring within the threshold.'
    } else {
        $lines = $Items | Select-Object -First 50 | ForEach-Object {
            "- **$($_.Status)** ($($_.DaysRemaining)d) ``$($_.Source)/$($_.Kind)`` " +
            "$($_.Container) / $($_.Name) (expires $($_.ExpiresOn.ToString('yyyy-MM-dd')))"
        }
        $text = "**Azure secret expiration report**`n`n" + ($lines -join "`n")
        if ($Items.Count -gt 50) { $text += "`n`n_…and $($Items.Count - 50) more_" }
    }
    $body = @{ text = $text } | ConvertTo-Json -Depth 3
    Invoke-RestMethod -Uri $WebhookUrl -Method Post -ContentType 'application/json' -Body $body | Out-Null
}

function Send-EmailNotification {
    param([object[]]$Items)
    $html = Format-HtmlReport -Items $Items
    $subject = "[Azure] $($Items.Count) secrets expiring within $ThresholdDays days"
    $params = @{
        SmtpServer = $SmtpHost
        Port       = $SmtpPort
        UseSsl     = $true
        From       = $From
        To         = $To
        Subject    = $subject
        Body       = $html
        BodyAsHtml = $true
    }
    if ($SmtpCredential) { $params.Credential = $SmtpCredential }
    Send-MailMessage @params
}

# --- Main -------------------------------------------------------------------

if (-not (Get-AzContext)) {
    throw 'No Az context. Run Connect-AzAccount (or attach a Managed Identity) first.'
}

$all = New-Object System.Collections.Generic.List[object]

if (-not $SkipAppRegistrations) {
    try {
        $all.AddRange((Get-AppRegistrationCredentials))
    } catch {
        Write-Warning "App registration scan failed: $_"
    }
}

foreach ($v in $KeyVault) {
    try {
        $all.AddRange((Get-KeyVaultItems -VaultName $v))
    } catch {
        Write-Warning "Key Vault '$v' scan failed: $_"
    }
}

$cutoff = (Get-Date).ToUniversalTime().AddDays($ThresholdDays)
$report = $all |
    Where-Object { $_.ExpiresOn -le $cutoff } |
    Sort-Object ExpiresOn

$report | Format-Table Status, DaysRemaining, Source, Kind, Container, Name, ExpiresOn -AutoSize

if ($DryRun) {
    Write-Host "Dry-run: skipping notifications." -ForegroundColor Yellow
    return
}

if ($TeamsWebhook) {
    try { Send-TeamsNotification -WebhookUrl $TeamsWebhook -Items $report }
    catch { Write-Warning "Teams notification failed: $_" }
}

if ($SmtpHost -and $From -and $To) {
    try { Send-EmailNotification -Items $report }
    catch { Write-Warning "Email notification failed: $_" }
}

if ($report | Where-Object Status -eq 'EXPIRED') { exit 2 }
elseif ($report.Count -gt 0) { exit 1 }
else { exit 0 }
