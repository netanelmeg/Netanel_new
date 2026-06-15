"""Entry point so the package can be run as ``python -m mdconvert``."""

from __future__ import annotations

from .cli import run

if __name__ == "__main__":
    raise SystemExit(run())
