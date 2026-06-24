"""Azure Secret Expiration Monitor — modern Windows GUI (ttkbootstrap).

Sidebar navigation, stat cards, themed widgets, and a light/dark switch.
Logic is unchanged from the prior tkinter build — only the look-and-feel
and layout are new.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import (
    BOTH, DANGER, END, INFO, LEFT, PRIMARY, RIGHT, SUCCESS, WARNING, X, Y,
)

import config_store
import permissions as perms
from core import (
    AppConfig, ConnectionTestResult, ExpiringItem,
    add_app_password, audit_event,
    filter_items, find_app_object_id, items_needing_alert,
    make_credential, notify_email, notify_teams,
    renew_keyvault_certificate_expiry, renew_keyvault_key_expiry,
    renew_keyvault_secret_expiry, scan_all, test_connection,
)
from permissions import Permission, Role, RoleAssignments

LOG = logging.getLogger("azure-secret-monitor.gui")

# Row colors for the Treeview (subtle tints; status badge column is the loud signal).
ROW_COLORS = {
    "EXPIRED":  "#fde2e2",
    "CRITICAL": "#fde7cf",
    "WARNING":  "#fff5cc",
    "OK":       "#e3f4e1",
}
STATUS_STYLES = {
    "EXPIRED":  "danger",
    "CRITICAL": "warning",
    "WARNING":  "warning",
    "OK":       "success",
}
LIGHT_THEME = "cosmo"
DARK_THEME = "darkly"


def _resource_path(rel_path: str) -> Path | None:
    """Locate a bundled resource, accounting for PyInstaller / MSI / dev runs.

    Search order:
      1. PyInstaller one-file extraction dir (`sys._MEIPASS`).
      2. Directory next to the running executable (one-dir build / MSI install).
      3. Repo layout when running from source: `<repo>/<rel_path>`.
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / rel_path)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / rel_path)
        # MSI layout: scripts live next to the EXE without the "windows/" prefix.
        candidates.append(Path(sys.executable).parent / os.path.basename(rel_path))
    else:
        candidates.append(Path(__file__).resolve().parent.parent / rel_path)
    for c in candidates:
        if c.exists():
            return c
    return None


