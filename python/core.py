"""Core scanning, auth, and notification logic.

Used by both the GUI (`gui.py`) and the CLI (`cli.py`). No UI imports.
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable, Iterable

import requests
from azure.identity import ClientSecretCredential
from azure.keyvault.certificates import CertificateClient
from azure.keyvault.keys import KeyClient
from azure.keyvault.secrets import SecretClient
from msgraph_core import GraphClient

LOG = logging.getLogger("azure-secret-monitor.core")

ProgressCallback = Callable[[str], None]


@dataclass
class ExpiringItem:
    source: str          # "AppRegistration" or "KeyVault"
    kind: str            # "ClientSecret", "Certificate", "Key", "Secret"
    name: str
    container: str       # app display name or vault name
    expires_on: datetime
    identifier: str = ""

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

    def state_key(self) -> str:
        return f"{self.source}|{self.container}|{self.kind}|{self.name}|{self.identifier}"


@dataclass
class AppConfig:
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    key_vaults: list[str] = field(default_factory=list)
    scan_app_registrations: bool = True
    threshold_days: int = 30
    include_ok: bool = False

    teams_webhook: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""              # comma-separated
    email_subject: str = "[Azure] Secret expiration report"

    schedule_enabled: bool = False
    schedule_interval_hours: int = 24

    def email_recipients(self) -> list[str]:
        return [a.strip() for a in self.email_to.split(",") if a.strip()]

    def validate_for_scan(self) -> list[str]:
        errors = []
        if not self.tenant_id:
            errors.append("Tenant ID is required.")
        elif not _is_uuid(self.tenant_id):
            errors.append("Tenant ID must be a GUID (e.g. 11111111-2222-3333-4444-555555555555).")
        if not self.client_id:
            errors.append("Client ID is required.")
        elif not _is_uuid(self.client_id):
            errors.append("Client ID must be a GUID.")
        if not self.client_secret:
            errors.append("Client secret is required.")
        if not self.scan_app_registrations and not self.key_vaults:
            errors.append("Enable App Registration scanning or add at least one Key Vault.")
        for v in self.key_vaults:
            if not _is_valid_vault_name(v):
                errors.append(f"Invalid Key Vault name: '{v}'. Names must be 3-24 chars, "
                              "alphanumeric or hyphen.")
        return errors


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_VAULT_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{1,22}[a-zA-Z0-9])$")


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s.strip()))


def _is_valid_vault_name(s: str) -> bool:
    return bool(_VAULT_RE.match(s.strip()))


def _odata_escape(s: str) -> str:
    """Escape a value for safe inclusion inside an OData single-quoted string."""
    return s.replace("'", "''")


_HEADER_INJECTION = re.compile(r"[\r\n]")


def _sanitize_header(value: str) -> str:
    """Strip control chars that would let a setting break out of a header.

    SMTP/MIME headers terminate at CRLF, so a stray newline in From/To/Subject
    lets a writer inject arbitrary additional headers. Save-time validation
    plus run-time sanitization are layered.
    """
    return _HEADER_INJECTION.sub(" ", value).strip()


def make_credential(cfg: AppConfig) -> ClientSecretCredential:
    return ClientSecretCredential(
        tenant_id=cfg.tenant_id,
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
    )


def scan_app_registrations(credential: ClientSecretCredential,
                           progress: ProgressCallback | None = None) -> list[ExpiringItem]:
    if progress:
        progress("Scanning Entra ID app registrations...")
    LOG.info("Scanning Entra ID app registrations...")
    client = GraphClient(credential=credential)
    items: list[ExpiringItem] = []
    url = ("https://graph.microsoft.com/v1.0/applications"
           "?$select=appId,displayName,passwordCredentials,keyCredentials&$top=999")

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


def scan_key_vault(vault_name: str, credential: ClientSecretCredential,
                   progress: ProgressCallback | None = None) -> list[ExpiringItem]:
    if not _is_valid_vault_name(vault_name):
        raise ValueError(f"Invalid Key Vault name: {vault_name!r}")
    if progress:
        progress(f"Scanning Key Vault: {vault_name}")
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


def scan_all(cfg: AppConfig, progress: ProgressCallback | None = None) -> list[ExpiringItem]:
    credential = make_credential(cfg)
    items: list[ExpiringItem] = []
    if cfg.scan_app_registrations:
        try:
            items.extend(scan_app_registrations(credential, progress))
        except Exception as exc:
            LOG.error("App registration scan failed: %s", exc)
            if progress:
                progress(f"App registration scan failed: {exc}")
    for vault in cfg.key_vaults:
        try:
            items.extend(scan_key_vault(vault, credential, progress))
        except Exception as exc:
            LOG.error("Key Vault %s scan failed: %s", vault, exc)
            if progress:
                progress(f"Key Vault {vault} scan failed: {exc}")
    return items


def filter_items(items: Iterable[ExpiringItem], threshold_days: int,
                 include_ok: bool) -> list[ExpiringItem]:
    cutoff = datetime.now(timezone.utc) + timedelta(days=threshold_days)
    out = [i for i in items if include_ok or i.expires_on <= cutoff]
    out.sort(key=lambda i: i.expires_on)
    return out


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- rendering --------------------------------------------------------------

def render_console(items: list[ExpiringItem]) -> str:
    if not items:
        return "No expiring secrets found within the threshold window."
    rows = [f"{'STATUS':<10} {'DAYS':>5}  {'SOURCE':<16} {'KIND':<12} {'CONTAINER':<35} NAME",
            "-" * 110]
    for i in items:
        rows.append(
            f"{i.status:<10} {i.days_remaining:>5}  "
            f"{i.source:<16} {i.kind:<12} {i.container[:34]:<35} {i.name}"
        )
    return "\n".join(rows)


def render_html(items: list[ExpiringItem]) -> str:
    if not items:
        return "<p>No expiring secrets within the threshold window.</p>"
    head = ("<tr><th>Status</th><th>Days</th><th>Source</th><th>Kind</th>"
            "<th>Container</th><th>Name</th><th>Expires (UTC)</th></tr>")
    colors = {"EXPIRED": "#ffb3b3", "CRITICAL": "#ffd6a5",
              "WARNING": "#fff3b0", "OK": "#d8f3dc"}
    body = "".join(
        f"<tr style='background:{colors.get(i.status, '#fff')}'>"
        f"<td>{i.status}</td><td>{i.days_remaining}</td>"
        f"<td>{i.source}</td><td>{i.kind}</td>"
        f"<td>{i.container}</td><td>{i.name}</td>"
        f"<td>{i.expires_on.strftime('%Y-%m-%d %H:%M')}</td></tr>"
        for i in items
    )
    return ("<table border='1' cellpadding='6' cellspacing='0' "
            f"style='border-collapse:collapse;font-family:Segoe UI,Arial'>{head}{body}</table>")


# --- notifications ----------------------------------------------------------

def notify_email(cfg: AppConfig, items: list[ExpiringItem]) -> None:
    if not (cfg.smtp_host and cfg.email_from and cfg.email_recipients()):
        return
    subject = _sanitize_header(
        cfg.email_subject or f"[Azure] {len(items)} secrets expiring soon")
    sender = _sanitize_header(cfg.email_from)
    recipients = [_sanitize_header(r) for r in cfg.email_recipients()]
    if not sender or not recipients:
        LOG.error("Refusing to send email: From or To became empty after sanitization.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(render_console(items), "plain"))
    msg.attach(MIMEText(render_html(items), "html"))

    password = cfg.smtp_password or os.getenv("SMTP_PASSWORD", "")
    LOG.info("Sending email via %s:%s to %s", cfg.smtp_host, cfg.smtp_port, msg["To"])
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
        if cfg.smtp_starttls:
            smtp.starttls()
        if cfg.smtp_username and password:
            smtp.login(cfg.smtp_username, password)
        smtp.sendmail(sender, recipients, msg.as_string())


def notify_teams(webhook_url: str, items: list[ExpiringItem]) -> None:
    if not webhook_url:
        return
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
    LOG.info("Posting to Teams webhook")
    r = requests.post(webhook_url, json={"text": text}, timeout=30)
    r.raise_for_status()


# --- lifecycle (renew / extend) --------------------------------------------

def add_app_password(credential: ClientSecretCredential, *,
                     app_object_id: str, display_name: str,
                     end_date: datetime) -> dict:
    """Add a new password credential to an existing Entra ID app registration.

    Returns the Graph response — including the one-time `secretText` — which
    the caller is expected to surface to the operator immediately. The value
    is never persisted.

    Requires Graph permission `Application.ReadWrite.OwnedBy` (or
    `Application.ReadWrite.All`) for the calling SP.
    """
    client = GraphClient(credential=credential)
    body = {
        "passwordCredential": {
            "displayName": display_name,
            "endDateTime": _aware(end_date).isoformat().replace("+00:00", "Z"),
        }
    }
    url = f"https://graph.microsoft.com/v1.0/applications/{app_object_id}/addPassword"
    resp = client.post(url, json=body)
    if resp.status_code >= 300:
        raise RuntimeError(f"addPassword failed {resp.status_code}: {resp.text}")
    return resp.json()


def find_app_object_id(credential: ClientSecretCredential, *, app_id: str) -> str:
    """Resolve an app registration's `appId` (client ID) to its object ID."""
    if not _is_uuid(app_id):
        raise ValueError(f"app_id must be a UUID, got: {app_id!r}")
    client = GraphClient(credential=credential)
    safe_app_id = _odata_escape(app_id)
    url = (f"https://graph.microsoft.com/v1.0/applications"
           f"?$filter=appId eq '{safe_app_id}'&$select=id,appId")
    resp = client.get(url)
    if resp.status_code >= 300:
        raise RuntimeError(f"applications lookup failed {resp.status_code}: {resp.text}")
    values = resp.json().get("value", [])
    if not values:
        raise RuntimeError(f"No application with appId {app_id}")
    return values[0]["id"]


