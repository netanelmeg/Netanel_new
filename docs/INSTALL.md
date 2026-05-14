# Installation & Configuration Guide

End-to-end walkthrough for getting **Azure Secret Monitor** running on a
Windows Server, from a clean machine through your first notification.

> Estimated time: **20–30 minutes**, most of which is waiting for an Azure
> admin consent click.

---

## Table of contents

1. [What you'll end up with](#1-what-youll-end-up-with)
2. [Prerequisites](#2-prerequisites)
3. [Install Python on Windows Server](#3-install-python-on-windows-server)
4. [Get the code](#4-get-the-code)
5. [Install Python dependencies](#5-install-python-dependencies)
6. [Create the Entra ID app registration](#6-create-the-entra-id-app-registration)
7. [Grant Microsoft Graph permission](#7-grant-microsoft-graph-permission)
8. [Grant Key Vault permission](#8-grant-key-vault-permission)
9. [Launch the GUI and configure](#9-launch-the-gui-and-configure)
10. [Configure notifications](#10-configure-notifications)
11. [Run your first scan](#11-run-your-first-scan)
12. [Install the Windows Scheduled Task](#12-install-the-windows-scheduled-task)
13. [Verify everything works](#13-verify-everything-works)
14. [Troubleshooting](#14-troubleshooting)
15. [Appendix: file locations and exit codes](#15-appendix-file-locations-and-exit-codes)

---

## 1. What you'll end up with

- A GUI app on the server's desktop for ad-hoc scans and configuration.
- A Windows Scheduled Task that runs `cli.py` every day under your user
  account, decrypts the stored client secret with DPAPI, hits Azure, and
  posts/emails any items whose severity rose since the last run.
- A JSON state file that prevents the same alert from firing every day.

![Dashboard preview](screenshots/dashboard.png)

---

## 2. Prerequisites

- **Windows Server 2019 / 2022 / 2025** (or Windows 10/11 — the app is just
  a desktop Python program).
- **Local admin** on the server (only needed once, to register the Scheduled
  Task; the task itself runs as your normal user).
- **Outbound HTTPS** from the server to:
  - `login.microsoftonline.com`
  - `graph.microsoft.com`
  - `*.vault.azure.net`
  - your Teams webhook host (`*.webhook.office.com`) and/or SMTP relay
- **An Entra ID tenant admin** who can grant `Application.Read.All` consent
  (one click in the portal — the rest you can do yourself).

---

## 3. Install Python on Windows Server

1. Sign in to the server as the user that will own the monitor (e.g.
   `CONTOSO\svc-secret-monitor`). Important: that **same** account must run
   the Scheduled Task later, because DPAPI ties the encrypted secret to the
   user profile.
2. Download Python **3.11 or 3.12** for Windows (64-bit) from
   <https://www.python.org/downloads/windows/>.
3. Run the installer:
   - Tick **"Add python.exe to PATH"**.
   - Click **"Customize installation"** and keep `tcl/tk and IDLE` selected
     (this is tkinter — required for the GUI).
   - Finish the wizard.
4. Open a new PowerShell window and verify:

   ```powershell
   python --version       # 3.11.x or 3.12.x
   python -c "import tkinter; print('tk OK')"
   ```

---

## 4. Get the code

Either clone with git or download the ZIP:

```powershell
cd C:\
git clone https://github.com/netanelmeg/Netanel_new.git AzureSecretMonitor
cd C:\AzureSecretMonitor
```

(Adjust the URL if you forked the repo internally.)

---

## 5. Install Python dependencies

```powershell
cd C:\AzureSecretMonitor\python
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This pulls `azure-identity`, the Key Vault SDKs, `msgraph-core`, `requests`,
and `ttkbootstrap` (the modern Tk theme). About 60 MB total.

---

## 6. Create the Entra ID app registration

1. Open the **Azure portal** → **Microsoft Entra ID** → **App registrations**
   → **+ New registration**.
2. Name it `azure-secret-monitor`. Single tenant. Leave the Redirect URI
   blank. Click **Register**.
3. On the new app's overview page, copy:
   - **Directory (tenant) ID**
   - **Application (client) ID**
4. Left nav → **Certificates & secrets** → **Client secrets** → **+ New
   client secret**. Description `secret-monitor`, expiry e.g. 24 months.
   Click **Add**. **Copy the value immediately** — it's only shown once.

Keep those three values handy: **tenant ID**, **client ID**, **secret value**.

---

## 7. Grant Microsoft Graph permission

The app needs to list all application registrations and read their
credentials.

1. Left nav → **API permissions** → **+ Add a permission** →
   **Microsoft Graph** → **Application permissions**.
2. Search for `Application.Read.All`, tick it, click **Add permissions**.
3. Click **Grant admin consent for <your tenant>** (a tenant admin must do
   this once). The status should turn green.

> No delegated user permissions are required.

---

## 8. Grant Key Vault permission

Do this for **each** Key Vault you want monitored. The simplest path is RBAC:

1. Open the Key Vault → **Access control (IAM)** → **+ Add role assignment**.
2. Assign **Key Vault Reader** to the service principal `azure-secret-monitor`.
3. Repeat and assign these data-plane roles so the app can list metadata:
   - **Key Vault Secrets User**
   - **Key Vault Crypto User**
   - **Key Vault Certificate User**

> If your vault still uses **Access Policies** instead of RBAC: open
> **Access policies** → **Create**, pick `azure-secret-monitor`, and grant
> `Get` and `List` on Secrets, Keys, and Certificates.

---

## 9. Launch the GUI and configure

Double-click `windows\Start-Monitor.bat`, or:

```powershell
cd C:\AzureSecretMonitor\python
python gui.py
```

Go to the **Azure** tab:

![Azure tab](screenshots/azure.png)

Fill in:

| Field | Value |
|---|---|
| Tenant ID | the GUID from step 6 |
| Client ID | the GUID from step 6 |
| Client secret | the secret value you copied in step 6 |
| Threshold (days) | how many days ahead to consider "expiring soon" — 30 is a good default |
| Scan Entra ID app registrations | ON if you want app-reg credentials reported |
| Show healthy items (OK) | OFF for normal monitoring; ON if you want a full inventory |
| Key Vaults | one vault **name** per line (not the full URL) |

Click **💾 Save settings**. The client secret is immediately encrypted with
Windows DPAPI under your current user and written to
`%APPDATA%\AzureSecretMonitor\secret.bin`. Nothing sensitive is stored in
plaintext on disk.

---

## 10. Configure notifications

Go to the **Notifications** tab:

![Notifications tab](screenshots/notifications.png)

### Microsoft Teams (optional)

1. In Teams, open the channel → ⋯ → **Workflows** (or **Connectors** in
   classic Teams) → add an **Incoming Webhook**.
2. Copy the generated URL into **Incoming webhook URL**.
3. Click **💾 Save settings**.
4. Back on the **Dashboard** tab, click **💬 Test Teams** — you should see a
   "No Azure secrets expiring within the threshold." card appear in Teams.

### SMTP email (optional)

| Field | Example |
|---|---|
| SMTP host | `smtp.office365.com` |
| SMTP port | `587` |
| Use STARTTLS | ON for 587, OFF for 465-with-implicit-TLS |
| Username | `alerts@contoso.com` |
| Password | the mailbox/relay password (encrypted with DPAPI on save) |
| From | `alerts@contoso.com` |
| To | comma-separated recipients (`secops@contoso.com, oncall@contoso.com`) |
| Subject | `[Azure] Secret expiration report` |

Save, then click **✉ Test email** on the Dashboard.

---

## 11. Run your first scan

Open the **Dashboard** tab and click **▶ Scan now** (top-right) or
**🔄 Rescan**. Within a few seconds you should see populated rows and the
status counters update:

![Dashboard with results](screenshots/dashboard.png)

- The colored cards across the top show how many credentials fall in each
  bucket.
- Each row's left column is its severity (`EXPIRED`, `CRITICAL`, `WARNING`,
  or `OK`).
- Use the **Filter** box to narrow down by name / vault / kind.

If the configured notification channels are set up, **rising-severity items
are sent automatically** during this same scan — but only items whose
severity is higher than the last recorded state. A clean follow-up scan will
not re-spam.

---

## 12. Install the Windows Scheduled Task

This lets the scanner run daily without keeping the GUI open.

### From inside the GUI

Open **Scheduler** → **📅 Install Scheduled Task…**:

![Scheduler tab](screenshots/scheduler.png)

A PowerShell window opens. Approve any UAC prompt. The task is registered
under the name `AzureSecretMonitor`, daily at 08:00 local time, running as
the current Windows user.

### Or from PowerShell directly

```powershell
cd C:\AzureSecretMonitor\windows
powershell -ExecutionPolicy Bypass -File .\Install-ScheduledTask.ps1 -Time 07:30
```

Useful flags:

| Flag | Purpose |
|---|---|
| `-Time HH:mm` | When the task runs daily (default `08:00`). |
| `-PythonPath C:\Python312\python.exe` | Pin a specific interpreter. |
| `-TaskName MyMonitor` | Override the task name. |

> The task **must** run as the same Windows user that saved settings in the
> GUI — DPAPI keys are profile-bound. If you switch users, save settings
> again under the new account.

Verify the task in **Task Scheduler** → **Task Scheduler Library** →
`AzureSecretMonitor`. Right-click → **Run** to fire it immediately.

Output is appended to `C:\ProgramData\AzureSecretMonitor\logs\cli.log`.

---

## 13. Verify everything works

```powershell
cd C:\AzureSecretMonitor\python
python cli.py --dry-run
```

You should see a status table printed to the console. Exit code:

| Code | Meaning |
|---|---|
| `0` | Clean — nothing in the threshold window |
| `1` | At least one item is in the window but not yet expired |
| `2` | At least one item is **already expired** |
| `3` | Config missing — re-open the GUI and save |

Then run a real scan (notifications enabled):

```powershell
python cli.py
type C:\ProgramData\AzureSecretMonitor\logs\cli.log
```

Confirm a Teams card and/or email arrived.

---

## 14. Troubleshooting

| Symptom | Fix |
|---|---|
| **GUI doesn't start, `ModuleNotFoundError: tkinter`** | Re-run the Python installer and tick "tcl/tk and IDLE". |
| **`AADSTS7000215: Invalid client secret`** | The secret in the GUI doesn't match the one in Entra ID, or it expired. Generate a new client secret and paste the **value** (not the secret ID). |
| **Graph 403 on `/applications`** | `Application.Read.All` is missing or admin consent wasn't granted. Re-check step 7. |
| **Key Vault 403** | Role assignment hasn't propagated, or wrong vault name. Wait 5 min and retry; double-check the vault **name** (not URL) in the GUI. |
| **`Scheduled Task fails with exit code 3`** | The task is running as a user who never saved settings. Either run the GUI under that user once, or re-register the task under the user who has the config. |
| **`CryptUnprotectData failed`** in the log | The DPAPI blob can't be decrypted by the current user — same root cause as above. |
| **No Teams card** | The webhook URL changed. Reconfigure with a fresh URL and retry **Test Teams**. |
| **SMTP `auth failed`** | Office 365 requires either SMTP AUTH explicitly enabled on the mailbox or a high-trust relay. Try a dedicated relay account. |
| **Same item alerts every day** | `state.json` was deleted or the item bounced between severities. Either accept it or raise the threshold so the item stays in one bucket. |

Increase verbosity by running:

```powershell
python cli.py -v
```

---

## 15. Appendix: file locations and exit codes

### File layout

```
C:\AzureSecretMonitor\
  python\
    gui.py            # GUI entry point
    cli.py            # headless run (used by Scheduled Task)
    core.py           # scanning + notification logic
    config_store.py   # DPAPI config storage
    requirements.txt
  windows\
    Start-Monitor.bat
    Install-ScheduledTask.ps1
  powershell\
    Monitor-AzureSecrets.ps1   # pure-PowerShell alternative
```

### Runtime data

```
%APPDATA%\AzureSecretMonitor\           # per-user
  config.json     non-sensitive settings
  secret.bin      client secret, DPAPI-encrypted
  smtp.bin        SMTP password, DPAPI-encrypted
  state.json      last-notified severity per item

%ProgramData%\AzureSecretMonitor\logs\  # machine-wide
  cli.log         Scheduled Task output
```

### CLI flags

```
python cli.py [--dry-run] [--json] [--ignore-state] [-v]
```

| Flag | Effect |
|---|---|
| `--dry-run` | Print results, skip all notifications. |
| `--json` | Emit JSON instead of a table (good for piping into other tools). |
| `--ignore-state` | Notify on every matching item, regardless of last-notified state. |
| `-v` / `--verbose` | DEBUG logging. |

### Uninstall

```powershell
Unregister-ScheduledTask -TaskName AzureSecretMonitor -Confirm:$false
Remove-Item -Recurse "$env:APPDATA\AzureSecretMonitor"
Remove-Item -Recurse "$env:ProgramData\AzureSecretMonitor"
Remove-Item -Recurse C:\AzureSecretMonitor
```

And, in Entra ID, delete the client secret (and optionally the whole app
registration) to revoke access.
