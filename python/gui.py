"""Azure Secret Expiration Monitor — modern Windows GUI (ttkbootstrap).

Sidebar navigation, stat cards, themed widgets, and a light/dark switch.
Logic is unchanged from the prior tkinter build — only the look-and-feel
and layout are new.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import (
    BOTH, DANGER, END, INFO, LEFT, PRIMARY, RIGHT, SUCCESS, WARNING, X, Y,
)

import config_store
from core import (
    AppConfig, ExpiringItem, filter_items, items_needing_alert,
    notify_email, notify_teams, scan_all,
)

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


class App(tb.Window):
    def __init__(self) -> None:
        super().__init__(themename=LIGHT_THEME, title="Azure Secret Monitor",
                         size=(1180, 740), minsize=(1000, 620))

        self.cfg = config_store.load_config()
        if not self.cfg.smtp_password:
            self.cfg.smtp_password = config_store.load_smtp_password()

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
        tb.Button(bar, text="✉  Test email", bootstyle="secondary-outline",
                  command=self.test_email).pack(side=LEFT, padx=8)
        tb.Button(bar, text="💬  Test Teams", bootstyle="secondary-outline",
                  command=self.test_teams).pack(side=LEFT)

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

        tb.Button(f, text="💾  Save settings", bootstyle=SUCCESS,
                  command=self.save_settings).pack(anchor="e", pady=(16, 0))
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
        self._gather_settings()
        try:
            config_store.save_config(self.cfg)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._restart_scheduler()
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
        from pathlib import Path
        import subprocess
        script = Path(__file__).parent.parent / "windows" / "Install-ScheduledTask.ps1"
        if not script.exists():
            messagebox.showerror("Missing", f"Could not find {script}")
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
