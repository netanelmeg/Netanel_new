"""Azure Secret Expiration Monitor.

Scans Azure AD App Registration credentials (client secrets and certificates)
and Azure Key Vault items (secrets, keys, certificates) and notifies when any
of them are expired or will expire within a configurable threshold.

Notifications can be sent to:
  - SMTP email
  - Microsoft Teams (Incoming Webhook)
  - Console (always)

Authentication uses azure-identity's DefaultAzureCredential, so the same code
works locally (az login), in CI (env vars / federated), and in Azure
(Managed Identity).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable

import requests
import yaml
from azure.identity import DefaultAzureCredential
from azure.keyvault.certificates import CertificateClient
from azure.keyvault.keys import KeyClient
from azure.keyvault.secrets import SecretClient
from msgraph_core import GraphClient

LOG = logging.getLogger("azure-secret-monitor")


@dataclass
class ExpiringItem:
    source: str          # "AppRegistration" or "KeyVault"
    kind: str            # "ClientSecret", "Certificate", "Key", "Secret"
    name: str            # display name
    container: str       # app display name or vault name
    expires_on: datetime
    identifier: str = "" # appId, keyId, certId, etc.

    @property
    def days_remaining(self) -> int:
        delta = self.expires_on - datetime.now(timezone.utc)
        return int(delta.total_seconds() // 86400)

    @property
    def status(self) -> str:
        d = self.days_remaining
        if d < 0:
            return "EXPIRED"
        if d <= 7:
            return "CRITICAL"
        if d <= 30:
            return "WARNING"
        return "OK"


@dataclass
class Config:
    threshold_days: int = 30
    app_registrations: bool = True
    key_vaults: list[str] = field(default_factory=list)
    notify_console: bool = True
    notify_email: dict | None = None
    notify_teams_webhook: str | None = None
    include_ok: bool = False


def load_config(path: str | None) -> Config:
    """Load configuration from a YAML file, falling back to env vars."""
    data: dict = {}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    cfg = Config(
        threshold_days=int(data.get("threshold_days", os.getenv("THRESHOLD_DAYS", 30))),
        app_registrations=bool(data.get("app_registrations", True)),
        key_vaults=data.get("key_vaults") or _split_env("KEY_VAULTS"),
        notify_console=bool(data.get("notify_console", True)),
        notify_email=data.get("email"),
        notify_teams_webhook=data.get("teams_webhook") or os.getenv("TEAMS_WEBHOOK"),
        include_ok=bool(data.get("include_ok", False)),
    )
    return cfg


def _split_env(key: str) -> list[str]:
    raw = os.getenv(key, "")
    return [v.strip() for v in raw.split(",") if v.strip()]


def scan_app_registrations(credential: DefaultAzureCredential) -> list[ExpiringItem]:
    """Enumerate all Entra ID app registrations and their credentials."""
    LOG.info("Scanning Entra ID app registrations...")
    client = GraphClient(credential=credential)
    items: list[ExpiringItem] = []
    url = "https://graph.microsoft.com/v1.0/applications?$select=appId,displayName,passwordCredentials,keyCredentials&$top=999"

    while url:
        resp = client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Graph error {resp.status_code}: {resp.text}")
        payload = resp.json()
        for app in payload.get("value", []):
            display_name = app.get("displayName", "<unnamed>")
            app_id = app.get("appId", "")
            for pwd in app.get("passwordCredentials", []) or []:
                end = _parse_iso(pwd.get("endDateTime"))
                if end:
                    items.append(ExpiringItem(
                        source="AppRegistration",
                        kind="ClientSecret",
                        name=pwd.get("displayName") or pwd.get("keyId", "secret"),
                        container=display_name,
                        expires_on=end,
                        identifier=app_id,
                    ))
            for cert in app.get("keyCredentials", []) or []:
                end = _parse_iso(cert.get("endDateTime"))
                if end:
                    items.append(ExpiringItem(
                        source="AppRegistration",
                        kind="Certificate",
                        name=cert.get("displayName") or cert.get("keyId", "cert"),
                        container=display_name,
                        expires_on=end,
                        identifier=app_id,
                    ))
        url = payload.get("@odata.nextLink")
    LOG.info("Found %d app registration credentials", len(items))
    return items


def scan_key_vault(vault_name: str, credential: DefaultAzureCredential) -> list[ExpiringItem]:
    """Enumerate secrets, keys, and certificates in a Key Vault."""
    LOG.info("Scanning Key Vault: %s", vault_name)
    vault_url = f"https://{vault_name}.vault.azure.net"
    items: list[ExpiringItem] = []

    secret_client = SecretClient(vault_url=vault_url, credential=credential)
    for prop in secret_client.list_properties_of_secrets():
        if prop.expires_on:
            items.append(ExpiringItem(
                source="KeyVault", kind="Secret", name=prop.name,
                container=vault_name, expires_on=_aware(prop.expires_on),
                identifier=prop.id or "",
            ))

    key_client = KeyClient(vault_url=vault_url, credential=credential)
    for prop in key_client.list_properties_of_keys():
        if prop.expires_on:
            items.append(ExpiringItem(
                source="KeyVault", kind="Key", name=prop.name,
                container=vault_name, expires_on=_aware(prop.expires_on),
                identifier=prop.id or "",
            ))

    cert_client = CertificateClient(vault_url=vault_url, credential=credential)
    for prop in cert_client.list_properties_of_certificates():
        if prop.expires_on:
            items.append(ExpiringItem(
                source="KeyVault", kind="Certificate", name=prop.name,
                container=vault_name, expires_on=_aware(prop.expires_on),
                identifier=prop.id or "",
            ))

    return items


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def filter_items(items: Iterable[ExpiringItem], threshold_days: int,
                 include_ok: bool) -> list[ExpiringItem]:
    cutoff = datetime.now(timezone.utc) + timedelta(days=threshold_days)
    out = []
    for item in items:
        if include_ok or item.expires_on <= cutoff:
            out.append(item)
    out.sort(key=lambda i: i.expires_on)
    return out


def render_console(items: list[ExpiringItem]) -> str:
    if not items:
        return "No expiring secrets found within the threshold window."
    rows = [
        f"{'STATUS':<10} {'DAYS':>5}  {'SOURCE':<16} {'KIND':<12} {'CONTAINER':<35} NAME"
    ]
    rows.append("-" * 110)
    for i in items:
        rows.append(
            f"{i.status:<10} {i.days_remaining:>5}  "
            f"{i.source:<16} {i.kind:<12} {i.container[:34]:<35} {i.name}"
        )
    return "\n".join(rows)


def render_html(items: list[ExpiringItem]) -> str:
    if not items:
        return "<p>No expiring secrets found within the threshold window.</p>"
    head = (
        "<tr><th>Status</th><th>Days</th><th>Source</th><th>Kind</th>"
        "<th>Container</th><th>Name</th><th>Expires (UTC)</th></tr>"
    )
    body = "".join(
        f"<tr style='background:{_color(i.status)}'>"
        f"<td>{i.status}</td><td>{i.days_remaining}</td>"
        f"<td>{i.source}</td><td>{i.kind}</td>"
        f"<td>{i.container}</td><td>{i.name}</td>"
        f"<td>{i.expires_on.strftime('%Y-%m-%d %H:%M')}</td></tr>"
        for i in items
    )
    return (
        "<table border='1' cellpadding='6' cellspacing='0' "
        f"style='border-collapse:collapse;font-family:Segoe UI,Arial'>{head}{body}</table>"
    )


def _color(status: str) -> str:
    return {
        "EXPIRED": "#ffb3b3",
        "CRITICAL": "#ffd6a5",
        "WARNING": "#fff3b0",
        "OK": "#d8f3dc",
    }.get(status, "#ffffff")


def notify_email(cfg: dict, items: list[ExpiringItem]) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = cfg.get("subject", f"[Azure] {len(items)} secrets expiring soon")
    msg["From"] = cfg["from"]
    msg["To"] = ", ".join(cfg["to"]) if isinstance(cfg["to"], list) else cfg["to"]
    msg.attach(MIMEText(render_console(items), "plain"))
    msg.attach(MIMEText(render_html(items), "html"))

    host = cfg["smtp_host"]
    port = int(cfg.get("smtp_port", 587))
    username = cfg.get("username")
    password = cfg.get("password") or os.getenv("SMTP_PASSWORD")
    use_tls = bool(cfg.get("starttls", True))

    LOG.info("Sending email via %s:%s to %s", host, port, msg["To"])
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)


def notify_teams(webhook_url: str, items: list[ExpiringItem]) -> None:
    if not items:
        text = "No Azure secrets expiring within the threshold."
    else:
        lines = [
            f"- **{i.status}** ({i.days_remaining}d) "
            f"`{i.source}/{i.kind}` {i.container} / {i.name} "
            f"(expires {i.expires_on.strftime('%Y-%m-%d')})"
            for i in items[:50]
        ]
        text = "**Azure secret expiration report**\n\n" + "\n".join(lines)
        if len(items) > 50:
            text += f"\n\n_…and {len(items) - 50} more_"
    payload = {"text": text}
    LOG.info("Posting to Teams webhook")
    r = requests.post(webhook_url, json=payload, timeout=30)
    r.raise_for_status()


def run(config_path: str | None, dry_run: bool, output_json: bool) -> int:
    cfg = load_config(config_path)
    credential = DefaultAzureCredential()

    all_items: list[ExpiringItem] = []
    if cfg.app_registrations:
        try:
            all_items.extend(scan_app_registrations(credential))
        except Exception as exc:
            LOG.error("App registration scan failed: %s", exc)
    for vault in cfg.key_vaults:
        try:
            all_items.extend(scan_key_vault(vault, credential))
        except Exception as exc:
            LOG.error("Key Vault %s scan failed: %s", vault, exc)

    items = filter_items(all_items, cfg.threshold_days, cfg.include_ok)

    if output_json:
        print(json.dumps([{
            "source": i.source, "kind": i.kind, "name": i.name,
            "container": i.container, "expires_on": i.expires_on.isoformat(),
            "days_remaining": i.days_remaining, "status": i.status,
            "identifier": i.identifier,
        } for i in items], indent=2))
    elif cfg.notify_console:
        print(render_console(items))

    if dry_run:
        LOG.info("Dry-run: skipping notifications")
        return _exit_code(items)

    if cfg.notify_email:
        try:
            notify_email(cfg.notify_email, items)
        except Exception as exc:
            LOG.error("Email notification failed: %s", exc)

    if cfg.notify_teams_webhook:
        try:
            notify_teams(cfg.notify_teams_webhook, items)
        except Exception as exc:
            LOG.error("Teams notification failed: %s", exc)

    return _exit_code(items)


def _exit_code(items: list[ExpiringItem]) -> int:
    """Return 2 if anything expired, 1 if anything in window, 0 otherwise."""
    if any(i.status == "EXPIRED" for i in items):
        return 2
    if items:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Azure secret expiration.")
    parser.add_argument("-c", "--config", help="Path to YAML config file", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Skip notifications")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(run(args.config, args.dry_run, args.json))


if __name__ == "__main__":
    main()
