# Azure Secret Expiration Monitor (Windows on-prem GUI)

A Windows Server desktop application that scans Azure for expiring secrets and
sends notifications. Runs **on-premises** — no cloud hosting required. Uses a
service principal (client ID + secret) to talk to Azure; the secret is
encrypted on disk with Windows DPAPI.

**👉 New users: follow the step-by-step [Installation & Configuration Guide](docs/INSTALL.md).**

## Screenshots

### Dashboard
Color-coded list of every credential in scope. Severity is computed from each
item's `expiresOn`; the summary line in the top-right counts items per bucket.

![Dashboard](docs/screenshots/dashboard.png)

### Azure tab
Service principal credentials, threshold window, and the list of Key Vaults to
scan. The client secret entry is masked and stored DPAPI-encrypted.

![Azure tab](docs/screenshots/azure.png)

### Notifications tab
Microsoft Teams Incoming Webhook plus SMTP email settings. The SMTP password
is also DPAPI-encrypted on save.

![Notifications tab](docs/screenshots/notifications.png)

### Scheduler tab
Toggle in-app background scans, or click "Install Scheduled Task..." to
register a Windows daily task that runs `cli.py` unattended.

![Scheduler tab](docs/screenshots/scheduler.png)


```
+------------------+        +-----------------------+        +---------------------+
|  Windows Server  |   -->  |  Microsoft Graph API  |  -->   | App registrations    |
|  (this app)      |        |  Azure Key Vault API  |        | Key Vault items     |
+------------------+        +-----------------------+        +---------------------+
          |
          v
   Teams webhook / SMTP email
```

## What it scans

- **Entra ID app registrations** — client secrets + certificate credentials.
- **Azure Key Vault** — secrets, keys, and certificates with an `expiresOn`.

Each credential is bucketed:

| Status | Meaning |
|---|---|
| `EXPIRED` | Already past expiration. |
| `CRITICAL` | ≤ 7 days remaining. |
| `WARNING` | ≤ 30 days remaining (configurable). |
| `OK` | Outside the threshold window. |

Notifications fire only when an item's severity **rises** (e.g. WARNING →
CRITICAL), so the same alert doesn't spam every day. State is kept in
`%APPDATA%\AzureSecretMonitor\state.json`.

---

## Prerequisites (Windows Server)

1. **Python 3.10+** for Windows (tkinter is included in the standard installer).
2. An **Entra ID app registration** to act as the service principal:
   - API permissions (Microsoft Graph, application type):
     `Application.Read.All` — granted with admin consent.
   - For each Key Vault you want to scan, grant the service principal
     `Key Vault Reader` plus a data role that allows listing:
     `Key Vault Secrets User`, `Key Vault Crypto User`, `Key Vault Certificate User`
     (or use Vault Access Policies with `get`+`list` on secrets/keys/certificates).
   - Create a **client secret** for the app registration — copy its value.

## Install

```powershell
git clone <this repo>
cd Netanel_new\python
pip install -r requirements.txt
```

## Run the GUI

Double-click `windows\Start-Monitor.bat`, or:

```powershell
cd python
python gui.py
```

The window has four tabs:

- **Dashboard** — color-coded table of every credential in scope, with
  "Scan now", "Send test Teams", "Send test email".
- **Azure** — tenant ID, client ID, client secret, key vault names,
  threshold days, app-registration toggle.
- **Notifications** — Microsoft Teams webhook + SMTP settings.
- **Scheduler** — enable in-app background scans on an interval, or install a
  Windows Scheduled Task that runs unattended.

Click **Save** in any tab to persist. Sensitive fields (client secret, SMTP
password) are encrypted with **DPAPI under the current Windows user** before
being written to `%APPDATA%\AzureSecretMonitor\secret.bin` /  `smtp.bin`.
Other users on the same server cannot decrypt them.

## Run unattended (Windows Scheduled Task)

After configuring + saving via the GUI, open the **Scheduler** tab and click
"Install Scheduled Task...", or run the installer directly:

```powershell
powershell -ExecutionPolicy Bypass -File windows\Install-ScheduledTask.ps1 -Time 07:30
```

This registers a task named `AzureSecretMonitor` that runs `cli.py` daily as
the current user (so it can decrypt the DPAPI-protected secret). Logs go to
`%ProgramData%\AzureSecretMonitor\logs\cli.log`.

The CLI exit code reflects severity (useful if you want to chain other tasks):

- `0` — clean (nothing in window)
- `1` — items in the threshold window
- `2` — at least one item already expired
- `3` — configuration missing (run the GUI first)

## File layout

```
python/
  gui.py            # tkinter GUI (entry point for desktop use)
  cli.py            # headless run (used by the Scheduled Task)
  core.py           # scanning + notifications (no UI imports)
  config_store.py   # DPAPI-encrypted config / state on disk
  requirements.txt
windows/
  Start-Monitor.bat       # launches the GUI
  Install-ScheduledTask.ps1
powershell/
  Monitor-AzureSecrets.ps1   # alternative pure-PowerShell scanner
```

## Where settings live

```
%APPDATA%\AzureSecretMonitor\
  config.json    # non-sensitive settings (tenant/client IDs, vaults, etc.)
  secret.bin     # client secret, DPAPI-encrypted (CurrentUser)
  smtp.bin       # SMTP password, DPAPI-encrypted (CurrentUser)
  state.json     # last-notified severity per item (alert deduplication)
```

Logs (Scheduled Task runs only): `%ProgramData%\AzureSecretMonitor\logs\cli.log`.

## Troubleshooting

- **"Configuration incomplete"** from the CLI: run the GUI once on the same
  Windows account, save the settings, then re-trigger the task.
- **Scheduled Task fails to read the secret**: the task must run under the
  same user account that saved the secret in the GUI. DPAPI keys are tied to
  the Windows user profile.
- **Graph 403 on `applications`**: the service principal needs
  `Application.Read.All` with admin consent.
- **Key Vault 403**: assign `Key Vault Reader` + the relevant data role(s),
  or add the SP to the vault's access policies with `get`+`list` permissions.
