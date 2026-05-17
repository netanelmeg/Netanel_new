"""Role-based permission model.

Three roles, hierarchical:

    Reader  →  Contributor  →  Admin

Each higher role inherits all capabilities of the lower ones. The current
user's role is looked up from the saved role map (Windows username → role).
Anyone not in the map falls back to the wildcard `*` entry, which defaults
to Reader.

Bootstrapping: the very first Windows user to launch the GUI is promoted to
Admin automatically (so the install isn't unmanageable). After that, only
existing Admins can change role assignments.

Note: these checks live in the UI/CLI layer. The *real* authorization is
enforced by Azure on the service-principal credentials — the local role
model prevents accidental misuse and provides an audit trail, but a
determined operator with file-system access could edit role_assignments.json.
For hard enforcement, deploy with an SP that has only the permissions the
weakest user should have.
"""

from __future__ import annotations

import enum
import getpass
from dataclasses import dataclass
from typing import Iterable


class Role(str, enum.Enum):
    READER = "reader"
    CONTRIBUTOR = "contributor"
    ADMIN = "admin"

    @property
    def label(self) -> str:
        return {"reader": "Reader", "contributor": "Contributor", "admin": "Admin"}[self.value]

    @property
    def rank(self) -> int:
        return {"reader": 0, "contributor": 1, "admin": 2}[self.value]


class Permission(str, enum.Enum):
    VIEW_DASHBOARD     = "view_dashboard"
    RUN_SCAN           = "run_scan"
    TEST_NOTIFICATIONS = "test_notifications"
    RENEW_CREDENTIAL   = "renew_credential"
    EDIT_NOTIFICATIONS = "edit_notifications"
    EDIT_SCAN_SCOPE    = "edit_scan_scope"
    EDIT_AZURE_CONN    = "edit_azure_conn"
    INSTALL_TASK       = "install_scheduled_task"
    MANAGE_ROLES       = "manage_roles"

    @property
    def label(self) -> str:
        return {
            "view_dashboard":     "View dashboard",
            "run_scan":           "Run scan",
            "test_notifications": "Send test notifications",
            "renew_credential":   "Renew / extend credentials",
            "edit_notifications": "Edit notification settings",
            "edit_scan_scope":    "Edit scan scope",
            "edit_azure_conn":    "Edit Azure connection",
            "install_scheduled_task": "Install Scheduled Task",
            "manage_roles":       "Manage role assignments",
        }[self.value]


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.READER: {
        Permission.VIEW_DASHBOARD,
        Permission.RUN_SCAN,
        Permission.TEST_NOTIFICATIONS,
    },
    Role.CONTRIBUTOR: {
        Permission.RENEW_CREDENTIAL,
        Permission.EDIT_NOTIFICATIONS,
        Permission.EDIT_SCAN_SCOPE,
    },
    Role.ADMIN: {
        Permission.EDIT_AZURE_CONN,
        Permission.INSTALL_TASK,
        Permission.MANAGE_ROLES,
    },
}


def effective_permissions(role: Role) -> set[Permission]:
    """Resolve a role to all permissions, including inherited ones."""
    out: set[Permission] = set()
    for r in Role:
        if r.rank <= role.rank:
            out.update(ROLE_PERMISSIONS[r])
    return out


@dataclass
class RoleAssignments:
    """user (Windows username, case-insensitive) → role.

    The wildcard `*` is the fallback for anyone not listed.
    """
    mapping: dict[str, Role]

    def role_for(self, username: str) -> Role:
        key = username.lower().strip()
        if key in self.mapping:
            return self.mapping[key]
        return self.mapping.get("*", Role.READER)

    def users_with(self, role: Role) -> list[str]:
        return sorted(u for u, r in self.mapping.items() if r == role and u != "*")

    def set(self, username: str, role: Role) -> None:
        self.mapping[username.lower().strip()] = role

    def remove(self, username: str) -> None:
        key = username.lower().strip()
        if key == "*":
            return
        self.mapping.pop(key, None)

    def to_serializable(self) -> dict[str, str]:
        return {u: r.value for u, r in self.mapping.items()}

    @classmethod
    def from_serializable(cls, data: dict[str, str] | None) -> "RoleAssignments":
        if not data:
            return cls(mapping={"*": Role.READER})
        out: dict[str, Role] = {}
        for u, r in data.items():
            try:
                out[u.lower().strip()] = Role(r)
            except ValueError:
                continue
        out.setdefault("*", Role.READER)
        return cls(mapping=out)


def current_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def can(role: Role, permission: Permission) -> bool:
    return permission in effective_permissions(role)


def bootstrap_if_empty(assignments: RoleAssignments, *,
                       is_os_admin: bool) -> bool:
    """Promote the current user to Admin **only** if they are an OS Administrator
    and no Admin is already assigned.

    Without the OS-admin gate, any user could become Admin in the app simply
    by launching it first under their own profile — defeating the whole role
    model. This way the very first promotion requires a Windows
    Administrator (matching the ACL on roles.json).

    Returns True if a bootstrap promotion happened.
    """
    if any(r == Role.ADMIN for r in assignments.mapping.values()):
        return False
    if not is_os_admin:
        return False
    assignments.set(current_username(), Role.ADMIN)
    return True


def capability_matrix() -> list[tuple[Permission, dict[Role, bool]]]:
    """Render-ready: ordered list of (permission, {role: granted}) tuples."""
    perm_order: Iterable[Permission] = [
        Permission.VIEW_DASHBOARD,
        Permission.RUN_SCAN,
        Permission.TEST_NOTIFICATIONS,
        Permission.RENEW_CREDENTIAL,
        Permission.EDIT_NOTIFICATIONS,
        Permission.EDIT_SCAN_SCOPE,
        Permission.EDIT_AZURE_CONN,
        Permission.INSTALL_TASK,
        Permission.MANAGE_ROLES,
    ]
    out = []
    for p in perm_order:
        out.append((p, {r: can(r, p) for r in Role}))
    return out