def renew_keyvault_secret_expiry(credential: ClientSecretCredential, *,
                                 vault_name: str, secret_name: str,
                                 new_expires_on: datetime) -> None:
    vault_url = f"https://{vault_name}.vault.azure.net"
    client = SecretClient(vault_url=vault_url, credential=credential)
    secret = client.get_secret(secret_name)
    client.update_secret_properties(
        secret_name, version=secret.properties.version,
        expires_on=_aware(new_expires_on),
    )


def renew_keyvault_key_expiry(credential: ClientSecretCredential, *,
                              vault_name: str, key_name: str,
                              new_expires_on: datetime) -> None:
    vault_url = f"https://{vault_name}.vault.azure.net"
    client = KeyClient(vault_url=vault_url, credential=credential)
    key = client.get_key(key_name)
    client.update_key_properties(
        key_name, version=key.properties.version,
        expires_on=_aware(new_expires_on),
    )


def renew_keyvault_certificate_expiry(credential: ClientSecretCredential, *,
                                      vault_name: str, cert_name: str,
                                      new_expires_on: datetime) -> None:
    """Bump the `expires_on` on the certificate's properties.

    Note: this only updates the metadata. To actually issue a new certificate
    use the vault's certificate policy via `begin_create_certificate`.
    """
    vault_url = f"https://{vault_name}.vault.azure.net"
    client = CertificateClient(vault_url=vault_url, credential=credential)
    cert = client.get_certificate(cert_name)
    client.update_certificate_properties(
        cert_name, version=cert.properties.version,
        expires_on=_aware(new_expires_on),
    )


