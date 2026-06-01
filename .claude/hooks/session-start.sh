#!/bin/bash
# Installs .claude/commands/ as global ~/.claude/skills/ on every session start.
# This ensures ruflo slash commands are available without depending on
# the marketplace network fetch.
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

COMMANDS_DIR="${CLAUDE_PROJECT_DIR}/.claude/commands"
SKILLS_DIR="${HOME}/.claude/skills"

if [ ! -d "$COMMANDS_DIR" ]; then
  exit 0
fi

for cmd_file in "$COMMANDS_DIR"/*.md; do
  [ -f "$cmd_file" ] || continue
  skill_name="$(basename "$cmd_file" .md)"
  skill_dir="$SKILLS_DIR/$skill_name"
  mkdir -p "$skill_dir"
  cp "$cmd_file" "$skill_dir/SKILL.md"
done

echo "Ruflo skills installed: $(ls "$COMMANDS_DIR"/*.md | wc -l | tr -d ' ') commands available"
