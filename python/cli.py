"""Headless CLI for the secret monitor — used by the Windows Scheduled Task.

Reads the GUI's saved config (DPAPI-encrypted client secret on Windows) and
performs a single scan + notification round, then exits.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import config_store
from core import (
    filter_items, items_needing_alert, notify_email, notify_teams,
    render_console, scan_all,
)

LOG = logging.getLogger("azure-secret-monitor.cli")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Azure secret expiration monitor (headless run).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results but do not send notifications.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of a table.")
    parser.add_argument("--ignore-state", action="store_true",
                        help="Notify on every matching item, ignoring previous alert state.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = config_store.load_config()
    if not cfg.smtp_password:
        cfg.smtp_password = config_store.load_smtp_password()

    errors = cfg.validate_for_scan()
    if errors:
        print("Configuration incomplete:\n  - " + "\n  - ".join(errors), file=sys.stderr)
        print(f"Run gui.py to configure (config dir: {config_store.config_dir()}).",
              file=sys.stderr)
        sys.exit(3)

    raw = scan_all(cfg)
    items = filter_items(raw, cfg.threshold_days, cfg.include_ok)

    if args.json:
        print(json.dumps([{
            "source": i.source, "kind": i.kind, "name": i.name,
            "container": i.container, "expires_on": i.expires_on.isoformat(),
            "days_remaining": i.days_remaining, "status": i.status,
            "identifier": i.identifier,
        } for i in items], indent=2))
    else:
        print(render_console(items))

    if not args.dry_run:
        state = {} if args.ignore_state else config_store.load_state()
        to_alert = items_needing_alert(items, state)
        if to_alert:
            if cfg.teams_webhook:
                try:
                    notify_teams(cfg.teams_webhook, to_alert)
                except Exception as exc:
                    LOG.error("Teams notification failed: %s", exc)
            if cfg.smtp_host and cfg.email_from and cfg.email_recipients():
                try:
                    notify_email(cfg, to_alert)
                except Exception as exc:
                    LOG.error("Email notification failed: %s", exc)
        config_store.save_state(state)

    if any(i.status == "EXPIRED" for i in items):
        sys.exit(2)
    if items:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
