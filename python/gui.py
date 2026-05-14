"""Azure Secret Expiration Monitor — Windows GUI.

Tkinter-based GUI built for Windows Server. Loads/saves config to
%APPDATA%\\AzureSecretMonitor and encrypts the client secret with DPAPI.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import config_store
from core import (
    AppConfig, ExpiringItem, filter_items, items_needing_alert,
    notify_email, notify_teams, scan_all,
)

LOG = logging.getLogger("azure-secret-monitor.gui")

STATUS_COLORS = {
    "EXPIRED":  "#ffb3b3",
    "CRITICAL": "#ffd6a5",
    "WARNING":  "#fff3b0",
    "OK":       "#d8f3dc",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Azure Secret Expiration Monitor")
        self.geometry("1050x650")
        self.minsize(900, 550)

        self.cfg = config_store.load_config()
        if not self.cfg.smtp_password:
            self.cfg.smtp_password = config_store.load_smtp_password()

        self.items: list[ExpiringItem] = []
        self.event_queue: queue.Queue = queue.Queue()
        self._scan_thread: threading.Thread | None = None
        self._sched_thread: threading.Thread | None = None
        self._sched_stop = threading.Event()

        self._build_ui()
        self._poll_events()

        if self.cfg.schedule_enabled:
            self._start_scheduler()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        self._build_dashboard(nb)
        self._build_azure_tab(nb)
        self._build_notifications_tab(nb)
        self._build_schedule_tab(nb)

        self.status_var = tk.StringVar(value="Idle.")
        ttk.Label(self, textvariable=self.status_var, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom", padx=8, pady=4)

    def _build_dashboard(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=8)
        nb.add(frame, text="Dashboard")

        bar = ttk.Frame(frame); bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Scan now", command=self.scan_now).pack(side="left")
        ttk.Button(bar, text="Send test Teams", command=self.test_teams).pack(side="left", padx=4)
        ttk.Button(bar, text="Send test email", command=self.test_email).pack(side="left", padx=4)

        self.summary_var = tk.StringVar(value="No scan yet.")
        ttk.Label(bar, textvariable=self.summary_var).pack(side="right")

        cols = ("status", "days", "source", "kind", "container", "name", "expires")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings")
        widths = {"status": 90, "days": 60, "source": 130, "kind": 110,
                  "container": 240, "name": 240, "expires": 150}
        for c in cols:
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=widths[c], anchor="w")
        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(status, background=color)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _build_azure_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="Azure")

        self.tenant_var = tk.StringVar(value=self.cfg.tenant_id)
        self.client_id_var = tk.StringVar(value=self.cfg.client_id)
        self.client_secret_var = tk.StringVar(value=self.cfg.client_secret)
        self.threshold_var = tk.IntVar(value=self.cfg.threshold_days)
        self.app_reg_var = tk.BooleanVar(value=self.cfg.scan_app_registrations)
        self.include_ok_var = tk.BooleanVar(value=self.cfg.include_ok)

        self._row(frame, 0, "Tenant ID", self.tenant_var)
        self._row(frame, 1, "Client ID", self.client_id_var)
        self._row(frame, 2, "Client secret", self.client_secret_var, show="*")
        self._row(frame, 3, "Threshold (days)", self.threshold_var, width=10)

        ttk.Checkbutton(frame, text="Scan Entra ID app registrations",
                        variable=self.app_reg_var).grid(row=4, column=1, sticky="w", pady=4)
        ttk.Checkbutton(frame, text="Include healthy items (OK) in dashboard",
                        variable=self.include_ok_var).grid(row=5, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Key Vaults (one per line):").grid(row=6, column=0, sticky="nw", pady=(8, 4))
        self.vaults_text = tk.Text(frame, width=60, height=8)
        self.vaults_text.grid(row=6, column=1, sticky="we", pady=(8, 4))
        self.vaults_text.insert("1.0", "\n".join(self.cfg.key_vaults))

        frame.columnconfigure(1, weight=1)
        ttk.Button(frame, text="Save", command=self.save_settings).grid(
            row=10, column=1, sticky="e", pady=(16, 0))

    def _build_notifications_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="Notifications")

        self.teams_var = tk.StringVar(value=self.cfg.teams_webhook)
        self.smtp_host_var = tk.StringVar(value=self.cfg.smtp_host)
        self.smtp_port_var = tk.IntVar(value=self.cfg.smtp_port)
        self.smtp_starttls_var = tk.BooleanVar(value=self.cfg.smtp_starttls)
        self.smtp_user_var = tk.StringVar(value=self.cfg.smtp_username)
        self.smtp_pwd_var = tk.StringVar(value=self.cfg.smtp_password)
        self.email_from_var = tk.StringVar(value=self.cfg.email_from)
        self.email_to_var = tk.StringVar(value=self.cfg.email_to)
        self.email_subject_var = tk.StringVar(value=self.cfg.email_subject)

        ttk.Label(frame, text="Microsoft Teams").grid(row=0, column=0, columnspan=2, sticky="w")
        self._row(frame, 1, "Webhook URL", self.teams_var)

        ttk.Separator(frame).grid(row=2, column=0, columnspan=2, sticky="we", pady=10)
        ttk.Label(frame, text="SMTP email").grid(row=3, column=0, columnspan=2, sticky="w")
        self._row(frame, 4, "SMTP host", self.smtp_host_var)
        self._row(frame, 5, "SMTP port", self.smtp_port_var, width=10)
        ttk.Checkbutton(frame, text="Use STARTTLS",
                        variable=self.smtp_starttls_var).grid(row=6, column=1, sticky="w", pady=4)
        self._row(frame, 7, "Username", self.smtp_user_var)
        self._row(frame, 8, "Password", self.smtp_pwd_var, show="*")
        self._row(frame, 9, "From",     self.email_from_var)
        self._row(frame, 10, "To (comma-separated)", self.email_to_var)
        self._row(frame, 11, "Subject", self.email_subject_var)

        frame.columnconfigure(1, weight=1)
        ttk.Button(frame, text="Save", command=self.save_settings).grid(
            row=12, column=1, sticky="e", pady=(16, 0))

    def _build_schedule_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="Scheduler")

        self.sched_on_var = tk.BooleanVar(value=self.cfg.schedule_enabled)
        self.sched_hours_var = tk.IntVar(value=self.cfg.schedule_interval_hours)

        ttk.Checkbutton(frame, text="Run scans in the background while this app is open",
                        variable=self.sched_on_var).grid(row=0, column=0, columnspan=2, sticky="w")
        self._row(frame, 1, "Interval (hours)", self.sched_hours_var, width=10)

        info = (
            "To run unattended on this server, click 'Install Scheduled Task' below.\n"
            "It registers a Windows task that runs cli.py daily under the current user."
        )
        ttk.Label(frame, text=info, foreground="#555").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(12, 4))
        ttk.Button(frame, text="Install Scheduled Task...",
                   command=self.install_scheduled_task).grid(row=3, column=0, sticky="w", pady=4)

        ttk.Button(frame, text="Save", command=self.save_settings).grid(
            row=10, column=1, sticky="e", pady=(16, 0))

    def _row(self, parent, row, label, var, width=50, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=var, width=width, show=show)
        entry.grid(row=row, column=1, sticky="we", pady=4)
        return entry

    # ---------------------------------------------------------------- actions

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
        self.cfg.email_subject = self.email_subject_var.get().strip() or "[Azure] Secret expiration report"

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
        self.status_var.set(f"Settings saved to {config_store.config_dir()}")

    def scan_now(self) -> None:
        if self._scan_thread and self._scan_thread.is_alive():
            return
        cfg = self._gather_settings()
        errors = cfg.validate_for_scan()
        if errors:
            messagebox.showerror("Configuration incomplete", "\n".join(errors))
            return
        self.status_var.set("Scanning...")
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
                f"Scan complete at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
        except Exception as exc:
            LOG.exception("Scan failed")
            self.event_queue.put(("status", f"Scan failed: {exc}"))

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
            # Sleep in small chunks so we can stop quickly on settings change.
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
                    self.status_var.set(payload)
                elif kind == "items":
                    self._render_items(payload)
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def _render_items(self, items: list[ExpiringItem]) -> None:
        self.items = items
        self.tree.delete(*self.tree.get_children())
        counts = {"EXPIRED": 0, "CRITICAL": 0, "WARNING": 0, "OK": 0}
        for i in items:
            counts[i.status] = counts.get(i.status, 0) + 1
            self.tree.insert("", "end", values=(
                i.status, i.days_remaining, i.source, i.kind,
                i.container, i.name, i.expires_on.strftime("%Y-%m-%d %H:%M"),
            ), tags=(i.status,))
        self.summary_var.set(
            f"Expired: {counts['EXPIRED']}   "
            f"Critical: {counts['CRITICAL']}   "
            f"Warning: {counts['WARNING']}   "
            f"OK: {counts['OK']}   "
            f"Total: {len(items)}"
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    App().mainloop()


if __name__ == "__main__":
    main()
