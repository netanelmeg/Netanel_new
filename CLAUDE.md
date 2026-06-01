# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Azure Secret Expiration Monitor** — a Windows Server desktop application that scans Azure Entra ID app registrations and Key Vault items for expiring credentials, then sends notifications via Microsoft Teams and/or SMTP email. Runs on-premises using a service principal. Sensitive credentials (client secret, SMTP password) are encrypted with Windows DPAPI under the running user.

## Commands

### Run from source (Windows)

```powershell
cd python
pip install -r requirements.txt

# Launch GUI
python gui.py

# Headless CLI (used by Scheduled Task)
python cli.py [--dry-run] [--json] [--ignore-state] [-v]

# Validate config without sending notifications
python cli.py --dry-run
```

### Build EXE and MSI (Windows only, requires PyInstaller + WiX v3)

```powershell
cd windows
powershell -ExecutionPolicy Bypass -File .\Build-Exe.ps1
powershell -ExecutionPolicy Bypass -File .\Build-Msi.ps1 -Version 1.0.0.0
# Or skip re-building EXEs:
powershell -ExecutionPolicy Bypass -File .\Build-Msi.ps1 -SkipExeBuild -Version 1.0.0.0
```

Outputs land in `dist/`: `AzureSecretMonitor.exe`, `AzureSecretMonitorCli.exe`, `AzureSecretMonitor.msi`.

### Install Scheduled Task

```powershell
# Via GUI: Scheduler tab → "Install Scheduled Task..."
# Or directly:
powershell -ExecutionPolicy Bypass -File windows\Install-ScheduledTask.ps1 -Time 07:30
```

### One-time machine-wide permission setup (run as Administrator)

```powershell
powershell -ExecutionPolicy Bypass -File windows\Initialize-Permissions.ps1
```

### Cut a release

```powershell
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions (`.github/workflows/build-release.yml`) builds on `windows-latest`, produces all three artifacts, and attaches them to the release.

## Architecture

### Module relationships

```
gui.py          ──┐
cli.py          ──┤──> core.py           (scanning, notifications, rendering)
                  └──> config_store.py   (DPAPI-encrypted config + state on disk)
                       permissions.py    (role model — used only by gui.py)
```

`core.py` has **no UI imports** and is safe to import in any context. All Azure SDK calls, notification logic, and the `ExpiringItem` / `AppConfig` dataclasses live there.

`config_store.py` depends on `core.AppConfig` only. It owns DPAPI encryption/decryption, the on-disk file layout, and role/state serialization.

`gui.py` imports everything and wires it together inside a `ttkbootstrap.Window` subclass (`App`).

### Data flow for a scan

1. `config_store.load_config()` → reads `config.json` and decrypts `secret.bin` / `smtp.bin` via DPAPI.
2. `core.scan_all(cfg)` → authenticates with `ClientSecretCredential`, calls Microsoft Graph (app registrations) and Azure Key Vault SDKs (secrets, keys, certs), returns `list[ExpiringItem]`.
3. `core.filter_items(items, threshold_days, include_ok)` → drops items outside the window and sorts by `expires_on`.
4. `core.items_needing_alert(items, prior_state)` → filters to items whose severity **rose** since last run (deduplication); mutates `prior_state` in place.
5. `core.notify_teams()` / `core.notify_email()` → sends alerts.
6. `config_store.save_state(state)` → persists updated severity state to `state.json`.

### Severity model

Statuses are derived from `days_remaining` at read time (not stored):

| Status | Condition |
|---|---|
| `EXPIRED` | `days_remaining < 0` |
| `CRITICAL` | `≤ 7 days` |
| `WARNING` | `≤ threshold_days` (default 30) |
| `OK` | outside window |

Alert deduplication fires **only when severity rises** (`OK → WARNING → CRITICAL → EXPIRED`). The same item won't re-alert until it moves to a worse bucket. `state.json` tracks the last-notified status per item via `ExpiringItem.state_key()`.

### On-disk file layout

```
%APPDATA%\AzureSecretMonitor\     ← per-user (config_store.config_dir())
  config.json     non-sensitive settings (tenant/client IDs, vault names, etc.)
  secret.bin      client secret — DPAPI-encrypted, CurrentUser scope
  smtp.bin        SMTP password — DPAPI-encrypted, CurrentUser scope
  state.json      last-notified severity per item (dedup state)

%ProgramData%\AzureSecretMonitor\  ← machine-wide (config_store.system_config_dir())
  roles.json      Windows username → role; writable only by Administrators
  logs\audit.log  append-only JSON-lines audit trail
  logs\cli.log    Scheduled Task stdout/stderr
```

### DPAPI encryption

`config_store.protect_secret()` / `unprotect_secret()` call `CryptProtectData` / `CryptUnprotectData` via ctypes on Windows. On non-Windows (dev/test only), it falls back to a base64 `PLAIN:` prefix with a warning — never use this in production.

Encrypted blobs are profile-bound: only the Windows user who encrypted them can decrypt. The Scheduled Task must run as the same user who saved settings in the GUI.

### Role model

Three roles in `permissions.py`, hierarchical (each inherits the lower):

- **Reader** — view dashboard, run scans, send test notifications
- **Contributor** — above + renew/extend credentials, edit notification/scan-scope settings
- **Admin** — above + edit Azure connection, install Scheduled Task, manage role assignments

Role assignments live in `%ProgramData%\AzureSecretMonitor\roles.json`, ACL-restricted to Administrators-only writes. The `*` key is the fallback for unlisted users (defaults to `Reader`).

Bootstrap: the first Windows Administrator to launch the GUI is auto-promoted to Admin in the app (via `permissions.bootstrap_if_empty()`). This requires `Initialize-Permissions.ps1` to have been run first.

The local role model is **UI-level gating only** — the real authorization is Azure's service principal permissions. A local Admin who tries to renew a Key Vault secret without the right Azure role will get a 403 from Azure (recorded in `audit.log`).

### GUI structure (`gui.py`)

The `App` class (subclasses `ttkbootstrap.Window`) builds a sidebar-navigated window. Each sidebar button swaps the main frame to a different `*Frame` inner class. Tabs: Dashboard, Azure, Notifications, Scheduler, Permissions.

Background scans run in a `threading.Thread`; results are posted back to the main thread via `self.event_queue` (a `queue.Queue`) and processed in a `_poll_queue()` loop using `after()`.

Themes: `cosmo` (light) / `darkly` (dark), switchable at runtime. Row colors in the Treeview are set via `tag_configure`.

### Packaging

`windows/AzureSecretMonitor.spec` is the PyInstaller spec for both EXEs. It bundles the PowerShell helper scripts as data files so "Install Scheduled Task" works from a frozen build.

The MSI is built with WiX Toolset v3 (`installer.wxs`). The `UpgradeCode` GUID is fixed so monotonically increasing `ProductVersion` values upgrade cleanly. The MSI runs `Initialize-Permissions.ps1` at install time.

## Key conventions

- `core.py` must remain import-safe with no UI dependencies — keep Azure SDK, dataclasses, and notification logic there.
- All new audit-worthy actions (credential changes, role changes, settings saves) should call `core.audit_event()`. Never pass secret values into the `detail` field — it is truncated to 500 chars but callers must still sanitize.
- SMTP header fields (`From`, `To`, `Subject`) must pass through `core._sanitize_header()` before use to prevent header injection.
- OData filter values built from user input must pass through `core._odata_escape()`.
- CLI exit codes are load-bearing: `0` clean, `1` items in window, `2` expired, `3` config missing.
- The non-Windows DPAPI fallback (`PLAIN:`) is intentional for local dev; never ship it.
