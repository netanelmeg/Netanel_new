"""On-disk config storage with Windows DPAPI encryption for the client secret.

- Per-user config lives in `%APPDATA%\\AzureSecretMonitor\\` (or
  `~/.config/azure-secret-monitor` on non-Windows for dev/test).
- `config.json` stores non-sensitive fields, `secret.bin` / `smtp.bin` store
  the DPAPI-encrypted client secret and SMTP password.
- `state.json` (per-user) deduplicates notifications across runs.

- Machine-wide files live in `%ProgramData%\\AzureSecretMonitor\\` so they
  cannot be bypassed by a non-admin user editing their own profile:
    - `roles.json`   role assignments (writable only by OS Administrators)
    - `logs\\audit.log`  append-only audit trail
  The PowerShell helper `windows\\Initialize-Permissions.ps1` creates this
  directory with the correct ACL.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from dataclasses import asdict
from pathlib import Path

from core import AppConfig

LOG = logging.getLogger("azure-secret-monitor.config")

APP_NAME = "AzureSecretMonitor"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    else:
        path = Path.home() / ".config" / "azure-secret-monitor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def system_config_dir() -> Path:
    """Machine-wide config, intentionally not under %APPDATA%.

    On Windows this is %ProgramData%, which the Initialize-Permissions.ps1
    helper ACLs so only Administrators can write to it.
    """
    if sys.platform == "win32":
        base = os.environ.get("ProgramData") or r"C:\ProgramData"
        path = Path(base) / APP_NAME
    else:
        path = Path("/var/lib/azure-secret-monitor")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Non-admin first launch — fall through; reads will work, writes won't.
        pass
    return path


def config_path() -> Path: return config_dir() / "config.json"
def secret_path() -> Path: return config_dir() / "secret.bin"
def state_path() -> Path:  return config_dir() / "state.json"


def roles_path() -> Path:
    """Machine-wide role assignments — writable only by Administrators."""
    return system_config_dir() / "roles.json"


def audit_log_path() -> Path:
    """Machine-wide audit log."""
    path = system_config_dir() / "logs"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        pass
    return path / "audit.log"


def is_windows_admin() -> bool:
    """Return True if running as a member of BUILTIN\\Administrators (Windows)."""
    if sys.platform != "win32":
        return os.geteuid() == 0  # convenient for non-Windows dev only
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


# --- DPAPI (Windows) --------------------------------------------------------

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    b = _DataBlob()
    b.cbData = len(data)
    b.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    return b, buf  # keep buf alive


def _dpapi_protect(data: bytes) -> bytes:
    in_blob, _keep = _blob(data)
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise OSError(ctypes.WinError().strerror)
    out = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)  # type: ignore[attr-defined]
    return out


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob, _keep = _blob(data)
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise OSError(ctypes.WinError().strerror)
    out = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)  # type: ignore[attr-defined]
    return out


def protect_secret(secret: str) -> bytes:
    if not secret:
        return b""
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return _dpapi_protect(raw)
    LOG.warning("DPAPI not available on this OS — storing client secret base64-only.")
    return b"PLAIN:" + base64.b64encode(raw)


def unprotect_secret(blob: bytes) -> str:
    if not blob:
        return ""
    if blob.startswith(b"PLAIN:"):
        return base64.b64decode(blob[6:]).decode("utf-8")
    if sys.platform == "win32":
        return _dpapi_unprotect(blob).decode("utf-8")
    raise RuntimeError("Encrypted secret found but DPAPI is only available on Windows.")


# --- load / save ------------------------------------------------------------

_SECRET_FIELD = "client_secret"


def load_config() -> AppConfig:
    cfg = AppConfig()
    cp = config_path()
    if cp.exists():
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        except Exception as exc:
            LOG.error("Failed to load config: %s", exc)

    sp = secret_path()
    if sp.exists():
        try:
            cfg.client_secret = unprotect_secret(sp.read_bytes())
        except Exception as exc:
            LOG.error("Failed to decrypt client secret: %s", exc)
            cfg.client_secret = ""
    return cfg


def save_config(cfg: AppConfig) -> None:
    data = asdict(cfg)
    secret = data.pop(_SECRET_FIELD, "") or ""
    # Never persist SMTP password in plaintext either; same DPAPI treatment.
    smtp_pwd = data.pop("smtp_password", "") or ""

    cp = config_path()
    cp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _restrict_perms(cp)

    sp = secret_path()
    if secret:
        sp.write_bytes(protect_secret(secret))
        _restrict_perms(sp)
    elif sp.exists():
        sp.unlink()

    pwd_path = config_dir() / "smtp.bin"
    if smtp_pwd:
        pwd_path.write_bytes(protect_secret(smtp_pwd))
        _restrict_perms(pwd_path)
    elif pwd_path.exists():
        pwd_path.unlink()


def load_smtp_password() -> str:
    p = config_dir() / "smtp.bin"
    if not p.exists():
        return ""
    try:
        return unprotect_secret(p.read_bytes())
    except Exception as exc:
        LOG.error("Failed to decrypt SMTP password: %s", exc)
        return ""


def _restrict_perms(p: Path) -> None:
    """Best-effort: chmod 600 on POSIX. Windows ACLs are inherited from the
    user's profile which is already user-scoped."""
    if sys.platform != "win32":
        try:
            p.chmod(0o600)
        except OSError:
            pass


# --- state (dedupe) ---------------------------------------------------------

def load_state() -> dict:
    sp = state_path()
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


# --- role assignments -------------------------------------------------------

def load_roles() -> dict:
    rp = roles_path()
    if not rp.exists():
        return {}
    try:
        return json.loads(rp.read_text(encoding="utf-8"))
    except Exception as exc:
        LOG.error("Failed to load role assignments: %s", exc)
        return {}


def save_roles(roles: dict) -> None:
    rp = roles_path()
    try:
        rp.write_text(json.dumps(roles, indent=2, sort_keys=True), encoding="utf-8")
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot write {rp}. The role file is restricted to Windows "
            f"Administrators by design — re-launch the GUI as an Administrator "
            f"to change role assignments, or run "
            f"windows\\Initialize-Permissions.ps1 first."
        ) from exc
    _restrict_perms(rp)