# --- audit log --------------------------------------------------------------

_AUDIT_MAX_DETAIL = 500


def audit_event(log_path: str, *, actor: str, role: str, action: str,
                target: str, success: bool, detail: str = "") -> None:
    """Append a single JSON-line audit event.

    `detail` is truncated to avoid accidentally persisting large error blobs
    that could include sensitive material (tokens, full request bodies).
    Callers should NEVER pass secret values to `detail`; this is only a
    last-ditch cap.
    """
    import json
    safe_detail = (detail or "")[:_AUDIT_MAX_DETAIL].replace("\r", " ").replace("\n", " ")
    record = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actor": actor[:80],
        "role": role[:32],
        "action": action[:64],
        "target": target[:256],
        "success": bool(success),
        "detail": safe_detail,
    }
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        LOG.error("Could not write audit log %s: %s", log_path, exc)


def severity_rank(status: str) -> int:
    return {"OK": 0, "WARNING": 1, "CRITICAL": 2, "EXPIRED": 3}.get(status, -1)


def items_needing_alert(items: list[ExpiringItem], prior_state: dict) -> list[ExpiringItem]:
    """Filter to items whose severity is higher than the last notified severity.

    `prior_state` maps state_key -> last notified status. Mutated in place
    with the new statuses for items that warrant alerting.
    """
    out = []
    for i in items:
        prev = prior_state.get(i.state_key())
        if prev is None or severity_rank(i.status) > severity_rank(prev):
            out.append(i)
            prior_state[i.state_key()] = i.status
    return out