class App(tb.Window):
    def __init__(self) -> None:
        super().__init__(themename=LIGHT_THEME, title="Azure Secret Monitor",
                         size=(1200, 820), minsize=(1000, 700))

        self.cfg = config_store.load_config()
        if not self.cfg.smtp_password:
            self.cfg.smtp_password = config_store.load_smtp_password()

        self.roles = RoleAssignments.from_serializable(config_store.load_roles())
        self.is_os_admin = config_store.is_windows_admin()
        if perms.bootstrap_if_empty(self.roles, is_os_admin=self.is_os_admin):
            try:
                config_store.save_roles(self.roles.to_serializable())
            except PermissionError as exc:
                LOG.warning("Could not persist bootstrap role: %s", exc)
        self.current_user = perms.current_username()
        self.current_role: Role = self.roles.role_for(self.current_user)

        self.items: list[ExpiringItem] = []
        self.event_queue: queue.Queue = queue.Queue()
        self._scan_thread: threading.Thread | None = None
        self._sched_thread: threading.Thread | None = None
        self._sched_stop = threading.Event()
        self._page_frames: dict[str, tb.Frame] = {}
        self._nav_buttons: dict[str, tb.Button] = {}

        self._build_chrome()
        self._build_pages()
        self._show_page("dashboard")
        self._poll_events()

        if self.cfg.schedule_enabled:
            self._start_scheduler()

    # =====================================================================
    # Chrome: header, sidebar, status bar
    # =====================================================================

    def _build_chrome(self) -> None:
        # Header --------------------------------------------------------------
        header = tb.Frame(self, padding=(20, 14))
        header.pack(fill=X)

        title_box = tb.Frame(header)
        title_box.pack(side=LEFT)
        tb.Label(title_box, text="Azure Secret Monitor",
                 font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tb.Label(title_box, text="On-prem expiration tracking for Entra ID and Key Vault",
                 font=("Segoe UI", 10), bootstyle="secondary").pack(anchor="w")

        role_box = tb.Frame(header)
        role_box.pack(side=LEFT, padx=(28, 0))
        role_style = {"admin": "danger", "contributor": "warning",
                      "reader": "secondary"}[self.current_role.value]
        tb.Label(role_box, text=f"👤 {self.current_user}",
                 bootstyle="secondary").pack(anchor="w")
        tb.Label(role_box, text=f"  {self.current_role.label}  ",
                 bootstyle=f"inverse-{role_style}",
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(2, 0))

        actions = tb.Frame(header)
        actions.pack(side=RIGHT)
        self.theme_btn = tb.Button(actions, text="🌙 Dark", width=10,
                                   bootstyle="secondary-outline", command=self._toggle_theme)
        self.theme_btn.pack(side=RIGHT, padx=(8, 0))
        self.scan_btn = tb.Button(actions, text="▶  Scan now",
                                  bootstyle=PRIMARY, command=self.scan_now, width=14)
        self.scan_btn.pack(side=RIGHT)

        tb.Separator(self).pack(fill=X)

        # Body: sidebar + content --------------------------------------------
        body = tb.Frame(self)
        body.pack(fill=BOTH, expand=True)

        self.sidebar = tb.Frame(body, padding=(12, 16), width=210)
        self.sidebar.pack(side=LEFT, fill=Y)
        self.sidebar.pack_propagate(False)

        for key, label, icon in [
            ("dashboard",     "Dashboard",     "📊"),
            ("azure",         "Azure",         "☁"),
            ("notifications", "Notifications", "🔔"),
            ("scheduler",     "Scheduler",     "⏱"),
            ("permissions",   "Permissions",   "🛡"),
        ]:
            btn = tb.Button(self.sidebar, text=f"  {icon}   {label}",
                            bootstyle="secondary-link", width=20,
                            command=lambda k=key: self._show_page(k))
            btn.pack(fill=X, pady=2)
            self._nav_buttons[key] = btn

        tb.Separator(body, orient="vertical").pack(side=LEFT, fill=Y)

        self.content = tb.Frame(body, padding=20)
        self.content.pack(side=LEFT, fill=BOTH, expand=True)

        # Status bar ---------------------------------------------------------
        tb.Separator(self).pack(fill=X)
        bar = tb.Frame(self, padding=(20, 8))
        bar.pack(fill=X)
        self.status_var = tk.StringVar(value="● Idle.")
        tb.Label(bar, textvariable=self.status_var,
                 bootstyle="secondary").pack(side=LEFT)
        self.cfg_path_var = tk.StringVar(value=f"Config: {config_store.config_dir()}")
        tb.Label(bar, textvariable=self.cfg_path_var,
                 bootstyle="secondary").pack(side=RIGHT)

    def _show_page(self, key: str) -> None:
        for k, frame in self._page_frames.items():
            frame.pack_forget()
        self._page_frames[key].pack(fill=BOTH, expand=True)
        for k, btn in self._nav_buttons.items():
            btn.configure(bootstyle=("primary" if k == key else "secondary-link"))

    def _toggle_theme(self) -> None:
        current = self.style.theme.name
        new = DARK_THEME if current == LIGHT_THEME else LIGHT_THEME
        self.style.theme_use(new)
        self.theme_btn.configure(text="☀ Light" if new == DARK_THEME else "🌙 Dark")

    # =====================================================================
    # Pages
    # =====================================================================

    def _build_pages(self) -> None:
        self._page_frames["dashboard"]     = self._build_dashboard()
        self._page_frames["azure"]         = self._build_azure_page()
        self._page_frames["notifications"] = self._build_notifications_page()
        self._page_frames["scheduler"]     = self._build_scheduler_page()
        self._page_frames["permissions"]   = self._build_permissions_page()

    # ---------- Dashboard ------------------------------------------------

    def _build_dashboard(self) -> tb.Frame:
        f = tb.Frame(self.content)

        # Stat cards
        cards = tb.Frame(f)
        cards.pack(fill=X, pady=(0, 16))
        self.stat_vars = {
            "EXPIRED":  tk.StringVar(value="0"),
            "CRITICAL": tk.StringVar(value="0"),
            "WARNING":  tk.StringVar(value="0"),
            "OK":       tk.StringVar(value="0"),
        }
        for i, (key, label, style) in enumerate([
            ("EXPIRED",  "Expired",  DANGER),
            ("CRITICAL", "Critical (≤7d)", WARNING),
            ("WARNING",  "Warning (≤30d)", WARNING),
            ("OK",       "Healthy",  SUCCESS),
        ]):
            card = tb.Labelframe(cards, text=f"  {label}  ",
                                 bootstyle=style, padding=(16, 10))
            card.grid(row=0, column=i, padx=(0 if i == 0 else 12, 0), sticky="we")
            cards.columnconfigure(i, weight=1)
            tb.Label(card, textvariable=self.stat_vars[key],
                     font=("Segoe UI Semibold", 26)).pack(anchor="w")

        # Toolbar
        bar = tb.Frame(f)
        bar.pack(fill=X, pady=(0, 8))
        tb.Button(bar, text="🔄  Rescan", bootstyle="primary-outline",
                  command=self.scan_now).pack(side=LEFT)
        tb.Button(bar, text="⬇  Export…", bootstyle="secondary-outline",
                  command=self.export_results).pack(side=LEFT, padx=8)
        tb.Button(bar, text="✉  Test email", bootstyle="secondary-outline",
                  command=self.test_email).pack(side=LEFT)
        tb.Button(bar, text="💬  Test Teams", bootstyle="secondary-outline",
                  command=self.test_teams).pack(side=LEFT, padx=8)

        tb.Label(bar, text="Filter:", bootstyle="secondary").pack(side=LEFT, padx=(24, 6))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._apply_filter())
        tb.Entry(bar, textvariable=self.filter_var, width=28).pack(side=LEFT)

        self.last_scan_var = tk.StringVar(value="No scan yet")
        tb.Label(bar, textvariable=self.last_scan_var,
                 bootstyle="secondary").pack(side=RIGHT)

        # Treeview
        wrap = tb.Frame(f)
        wrap.pack(fill=BOTH, expand=True)

        cols = ("status", "days", "source", "kind", "container", "name", "expires")
        self.tree = tb.Treeview(wrap, columns=cols, show="headings",
                                bootstyle=INFO, height=18)
        headings = [("status", "Status", 90), ("days", "Days", 70),
                    ("source", "Source", 140), ("kind", "Kind", 110),
                    ("container", "Container", 240), ("name", "Name", 240),
                    ("expires", "Expires (UTC)", 150)]
        for col, text, w in headings:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="w")
        for status, color in ROW_COLORS.items():
            self.tree.tag_configure(status, background=color)
        vsb = tb.Scrollbar(wrap, orient="vertical", command=self.tree.yview,
                           bootstyle="secondary-round")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)

        self.row_menu = tk.Menu(self.tree, tearoff=0)
        self.row_menu.add_command(label="Renew / extend…", command=self._renew_selected)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self.tree.bind("<Double-1>", lambda e: self._renew_selected())

        return f

    # ---------- Azure ----------------------------------------------------

    def _build_azure_page(self) -> tb.Frame:
        f = tb.Frame(self.content)

        tb.Label(f, text="Azure connection",
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")
        tb.Label(f, text="Service principal credentials used to call Microsoft Graph and Key Vault.",
                 bootstyle="secondary").pack(anchor="w", pady=(0, 14))

        card = tb.Labelframe(f, text="  Service principal  ",
                             bootstyle="primary", padding=18)
        card.pack(fill=X, pady=(0, 16))

        self.tenant_var = tk.StringVar(value=self.cfg.tenant_id)
        self.client_id_var = tk.StringVar(value=self.cfg.client_id)
        self.client_secret_var = tk.StringVar(value=self.cfg.client_secret)
        self.threshold_var = tk.IntVar(value=self.cfg.threshold_days)
        self.app_reg_var = tk.BooleanVar(value=self.cfg.scan_app_registrations)
        self.include_ok_var = tk.BooleanVar(value=self.cfg.include_ok)

        self._labeled(card, 0, "Tenant ID", self.tenant_var)
        self._labeled(card, 1, "Client ID", self.client_id_var)
        self._labeled(card, 2, "Client secret", self.client_secret_var, show="●")
        card.columnconfigure(1, weight=1)

        scope = tb.Labelframe(f, text="  Scan scope  ",
                              bootstyle="info", padding=18)
        scope.pack(fill=BOTH, expand=True)

        self._labeled(scope, 0, "Threshold (days)", self.threshold_var, width=10)
        tb.Checkbutton(scope, text="Scan Entra ID app registrations",
                       variable=self.app_reg_var,
                       bootstyle="success-round-toggle").grid(
                           row=1, column=1, sticky="w", pady=8)
        tb.Checkbutton(scope, text="Show healthy items (OK) on dashboard",
                       variable=self.include_ok_var,
                       bootstyle="success-round-toggle").grid(
                           row=2, column=1, sticky="w", pady=4)

        tb.Label(scope, text="Key Vaults (one per line):").grid(
            row=3, column=0, sticky="nw", padx=(0, 12), pady=(12, 4))
        self.vaults_text = tk.Text(scope, height=8, font=("Consolas", 10),
                                   relief="solid", borderwidth=1)
        self.vaults_text.grid(row=3, column=1, sticky="we", pady=(12, 4))
        self.vaults_text.insert("1.0", "\n".join(self.cfg.key_vaults))
        scope.columnconfigure(1, weight=1)

        bar = tb.Frame(f)
        bar.pack(fill=X, pady=(16, 0))
        tb.Button(bar, text="🔌  Test connection", bootstyle="info-outline",
                  command=self.test_connection).pack(side=LEFT)
        tb.Button(bar, text="💾  Save settings", bootstyle=SUCCESS,
                  command=self.save_settings).pack(side=RIGHT)
        return f

    # ---------- Notifications -------------------------------------------

    def _build_notifications_page(self) -> tb.Frame:
        f = tb.Frame(self.content)
        tb.Label(f, text="Notifications",
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")
        tb.Label(f, text="Alerts fire only when severity rises (e.g. WARNING → CRITICAL).",
                 bootstyle="secondary").pack(anchor="w", pady=(0, 14))

        self.teams_var = tk.StringVar(value=self.cfg.teams_webhook)
        self.smtp_host_var = tk.StringVar(value=self.cfg.smtp_host)
        self.smtp_port_var = tk.IntVar(value=self.cfg.smtp_port)
        self.smtp_starttls_var = tk.BooleanVar(value=self.cfg.smtp_starttls)
        self.smtp_user_var = tk.StringVar(value=self.cfg.smtp_username)
        self.smtp_pwd_var = tk.StringVar(value=self.cfg.smtp_password)
        self.email_from_var = tk.StringVar(value=self.cfg.email_from)
        self.email_to_var = tk.StringVar(value=self.cfg.email_to)
        self.email_subject_var = tk.StringVar(value=self.cfg.email_subject)

        teams = tb.Labelframe(f, text="  Microsoft Teams  ",
                              bootstyle="primary", padding=18)
        teams.pack(fill=X, pady=(0, 14))
        self._labeled(teams, 0, "Incoming webhook URL", self.teams_var)
        teams.columnconfigure(1, weight=1)

        email = tb.Labelframe(f, text="  SMTP email  ",
                              bootstyle="primary", padding=18)
        email.pack(fill=X)
        self._labeled(email, 0, "SMTP host",  self.smtp_host_var)
        self._labeled(email, 1, "SMTP port",  self.smtp_port_var, width=10)
        tb.Checkbutton(email, text="Use STARTTLS", variable=self.smtp_starttls_var,
                       bootstyle="success-round-toggle").grid(
                           row=2, column=1, sticky="w", pady=4)
        self._labeled(email, 3, "Username",   self.smtp_user_var)
        self._labeled(email, 4, "Password",   self.smtp_pwd_var, show="●")
        self._labeled(email, 5, "From",       self.email_from_var)
        self._labeled(email, 6, "To (comma-separated)", self.email_to_var)
        self._labeled(email, 7, "Subject",    self.email_subject_var)
        email.columnconfigure(1, weight=1)

        tb.Button(f, text="💾  Save settings", bootstyle=SUCCESS,
                  command=self.save_settings).pack(anchor="e", pady=(16, 0))
        return f

    # ---------- Scheduler -----------------------------------------------

    def _build_scheduler_page(self) -> tb.Frame:
        f = tb.Frame(self.content)
        tb.Label(f, text="Scheduler",
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")
        tb.Label(f, text="Run scans on an interval, or install a Windows Scheduled Task for unattended runs.",
                 bootstyle="secondary").pack(anchor="w", pady=(0, 14))

        self.sched_on_var = tk.BooleanVar(value=self.cfg.schedule_enabled)
        self.sched_hours_var = tk.IntVar(value=self.cfg.schedule_interval_hours)

        inapp = tb.Labelframe(f, text="  In-app background scan  ",
                              bootstyle="info", padding=18)
        inapp.pack(fill=X, pady=(0, 14))
        tb.Checkbutton(inapp, text="Run scans while this app window stays open",
                       variable=self.sched_on_var,
                       bootstyle="success-round-toggle").grid(
                           row=0, column=0, columnspan=2, sticky="w")
        self._labeled(inapp, 1, "Interval (hours)", self.sched_hours_var, width=10)

        task = tb.Labelframe(f, text="  Windows Scheduled Task  ",
                             bootstyle="primary", padding=18)
        task.pack(fill=X)
        tb.Label(task, wraplength=720, justify="left", text=(
            "Registers a daily task named 'AzureSecretMonitor' that runs cli.py under "
            "the current Windows user (required so DPAPI can decrypt the stored client "
            "secret). Logs go to %ProgramData%\\AzureSecretMonitor\\logs\\cli.log."
        )).pack(anchor="w", pady=(0, 10))
        tb.Button(task, text="📅  Install Scheduled Task…", bootstyle=PRIMARY,
                  command=self.install_scheduled_task).pack(anchor="w")

        tb.Button(f, text="💾  Save settings", bootstyle=SUCCESS,
                  command=self.save_settings).pack(anchor="e", pady=(16, 0))
        return f

    # ---------- Permissions ---------------------------------------------

    def _build_permissions_page(self) -> tb.Frame:
        f = tb.Frame(self.content)
        tb.Label(f, text="Permissions",
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")
        tb.Label(f, text=("Three-tier role model. Reader → Contributor → Admin. "
                          "Roles are enforced in the UI; Azure-side limits come "
                          "from the service principal's API permissions."),
                 bootstyle="secondary", wraplength=860,
                 justify="left").pack(anchor="w", pady=(0, 14))

        top = tb.Frame(f)
        top.pack(fill=BOTH, expand=True)

        # Left: role tree (roles → granted capabilities)
        left = tb.Labelframe(top, text="  Role tree  ",
                             bootstyle="primary", padding=12)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))

        self.role_tree = tb.Treeview(left, show="tree", bootstyle=INFO,
                                     height=14)
        self.role_tree.pack(fill=BOTH, expand=True)
        for role in Role:
            node = self.role_tree.insert(
                "", END, text=f"  {role.label}", open=True,
                values=(role.value,))
            for p in sorted(perms.effective_permissions(role), key=lambda x: x.label):
                # mark inherited permissions with ↳
                inherited = p not in perms.ROLE_PERMISSIONS[role]
                prefix = "    ↳ " if inherited else "    ✓ "
                self.role_tree.insert(node, END, text=prefix + p.label)

        # Right: user assignments
        right = tb.Labelframe(top, text="  User assignments  ",
                              bootstyle="info", padding=12)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=(8, 0))

        cols = ("user", "role")
        self.user_tree = tb.Treeview(right, columns=cols, show="headings",
                                     bootstyle=INFO, height=11)
        self.user_tree.heading("user", text="Windows user")
        self.user_tree.heading("role", text="Role")
        self.user_tree.column("user", width=200)
        self.user_tree.column("role", width=120)
        self.user_tree.pack(fill=BOTH, expand=True)

        btn_bar = tb.Frame(right)
        btn_bar.pack(fill=X, pady=(8, 0))
        self.add_user_btn = tb.Button(btn_bar, text="+ Assign user…",
                                      bootstyle="primary",
                                      command=self._dlg_assign_user)
        self.add_user_btn.pack(side=LEFT)
        self.remove_user_btn = tb.Button(btn_bar, text="Remove",
                                         bootstyle="danger-outline",
                                         command=self._remove_selected_user)
        self.remove_user_btn.pack(side=LEFT, padx=8)

        self._refresh_user_tree()

        # Bottom: capability matrix
        matrix = tb.Labelframe(f, text="  Capability matrix  ",
                               bootstyle="secondary", padding=12)
        matrix.pack(fill=X, pady=(12, 0))

        cols = ("cap", "reader", "contributor", "admin")
        m = tb.Treeview(matrix, columns=cols, show="headings", height=9,
                        bootstyle="secondary")
        m.heading("cap", text="Capability")
        m.heading("reader", text="Reader")
        m.heading("contributor", text="Contributor")
        m.heading("admin", text="Admin")
        m.column("cap", width=320, anchor="w")
        for c in ("reader", "contributor", "admin"):
            m.column(c, width=110, anchor="center")
        for perm, granted in perms.capability_matrix():
            row = (perm.label,
                   "✓" if granted[Role.READER] else "",
                   "✓" if granted[Role.CONTRIBUTOR] else "",
                   "✓" if granted[Role.ADMIN] else "")
            m.insert("", END, values=row)
        m.pack(fill=X)

        # Hide management buttons if non-admin
        if not perms.can(self.current_role, Permission.MANAGE_ROLES):
            self.add_user_btn.configure(state="disabled")
            self.remove_user_btn.configure(state="disabled")

        return f

    def _refresh_user_tree(self) -> None:
        self.user_tree.delete(*self.user_tree.get_children())
        items = sorted(self.roles.mapping.items(),
                       key=lambda kv: (kv[1].rank, kv[0]))
        for user, role in items:
            self.user_tree.insert("", END, values=(
                user if user != "*" else "<default>", role.label))

    def _dlg_assign_user(self) -> None:
        if not perms.can(self.current_role, Permission.MANAGE_ROLES):
            return
        if not self.is_os_admin:
            messagebox.showinfo(
                "Administrator required",
                "Changing role assignments writes to a protected file in "
                "%ProgramData%. Re-launch the GUI as a Windows Administrator "
                "to make this change.")
            return
        dlg = tb.Toplevel(self)
        dlg.title("Assign role")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("400x220")

        tb.Label(dlg, text="Windows username (or '*' for default):",
                 padding=(12, 10, 12, 0)).pack(anchor="w")
        user_var = tk.StringVar()
        tb.Entry(dlg, textvariable=user_var, width=40).pack(
            padx=12, pady=(0, 10), fill=X)

        tb.Label(dlg, text="Role:", padding=(12, 0)).pack(anchor="w")
        role_var = tk.StringVar(value=Role.READER.label)
        tb.Combobox(dlg, textvariable=role_var, state="readonly",
                    values=[r.label for r in Role]).pack(
                        padx=12, pady=(0, 14), fill=X)

        def commit():
            u = user_var.get().strip()
            if not u:
                return
            picked = next(r for r in Role if r.label == role_var.get())
            self.roles.set(u, picked)
            try:
                config_store.save_roles(self.roles.to_serializable())
            except PermissionError as exc:
                messagebox.showerror("Permission denied", str(exc))
                return
            audit_event(str(config_store.audit_log_path()),
                        actor=self.current_user, role=self.current_role.value,
                        action="assign_role", target=f"user:{u}",
                        success=True, detail=f"role={picked.value}")
            self._refresh_user_tree()
            dlg.destroy()
            # Refresh own role if we changed our own assignment.
            self.current_role = self.roles.role_for(self.current_user)

        bar = tb.Frame(dlg)
        bar.pack(fill=X, padx=12, pady=(0, 12))
        tb.Button(bar, text="Cancel", bootstyle="secondary-outline",
                  command=dlg.destroy).pack(side=RIGHT)
        tb.Button(bar, text="Assign", bootstyle="primary",
                  command=commit).pack(side=RIGHT, padx=(0, 8))

    def _remove_selected_user(self) -> None:
        if not perms.can(self.current_role, Permission.MANAGE_ROLES):
            return
        sel = self.user_tree.selection()
        if not sel:
            return
        user = self.user_tree.item(sel[0], "values")[0]
        if user == "<default>":
            messagebox.showinfo("Default", "The default (*) row cannot be removed.")
            return
        if user.lower() == self.current_user.lower():
            if not messagebox.askyesno(
                "Remove yourself?",
                "You are removing your own assignment. You'll fall back to "
                "the default role. Continue?"):
                return
        self.roles.remove(user)
        try:
            config_store.save_roles(self.roles.to_serializable())
        except PermissionError as exc:
            messagebox.showerror("Permission denied", str(exc))
            return
        audit_event(str(config_store.audit_log_path()),
                    actor=self.current_user, role=self.current_role.value,
                    action="remove_role", target=f"user:{user}", success=True)
        self._refresh_user_tree()
        self.current_role = self.roles.role_for(self.current_user)

    # ---------- Renew / extend dialog -----------------------------------

    def _on_tree_right_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        if perms.can(self.current_role, Permission.RENEW_CREDENTIAL):
            self.row_menu.tk_popup(event.x_root, event.y_root)

    def _selected_item(self) -> ExpiringItem | None:
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        if idx >= len(self.items):
            return None
        # The tree may be filtered; find item by displayed values instead.
        values = self.tree.item(sel[0], "values")
        target_name = values[5]
        target_container = values[4]
        for it in self.items:
            if it.name == target_name and it.container == target_container:
                return it
        return None

    def _renew_selected(self) -> None:
        if not perms.can(self.current_role, Permission.RENEW_CREDENTIAL):
            messagebox.showinfo(
                "Permission required",
                "Your role does not allow renewing credentials. "
                "Ask an Admin to promote you to Contributor or higher.")
            return
        item = self._selected_item()
        if not item:
            return
        self._open_renew_dialog(item)

    def _open_renew_dialog(self, item: ExpiringItem) -> None:
        dlg = tb.Toplevel(self)
        dlg.title("Renew / extend credential")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("520x360")

        tb.Label(dlg, text=f"{item.source}  /  {item.kind}",
                 bootstyle="secondary").pack(anchor="w", padx=14, pady=(14, 0))
        tb.Label(dlg, text=item.name,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=14)
        tb.Label(dlg, text=f"In: {item.container}",
                 bootstyle="secondary").pack(anchor="w", padx=14, pady=(0, 12))

        # Body varies slightly by source
        body = tb.Frame(dlg, padding=14)
        body.pack(fill=BOTH, expand=True)

        from datetime import timedelta
        default_days = 365
        default_expiry = item.expires_on.replace(tzinfo=None) + timedelta(days=default_days)
        new_date_var = tk.StringVar(value=default_expiry.strftime("%Y-%m-%d"))
        tb.Label(body, text="New expiry date (YYYY-MM-DD):").grid(
            row=0, column=0, sticky="w", pady=4)
        tb.Entry(body, textvariable=new_date_var, width=22).grid(
            row=0, column=1, sticky="w", pady=4)

        display_name_var = tk.StringVar(
            value=f"renewed-{datetime.utcnow().strftime('%Y%m%d')}")
        if item.source == "AppRegistration" and item.kind == "ClientSecret":
            tb.Label(body, text="New secret display name:").grid(
                row=1, column=0, sticky="w", pady=4)
            tb.Entry(body, textvariable=display_name_var, width=30).grid(
                row=1, column=1, sticky="w", pady=4)
            tb.Label(body, wraplength=460, justify="left", bootstyle="warning",
                     text=("This will create a *new* client secret on the app "
                           "registration. The old secret is NOT removed — "
                           "rotate the consumer first, then delete the old "
                           "secret manually in the portal.")).grid(
                               row=2, column=0, columnspan=2, sticky="we", pady=(10, 0))
        else:
            tb.Label(body, wraplength=460, justify="left", bootstyle="info",
                     text=("This updates the `expires_on` metadata only. The "
                           "underlying secret material is unchanged. If the "
                           "value itself is compromised, also rotate it.")).grid(
                               row=2, column=0, columnspan=2, sticky="we", pady=(10, 0))

        result_box = tb.Frame(dlg)
        result_box.pack(fill=X, padx=14)

        bar = tb.Frame(dlg, padding=(14, 0, 14, 14))
        bar.pack(fill=X)

        def commit():
            from datetime import datetime as _dt, timezone as _tz
            try:
                new_dt = _dt.strptime(new_date_var.get().strip(), "%Y-%m-%d")
                new_dt = new_dt.replace(tzinfo=_tz.utc)
            except ValueError:
                messagebox.showerror("Bad date", "Use YYYY-MM-DD format.")
                return
            try:
                cred = make_credential(self.cfg)
                detail = ""
                if item.source == "AppRegistration":
                    if item.kind != "ClientSecret":
                        messagebox.showinfo("Not supported",
                            "Only client secrets can be renewed from here.")
                        return
                    obj_id = find_app_object_id(cred, app_id=item.identifier)
                    res = add_app_password(cred,
                        app_object_id=obj_id,
                        display_name=display_name_var.get().strip() or "renewed",
                        end_date=new_dt)
                    new_secret = res.get("secretText") or ""
                    detail = f"new keyId={res.get('keyId')}"
                    self._show_secret_once(dlg, new_secret)
                elif item.source == "KeyVault":
                    if item.kind == "Secret":
                        renew_keyvault_secret_expiry(cred,
                            vault_name=item.container, secret_name=item.name,
                            new_expires_on=new_dt)
                    elif item.kind == "Key":
                        renew_keyvault_key_expiry(cred,
                            vault_name=item.container, key_name=item.name,
                            new_expires_on=new_dt)
                    elif item.kind == "Certificate":
                        renew_keyvault_certificate_expiry(cred,
                            vault_name=item.container, cert_name=item.name,
                            new_expires_on=new_dt)
                    detail = f"new_expires_on={new_dt.isoformat()}"
                    messagebox.showinfo("Updated",
                        f"Expiry updated to {new_date_var.get()}.")
                audit_event(str(config_store.audit_log_path()),
                            actor=self.current_user, role=self.current_role.value,
                            action=f"renew_{item.source}_{item.kind}".lower(),
                            target=f"{item.container}/{item.name}",
                            success=True, detail=detail)
                if item.source != "AppRegistration":
                    dlg.destroy()
                    self.scan_now()
            except Exception as exc:
                audit_event(str(config_store.audit_log_path()),
                            actor=self.current_user, role=self.current_role.value,
                            action=f"renew_{item.source}_{item.kind}".lower(),
                            target=f"{item.container}/{item.name}",
                            success=False, detail=str(exc))
                messagebox.showerror("Renew failed", str(exc))

        tb.Button(bar, text="Cancel", bootstyle="secondary-outline",
                  command=dlg.destroy).pack(side=RIGHT)
        tb.Button(bar, text="🔁  Renew", bootstyle="success",
                  command=commit).pack(side=RIGHT, padx=(0, 8))

    def _show_secret_once(self, parent, secret: str) -> None:
        dlg = tb.Toplevel(parent)
        dlg.title("New client secret — copy now")
        dlg.transient(parent)
        dlg.grab_set()
        dlg.geometry("580x260")
        tb.Label(dlg, bootstyle="warning",
                 text=("⚠  This is the only time you will see this value. "
                       "Copy it into the consuming system, then close.")
                 ).pack(anchor="w", padx=14, pady=(14, 8))
        txt = tk.Text(dlg, height=4, font=("Consolas", 10), wrap="char")
        txt.insert("1.0", secret)
        txt.configure(state="disabled")
        txt.pack(fill=X, padx=14)

        clip_state = {"countdown": 0, "job": None}
        countdown_var = tk.StringVar(value="")

        def clear_clipboard():
            try:
                if self.clipboard_get() == secret:
                    self.clipboard_clear()
            except tk.TclError:
                pass
            countdown_var.set("Clipboard cleared.")
            clip_state["countdown"] = 0

        def tick():
            if clip_state["countdown"] <= 0:
                clear_clipboard()
                return
            countdown_var.set(f"Clipboard auto-clears in {clip_state['countdown']}s")
            clip_state["countdown"] -= 1
            clip_state["job"] = self.after(1000, tick)

        def copy():
            self.clipboard_clear()
            self.clipboard_append(secret)
            if clip_state["job"]:
                self.after_cancel(clip_state["job"])
            clip_state["countdown"] = 30
            tick()

        tb.Label(dlg, textvariable=countdown_var,
                 bootstyle="secondary").pack(anchor="w", padx=14, pady=(8, 0))

        def on_close():
            if clip_state["job"]:
                self.after_cancel(clip_state["job"])
            clear_clipboard()
            dlg.destroy()
        dlg.protocol("WM_DELETE_WINDOW", on_close)

        bar = tb.Frame(dlg, padding=(14, 12, 14, 14))
        bar.pack(fill=X)
        tb.Button(bar, text="Close", bootstyle="secondary",
                  command=on_close).pack(side=RIGHT)
        tb.Button(bar, text="Copy to clipboard", bootstyle="primary",
                  command=copy).pack(side=RIGHT, padx=(0, 8))

    # =====================================================================
    # Helpers
    # =====================================================================

    def _labeled(self, parent, row, label, var, width=46, show=None) -> tb.Entry:
        tb.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                          padx=(0, 12), pady=6)
        entry = tb.Entry(parent, textvariable=var, width=width, show=show)
        entry.grid(row=row, column=1, sticky="we", pady=6)
        return entry

    # =====================================================================
    # Actions (unchanged behavior from the prior build)
    # =====================================================================

    def _gather_settings(self) -> AppConfig:
        vaults = [v.strip() for v in self.vaults_text.get("1.0", "end").splitlines() if v.strip()]
        self.cfg.tenant_id = self.tenant_var.get().strip()
        self.cfg.client_id = self.client_id_var.get().strip()
        self.cfg.client_secret = self.client_secret_var.get()
        self.cfg.threshold_days = int(self.threshold_var.get() or 30)
        self.cfg.scan_app_registrations = bool(self.app_reg_var.get())
        self.cfg.include_ok = bool(self.include_ok_var.get())
        self.cfg.key_vaults = vaults

        self.cfg.teams_webhook = self.teams_var.get().strip()
        self.cfg.smtp_host = self.smtp_host_var.get().strip()
        self.cfg.smtp_port = int(self.smtp_port_var.get() or 587)
        self.cfg.smtp_starttls = bool(self.smtp_starttls_var.get())
        self.cfg.smtp_username = self.smtp_user_var.get().strip()
        self.cfg.smtp_password = self.smtp_pwd_var.get()
        self.cfg.email_from = self.email_from_var.get().strip()
        self.cfg.email_to = self.email_to_var.get().strip()
        self.cfg.email_subject = (self.email_subject_var.get().strip()
                                  or "[Azure] Secret expiration report")

        self.cfg.schedule_enabled = bool(self.sched_on_var.get())
        self.cfg.schedule_interval_hours = max(1, int(self.sched_hours_var.get() or 24))
        return self.cfg

    def save_settings(self) -> None:
        # Settings span three permission domains; require at least Contributor
        # to save scan-scope / notifications, and Admin to overwrite the
        # Azure connection. Block early if the user has none of these.
        allowed = any(perms.can(self.current_role, p) for p in (
            Permission.EDIT_AZURE_CONN, Permission.EDIT_NOTIFICATIONS,
            Permission.EDIT_SCAN_SCOPE))
        if not allowed:
            messagebox.showinfo(
                "Read-only",
                "Your role can view settings but cannot save them. "
                "Ask an Admin to promote you.")
            return
        self._gather_settings()
        try:
            config_store.save_config(self.cfg)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._restart_scheduler()
        audit_event(str(config_store.audit_log_path()),
                    actor=self.current_user, role=self.current_role.value,
                    action="save_settings", target="config.json", success=True)
        self.status_var.set(f"● Settings saved to {config_store.config_dir()}")

    def scan_now(self) -> None:
        if self._scan_thread and self._scan_thread.is_alive():
            return
        cfg = self._gather_settings()
        errors = cfg.validate_for_scan()
        if errors:
            messagebox.showerror("Configuration incomplete", "\n".join(errors))
            return
        self.status_var.set("● Scanning…")
        self._scan_thread = threading.Thread(
            target=self._do_scan, args=(cfg, True), daemon=True)
        self._scan_thread.start()

    def _do_scan(self, cfg: AppConfig, send_notifications: bool) -> None:
        try:
            raw = scan_all(cfg, progress=lambda m: self.event_queue.put(("status", m)))
            filtered = filter_items(raw, cfg.threshold_days, cfg.include_ok)
            self.event_queue.put(("items", filtered))

            if send_notifications:
                state = config_store.load_state()
                to_alert = items_needing_alert(filtered, state)
                if to_alert:
                    if cfg.teams_webhook:
                        try:
                            notify_teams(cfg.teams_webhook, to_alert)
                        except Exception as exc:
                            self.event_queue.put(("status", f"Teams failed: {exc}"))
                    if cfg.smtp_host and cfg.email_from and cfg.email_recipients():
                        try:
                            notify_email(cfg, to_alert)
                        except Exception as exc:
                            self.event_queue.put(("status", f"Email failed: {exc}"))
                config_store.save_state(state)
            self.event_queue.put(("status",
                f"● Scan complete at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
        except Exception as exc:
            LOG.exception("Scan failed")
            self.event_queue.put(("status", f"● Scan failed: {exc}"))

    def test_connection(self) -> None:
        cfg = self._gather_settings()
        errors = cfg.validate_for_scan()
        if errors:
            messagebox.showerror("Configuration incomplete", "\n".join(errors))
            return
        self.status_var.set("● Testing connection...")
        t = threading.Thread(target=self._do_test_connection,
                             args=(cfg,), daemon=True)
        t.start()

    def _do_test_connection(self, cfg: AppConfig) -> None:
        try:
            result = test_connection(cfg)
            self.event_queue.put(("conn_test", result))
            self.event_queue.put(("status",
                "● Connection test complete." if result.all_ok()
                else "● Connection test found issues."))
        except Exception as exc:
            LOG.exception("Test connection crashed")
            self.event_queue.put(("status", f"● Test failed: {exc}"))

    def _show_conn_test_result(self, result: ConnectionTestResult) -> None:
        dlg = tb.Toplevel(self)
        dlg.title("Connection test")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("640x460")

        tb.Label(dlg, text="Connection test results",
                 font=("Segoe UI Semibold", 14),
                 padding=(16, 14, 16, 0)).pack(anchor="w")

        body = tb.Frame(dlg, padding=16)
        body.pack(fill=BOTH, expand=True)

        def row(parent, label: str, ok: bool, detail: str, r: int):
            badge_style = "inverse-success" if ok else "inverse-danger"
            badge_text = "  PASS  " if ok else "  FAIL  "
            tb.Label(parent, text=label,
                     font=("Segoe UI Semibold", 10)).grid(
                         row=r, column=0, sticky="nw", padx=(0, 12), pady=4)
            tb.Label(parent, text=badge_text,
                     bootstyle=badge_style,
                     font=("Segoe UI Semibold", 9)).grid(
                         row=r, column=1, sticky="nw", pady=4)
            tb.Label(parent, text=detail, bootstyle="secondary",
                     wraplength=420, justify="left").grid(
                         row=r, column=2, sticky="w", padx=(12, 0), pady=4)

        row(body, "Token acquisition", result.auth_ok, result.auth_detail, 0)
        row(body, "Microsoft Graph",   result.graph_ok, result.graph_detail, 1)

        for idx, (vault, (ok, detail)) in enumerate(result.vault_results.items(), start=2):
            row(body, f"Key Vault: {vault}", ok, detail, idx)

        body.columnconfigure(2, weight=1)

        bar = tb.Frame(dlg, padding=(16, 0, 16, 16))
        bar.pack(fill=X)
        tb.Button(bar, text="Close", bootstyle="secondary",
                  command=dlg.destroy).pack(side=RIGHT)

    def export_results(self) -> None:
        from tkinter import filedialog
        import csv as csvmod
        import json as jsonmod

        if not self.items:
            messagebox.showinfo("Nothing to export",
                                "Run a scan first — the dashboard is empty.")
            return

        items = self._currently_visible_items()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        fname = filedialog.asksaveasfilename(
            parent=self,
            title="Export scan results",
            defaultextension=".csv",
            initialfile=f"azure-secrets-{ts}.csv",
            filetypes=[("CSV (Excel-friendly)", "*.csv"),
                       ("JSON (machine-readable)", "*.json")],
        )
        if not fname:
            return

        try:
            if fname.lower().endswith(".json"):
                data = [{
                    "source": i.source, "kind": i.kind, "name": i.name,
                    "container": i.container,
                    "expires_on": i.expires_on.isoformat(),
                    "days_remaining": i.days_remaining,
                    "status": i.status, "identifier": i.identifier,
                } for i in items]
                with open(fname, "w", encoding="utf-8") as f:
                    jsonmod.dump(data, f, indent=2)
            else:
                with open(fname, "w", encoding="utf-8", newline="") as f:
                    w = csvmod.writer(f)
                    w.writerow(["status", "days_remaining", "source", "kind",
                                "container", "name", "expires_on_utc",
                                "identifier"])
                    for i in items:
                        w.writerow([i.status, i.days_remaining, i.source, i.kind,
                                    i.container, i.name,
                                    i.expires_on.strftime("%Y-%m-%d %H:%M:%S"),
                                    i.identifier])
            messagebox.showinfo("Exported",
                f"Wrote {len(items)} row(s) to:\n{fname}")
            audit_event(str(config_store.audit_log_path()),
                        actor=self.current_user, role=self.current_role.value,
                        action="export", target=os.path.basename(fname),
                        success=True, detail=f"rows={len(items)}")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def _currently_visible_items(self) -> list[ExpiringItem]:
        """Respect the dashboard filter so 'Export' only writes what you see."""
        needle = (self.filter_var.get() if hasattr(self, "filter_var") else "").lower().strip()
        if not needle:
            return list(self.items)
        return [i for i in self.items
                if needle in " ".join([i.source, i.kind, i.container,
                                       i.name, i.status]).lower()]

    def test_teams(self) -> None:
        cfg = self._gather_settings()
        if not cfg.teams_webhook:
            messagebox.showinfo("No webhook", "Set the Teams webhook URL first.")
            return
        try:
            notify_teams(cfg.teams_webhook, [])
            messagebox.showinfo("Sent", "Test message posted to Teams.")
        except Exception as exc:
            messagebox.showerror("Teams failed", str(exc))

    def test_email(self) -> None:
        cfg = self._gather_settings()
        if not (cfg.smtp_host and cfg.email_from and cfg.email_recipients()):
            messagebox.showinfo("Email not configured",
                                "Fill SMTP host, From, and To first.")
            return
        try:
            notify_email(cfg, [])
            messagebox.showinfo("Sent", "Test email sent.")
        except Exception as exc:
            messagebox.showerror("Email failed", str(exc))

    def install_scheduled_task(self) -> None:
        if not perms.can(self.current_role, Permission.INSTALL_TASK):
            messagebox.showinfo(
                "Permission required",
                "Only Admins can install the Scheduled Task.")
            return
        import subprocess
        script = _resource_path("windows/Install-ScheduledTask.ps1")
        if not script or not script.exists():
            messagebox.showerror(
                "Missing",
                "Could not locate Install-ScheduledTask.ps1 near the running "
                "executable. If you built a custom package, ensure the script "
                "ships alongside the EXE.")
            return
        try:
            subprocess.Popen([
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script),
            ])
            messagebox.showinfo("Launched",
                "PowerShell installer launched. Approve the UAC prompt if asked.")
        except Exception as exc:
            messagebox.showerror("Failed to launch", str(exc))

    # ------------------------------------------------------------- scheduler

    def _start_scheduler(self) -> None:
        if self._sched_thread and self._sched_thread.is_alive():
            return
        self._sched_stop.clear()
        self._sched_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._sched_thread.start()

    def _stop_scheduler(self) -> None:
        self._sched_stop.set()

    def _restart_scheduler(self) -> None:
        self._stop_scheduler()
        if self.cfg.schedule_enabled:
            self._start_scheduler()

    def _scheduler_loop(self) -> None:
        interval = max(1, self.cfg.schedule_interval_hours) * 3600
        while not self._sched_stop.is_set():
            cfg = self.cfg
            if not cfg.validate_for_scan():
                self._do_scan(cfg, True)
            for _ in range(interval):
                if self._sched_stop.is_set():
                    return
                time.sleep(1)

    # --------------------------------------------------------------- pumping

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "status":
                    self.status_var.set("● " + payload if not payload.startswith("●") else payload)
                elif kind == "items":
                    self._render_items(payload)
                elif kind == "conn_test":
                    self._show_conn_test_result(payload)
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def _render_items(self, items: list[ExpiringItem]) -> None:
        self.items = items
        self._apply_filter()
        counts = {"EXPIRED": 0, "CRITICAL": 0, "WARNING": 0, "OK": 0}
        for i in items:
            counts[i.status] = counts.get(i.status, 0) + 1
        for k, v in counts.items():
            self.stat_vars[k].set(str(v))
        self.last_scan_var.set(f"Last scan: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def _apply_filter(self) -> None:
        needle = (self.filter_var.get() if hasattr(self, "filter_var") else "").lower().strip()
        self.tree.delete(*self.tree.get_children())
        for i in self.items:
            if needle:
                hay = " ".join([i.source, i.kind, i.container, i.name, i.status]).lower()
                if needle not in hay:
                    continue
            self.tree.insert("", END, values=(
                i.status, i.days_remaining, i.source, i.kind,
                i.container, i.name, i.expires_on.strftime("%Y-%m-%d %H:%M"),
            ), tags=(i.status,))


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    App().mainloop()


if __name__ == "__main__":
    main()
