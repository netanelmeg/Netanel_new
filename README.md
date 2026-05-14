# Azure Secret Expiration Monitor

Monitors Azure secret expirations and sends notifications. Two equivalent
implementations are provided:

| Path | Stack | Best for |
|---|---|---|
| `python/azure_secret_monitor.py` | Python 3.10+, `azure-identity` | Linux/CI, containers, cron, GitHub Actions |
| `powershell/Monitor-AzureSecrets.ps1` | PowerShell 7+, `Az` modules | Windows admins, Azure Automation runbooks |

## What it scans

- **Entra ID (Azure AD) app registrations** – client secrets and certificate
  credentials on every application the identity can read.
- **Azure Key Vault** – secrets, keys, and certificates in each named vault
  (only items that have an explicit expiration are reported).

For every credential it computes days remaining and assigns a status:

| Status | Meaning |
|---|---|
| `EXPIRED` | Already past `expiresOn`. |
| `CRITICAL` | Expires within 7 days. |
| `WARNING` | Expires within 30 days. |
| `OK` | Beyond 30 days (only shown with `include_ok`). |

## Notifications

- Console table (always)
- Microsoft Teams via Incoming Webhook
- SMTP email (HTML + plain text)

Exit code: `0` clean, `1` items in window, `2` something already expired —
useful for CI gating.

---

## Python

```bash
cd python
pip install -r requirements.txt
cp config.example.yaml config.yaml   # edit vault names, email, webhook
az login                              # or set AZURE_CLIENT_ID/SECRET/TENANT
python azure_secret_monitor.py -c config.yaml
```

Common flags:

```bash
python azure_secret_monitor.py --dry-run         # don't send anything
python azure_secret_monitor.py --json            # machine-readable output
python azure_secret_monitor.py -v                # debug logging
```

Auth uses `DefaultAzureCredential`, so it picks up (in order): env vars,
managed identity, Azure CLI login, VS Code login, etc.

### Permissions required

- Microsoft Graph: `Application.Read.All` (delegated or app)
- Key Vault: `get` + `list` on secrets, keys, and certificates (RBAC role
  `Key Vault Reader` plus `Key Vault Secrets User` is enough for read-only
  metadata)

---

## PowerShell

```powershell
Install-Module Az -Scope CurrentUser
Connect-AzAccount

./powershell/Monitor-AzureSecrets.ps1 `
    -KeyVault 'prod-kv','shared-kv' `
    -ThresholdDays 45 `
    -TeamsWebhook 'https://outlook.office.com/webhook/...'
```

To send email instead/also:

```powershell
$cred = Get-Credential
./Monitor-AzureSecrets.ps1 -KeyVault prod-kv `
    -SmtpHost smtp.office365.com -From alerts@contoso.com `
    -To secops@contoso.com -SmtpCredential $cred
```

---

## Scheduling

- **GitHub Actions / Azure DevOps**: run the Python script on `schedule:` cron;
  authenticate with OIDC federated credentials.
- **Azure Automation**: import the PowerShell script as a runbook and use the
  account's system-assigned Managed Identity.
- **cron / Task Scheduler**: any host with the right credentials works.
