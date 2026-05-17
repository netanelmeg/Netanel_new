"""Render screenshots of the GUI for documentation.

Stubs the Azure / Graph / requests imports so the GUI can be loaded without
network access or heavyweight dependencies, populates the dashboard with
sample items, and captures each tab as a PNG via xwd + ImageMagick.

Run under a virtual display:

    xvfb-run -a -s '-screen 0 1400x900x24' python3.12 docs/screenshot.py

Outputs to docs/screenshots/.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

# --- Stub heavyweight deps so gui.py imports cleanly ------------------------

def _stub(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

class _Cred:
    def __init__(self, *a, **kw): pass

_stub("azure")
_stub("azure.identity", ClientSecretCredential=_Cred, DefaultAzureCredential=_Cred)
_stub("azure.keyvault")
_stub("azure.keyvault.secrets", SecretClient=lambda **kw: types.SimpleNamespace(
    list_properties_of_secrets=lambda: []))
_stub("azure.keyvault.keys", KeyClient=lambda **kw: types.SimpleNamespace(
    list_properties_of_keys=lambda: []))
_stub("azure.keyvault.certificates", CertificateClient=lambda **kw: types.SimpleNamespace(
    list_properties_of_certificates=lambda: []))
_stub("msgraph_core", GraphClient=lambda credential: types.SimpleNamespace(
    get=lambda url: types.SimpleNamespace(status_code=200, json=lambda: {"value": []})))
_stub("requests", post=lambda *a, **kw: types.SimpleNamespace(
    raise_for_status=lambda: None))

# --- Now safe to import the app ---------------------------------------------

import gui  # noqa: E402
from core import ExpiringItem  # noqa: E402

OUT = REPO / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def sample_items() -> list[ExpiringItem]:
    now = datetime.now(timezone.utc)
    raw = [
        ("AppRegistration", "ClientSecret", "prod-deployer",       "Contoso-CI-Pipeline",       -3),
        ("AppRegistration", "ClientSecret", "legacy-secret",       "Legacy-Reporting-App",      -45),
        ("AppRegistration", "Certificate",  "auth-cert-2025",      "Identity-Broker",            5),
        ("KeyVault",        "Secret",       "stripe-api-key",      "kv-prod-payments",           2),
        ("KeyVault",        "Secret",       "sendgrid-api-key",    "kv-prod-payments",          14),
        ("KeyVault",        "Certificate",  "wildcard-contoso",    "kv-prod-platform",          22),
        ("KeyVault",        "Key",          "tenant-encryption",   "kv-prod-platform",          27),
        ("AppRegistration", "ClientSecret", "datadog-integration", "Observability-Stack",       60),
        ("KeyVault",        "Secret",       "ado-pat-token",       "kv-shared-tools",           90),
        ("KeyVault",        "Certificate",  "internal-ca",         "kv-shared-tools",          340),
    ]
    return [
        ExpiringItem(source=s, kind=k, name=n, container=c,
                     expires_on=now + timedelta(days=d), identifier="demo")
        for s, k, n, c, d in raw
    ]


def capture(window_id: str, name: str) -> None:
    raw = OUT / f"{name}.xwd"
    png = OUT / f"{name}.png"
    subprocess.run(["xwd", "-id", window_id, "-out", str(raw)], check=True)
    subprocess.run(["convert", str(raw), str(png)], check=True)
    raw.unlink()
    print(f"  wrote {png.relative_to(REPO)}")


def main() -> None:
    app = gui.App()

    # Pre-fill demo settings so the form looks populated, not empty.
    app.tenant_var.set("11111111-2222-3333-4444-555555555555")
    app.client_id_var.set("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    app.client_secret_var.set("•" * 24)
    app.threshold_var.set(30)
    app.app_reg_var.set(True)
    app.vaults_text.delete("1.0", "end")
    app.vaults_text.insert("1.0", "kv-prod-payments\nkv-prod-platform\nkv-shared-tools")

    app.teams_var.set("https://contoso.webhook.office.com/webhookb2/abc123/IncomingWebhook/...")
    app.smtp_host_var.set("smtp.office365.com")
    app.smtp_port_var.set(587)
    app.smtp_user_var.set("alerts@contoso.com")
    app.smtp_pwd_var.set("•" * 16)
    app.email_from_var.set("alerts@contoso.com")
    app.email_to_var.set("secops@contoso.com, platform-team@contoso.com")
    app.email_subject_var.set("[Azure] Secret expiration report")

    app.sched_on_var.set(True)
    app.sched_hours_var.set(24)

    app._render_items(sample_items())
    app.status_var.set("Demo data — last scan 2026-05-14 09:42:11")

    app.update_idletasks()
    app.update()

    for name in ["dashboard", "azure", "notifications", "scheduler", "permissions"]:
        app._show_page(name)
        app.update_idletasks()
        app.update()
        app.after(200)
        app.update()
        capture(hex(app.winfo_id()), name)

    app.destroy()


if __name__ == "__main__":
    main()
