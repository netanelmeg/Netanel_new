#!/usr/bin/env python3
"""Gemma-tune superpowers skills for the Hermes agent.

Superpowers' skills are authored for Claude/GPT-class models. Two things hurt
smaller local models (e.g. Gemma 4 served via Ollama):

  1. Inline Graphviz (```dot ... ```) decision diagrams. Strong models parse
     these; small models emit them verbatim or get confused. The decision logic
     is also written in prose in every skill, so the diagram is redundant.
  2. Skills reference Claude Code tool names (Read/Edit/Bash/Skill/Task...).
     Hermes uses different names; the mapping lives in
     using-superpowers/references/hermes-tools.md.

This script rewrites Markdown skills in place:
  * Replaces each ```dot fenced block with a short prose pointer.
  * Adds a one-line banner pointing at the Hermes tool map (once per SKILL.md).

It is idempotent (safe to re-run) and only touches .md files. The
using-superpowers SKILL.md is hand-tuned separately and is skipped by default.

Usage:
    python3 gemma-tune.py <skills-dir> [--include-using-superpowers]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

DOT_BLOCK = re.compile(
    r"```[ \t]*dot\b.*?\n.*?\n```[ \t]*\n?",
    re.DOTALL,
)
DOT_REPLACEMENT = (
    "> _(A decision flowchart was here. It has been removed for smaller local "
    "models — follow the numbered steps and rules in this skill directly.)_\n"
)

BANNER = (
    "> **Hermes note:** This skill uses Claude Code tool names "
    "(`Read`, `Edit`, `Bash`, `Skill`, `Task`, ...). Map them to your Hermes "
    "tools via `using-superpowers/references/hermes-tools.md`.\n"
)
BANNER_MARK = "**Hermes note:**"


def strip_dot_blocks(text: str) -> tuple[str, int]:
    return DOT_BLOCK.subn(DOT_REPLACEMENT, text)


def add_banner(text: str) -> str:
    """Insert the Hermes banner right after the YAML frontmatter (if present)."""
    if BANNER_MARK in text:
        return text  # already added
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            head = text[: end + len("\n---\n")]
            rest = text[end + len("\n---\n") :]
            return f"{head}\n{BANNER}\n{rest}"
    return f"{BANNER}\n{text}"


def process(path: pathlib.Path) -> int:
    original = path.read_text(encoding="utf-8")
    text, n = strip_dot_blocks(original)
    if path.name == "SKILL.md":
        text = add_banner(text)
    if text != original:
        path.write_text(text, encoding="utf-8")
    return n


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("skills_dir", type=pathlib.Path)
    ap.add_argument(
        "--include-using-superpowers",
        action="store_true",
        help="also transform using-superpowers/SKILL.md (normally hand-tuned)",
    )
    args = ap.parse_args(argv)

    root = args.skills_dir
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1

    total_files = 0
    total_dot = 0
    for md in sorted(root.rglob("*.md")):
        if (
            not args.include_using_superpowers
            and md.parent.name == "using-superpowers"
            and md.name == "SKILL.md"
        ):
            continue
        removed = process(md)
        total_files += 1
        total_dot += removed
        if removed:
            print(f"  tuned {md.relative_to(root)} (-{removed} dot block(s))")

    print(f"Gemma-tune complete: {total_files} file(s), {total_dot} dot block(s) removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
