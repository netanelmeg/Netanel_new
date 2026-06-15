#!/usr/bin/env bash
#
# install-hermes.sh — install the Gemma-tuned Superpowers skills into Hermes.
#
# Copies the 14 Superpowers skills (already tuned for small local models) into
# Hermes' skills directory, installs a one-line bootstrap context file, and
# prints how to point Hermes at Gemma 4 via Ollama.
#
# Usage:
#   ./install-hermes.sh [options]
#
# Options:
#   --hermes-home DIR   Hermes config dir (default: $HERMES_HOME or ~/.hermes)
#   --dry-run           Show what would happen; change nothing
#   --retune            Re-run the Gemma transform on the skills before copying
#                       (requires python3; skills shipped here are already tuned)
#   --no-context        Skip installing the bootstrap context file
#   -h, --help          Show this help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DRY_RUN=0
RETUNE=0
INSTALL_CONTEXT=1

log()  { printf '  %s\n' "$*"; }
info() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*" >&2; }
run()  { if [ "$DRY_RUN" -eq 1 ]; then printf '  [dry-run] %s\n' "$*"; else eval "$*"; fi; }

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --hermes-home) HERMES_HOME="$2"; shift 2 ;;
    --dry-run)     DRY_RUN=1; shift ;;
    --retune)      RETUNE=1; shift ;;
    --no-context)  INSTALL_CONTEXT=0; shift ;;
    -h|--help)     usage ;;
    *) warn "unknown option: $1"; usage ;;
  esac
done

SKILLS_SRC="$SCRIPT_DIR/skills"
SKILLS_DST="$HERMES_HOME/skills"
CONTEXT_DST="$HERMES_HOME/context"

info "Superpowers → Hermes installer"
log "source skills : $SKILLS_SRC"
log "hermes home   : $HERMES_HOME"
[ "$DRY_RUN" -eq 1 ] && warn "dry-run: no changes will be made"
echo

# --- preflight ----------------------------------------------------------------
if [ ! -d "$SKILLS_SRC" ]; then
  warn "skills directory not found at $SKILLS_SRC"; exit 1
fi

if command -v hermes >/dev/null 2>&1; then
  log "found hermes: $(command -v hermes)"
else
  warn "hermes not found on PATH."
  warn "install it first: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash"
  warn "continuing — skills will be installed for when Hermes is present."
fi
echo

# --- optional retune ----------------------------------------------------------
if [ "$RETUNE" -eq 1 ]; then
  info "Re-tuning skills for small local models"
  if command -v python3 >/dev/null 2>&1; then
    run "python3 '$SCRIPT_DIR/lib/gemma-tune.py' '$SKILLS_SRC'"
  else
    warn "python3 not found; skipping retune (shipped skills are already tuned)"
  fi
  echo
fi

# --- install skills -----------------------------------------------------------
info "Installing skills into $SKILLS_DST"
run "mkdir -p '$SKILLS_DST'"
count=0
for dir in "$SKILLS_SRC"/*/; do
  name="$(basename "$dir")"
  log "skill: $name"
  run "rm -rf '$SKILLS_DST/$name'"
  run "cp -r '$dir' '$SKILLS_DST/$name'"
  count=$((count + 1))
done
log "installed $count skill(s)"
echo

# --- install bootstrap context file ------------------------------------------
if [ "$INSTALL_CONTEXT" -eq 1 ]; then
  info "Installing bootstrap context file"
  run "mkdir -p '$CONTEXT_DST'"
  run "cp '$SCRIPT_DIR/context/superpowers.md' '$CONTEXT_DST/superpowers.md'"
  log "wrote $CONTEXT_DST/superpowers.md"
  warn "Make sure Hermes loads this as a context file (it 'shapes every"
  warn "conversation'). Check 'hermes context' / your Hermes docs for how to"
  warn "register $CONTEXT_DST/superpowers.md, or paste its contents into your"
  warn "project/global context file (e.g. AGENTS.md / SOUL.md)."
  echo
fi

# --- verify -------------------------------------------------------------------
info "Verifying"
if [ "$DRY_RUN" -eq 0 ]; then
  if [ -f "$SKILLS_DST/using-superpowers/SKILL.md" ]; then
    log "OK: using-superpowers present"
  else
    warn "using-superpowers/SKILL.md missing — install may have failed"
  fi
  installed=$(find "$SKILLS_DST" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')
  log "skills now in $SKILLS_DST: $installed"
fi
echo

# --- next steps ---------------------------------------------------------------
info "Next steps"
cat <<EOF
  1. Point Hermes at Gemma 4 via Ollama:
       see  $SCRIPT_DIR/config/ollama-gemma.md
       quick: ollama pull gemma4 && hermes model
              (base URL http://localhost:11434/v1, model = your ollama tag)

  2. Start Hermes and confirm skills are discovered:
       hermes
       > "list your skills"          # should include using-superpowers, etc.
       > "tell me about your superpowers"

  3. Try it on a real task:
       > "let's add a small feature"  # should trigger brainstorming first

  Skills live in : $SKILLS_DST
  Tool mapping   : $SKILLS_DST/using-superpowers/references/hermes-tools.md
EOF

info "Done."
