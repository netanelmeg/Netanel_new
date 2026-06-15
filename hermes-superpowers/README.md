# Superpowers for Hermes (Gemma 4)

A port of [obra/superpowers](https://github.com/obra/superpowers) — a software
development skills library — adapted to run on the **Hermes Agent**
(NousResearch) with a **local Gemma 4 model served via Ollama**.

Superpowers gives a coding agent proven workflows: brainstorming a spec before
coding, writing detailed plans, test-driven development, systematic debugging,
code review, and finishing a branch cleanly. The skills trigger automatically
based on what you're doing.

## What's different from upstream

Hermes natively supports the `SKILL.md` standard and auto-discovers skills in
`~/.hermes/skills/` by their `description` frontmatter — so the skills mostly
drop in. This adapter adds the Hermes/Gemma-specific pieces:

1. **Gemma-tuned skills.** Upstream skills are written for Claude/GPT-class
   models. For a smaller local model we:
   - Removed inline Graphviz (` ```dot `) decision diagrams (Gemma can't parse
     them; the decision logic is also written in prose). See `lib/gemma-tune.py`.
   - Rewrote the entry-point `using-superpowers` skill in plain, concrete steps
     instead of maximalist "1% / non-negotiable" prose, which small models
     follow poorly.
2. **Hermes tool mapping** — `skills/using-superpowers/references/hermes-tools.md`
   maps Claude Code tool names (`Read`/`Edit`/`Bash`/`Skill`/`Task`...) to
   Hermes tools.
3. **Single bootstrap context file** — `context/superpowers.md`, a short
   always-on reminder (one context file, not many — small models degrade with
   too much standing instruction).
4. **Ollama + Gemma config guide** — `config/ollama-gemma.md`.

The other 13 skills keep their original strong directives (e.g. TDD's "Iron
Law") — those clear, rigid rules *help* a small model. Only the Claude-specific
machinery (Graphviz, multi-context injection, the meta "always invoke"
maximalism) was changed.

## Layout

```
hermes-superpowers/
├── install-hermes.sh            # installer (copies skills + context, prints Ollama steps)
├── lib/gemma-tune.py            # the transform that tuned the skills (re-runnable)
├── skills/                      # 14 Gemma-tuned Superpowers skills
│   └── using-superpowers/
│       ├── SKILL.md             # hand-tuned entry point
│       └── references/hermes-tools.md
├── context/superpowers.md       # one-line bootstrap context file
├── config/ollama-gemma.md       # how to run Gemma 4 via Ollama in Hermes
└── README.md
```

## Install (on the Hermes machine)

Copy this `hermes-superpowers/` folder to the computer running Hermes, then:

```bash
cd hermes-superpowers
./install-hermes.sh            # installs into ~/.hermes/skills and ~/.hermes/context
```

Useful flags:

```bash
./install-hermes.sh --dry-run             # preview, change nothing
./install-hermes.sh --hermes-home DIR     # non-default Hermes home
./install-hermes.sh --retune              # re-run the Gemma transform (needs python3)
./install-hermes.sh --no-context          # skip the bootstrap context file
```

If Hermes isn't installed yet:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

Then point Hermes at Gemma 4 via Ollama — see [`config/ollama-gemma.md`](config/ollama-gemma.md):

```bash
ollama pull gemma4        # use the exact tag from `ollama list`
hermes model              # provider: OpenAI-compatible, base URL http://localhost:11434/v1
```

## Verify

```bash
hermes
> "list your skills"                 # should include using-superpowers + 13 more
> "tell me about your superpowers"
> "let's add a small feature"        # should activate brainstorming first
```

## Things to confirm on your machine

This adapter is built from Hermes' public docs; a couple of details vary by
Hermes version and are flagged inline:

- **Tool names** — confirm with `hermes tools` and adjust
  `skills/using-superpowers/references/hermes-tools.md` if any differ. The
  *capability* mapping is correct regardless.
- **Context-file registration** — the installer writes
  `~/.hermes/context/superpowers.md`. Confirm how your Hermes loads context
  files (`hermes context` / docs), or paste its contents into your global
  context file. Even without it, Hermes auto-discovers the skills by description.
- **Gemma tag** — use the exact name from `ollama list` everywhere.

## Updating from upstream

To refresh against a newer Superpowers release: copy the new `skills/` in, then
re-run the transform and reinstall:

```bash
python3 lib/gemma-tune.py skills        # strips diagrams, adds tool-map banner
./install-hermes.sh
```

Re-tune is idempotent. The hand-tuned `using-superpowers/SKILL.md` is skipped by
the transform — re-apply your edits there manually if upstream changes it.

## Credit & license

Superpowers © Jesse Vincent & Prime Radiant, MIT. This is an unofficial
Hermes/Gemma adaptation that preserves the upstream methodology and license.
