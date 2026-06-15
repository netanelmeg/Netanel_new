# Running mdconvert with a local Gemma agent

Use a **locally-hosted Gemma model** (via [Ollama](https://ollama.com)) as the
brain of your agent, so file→Markdown conversion runs with **no cloud rate
limits and no cost** — exactly what bit you with Gemini's free-tier `429`s.

The `file-to-markdown` skill is model-agnostic: it shells out to the `mdconvert`
CLI, so **any** agent that can run a command works — including a small local
Gemma model. Nothing in the converter depends on a specific model.

> Tested on WSL (Ubuntu) on Windows 10; the same steps work on native Linux.

---

## 1. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start the server (skip if it's already running as a service):

```bash
ollama serve    # leave running, or: systemctl --user start ollama
```

## 2. Pull a Gemma model

```bash
ollama pull gemma3          # or gemma2 — use whatever tag is available to you
ollama run gemma3 "say hi"  # quick smoke test, then Ctrl-D
```

Pick a size that fits your machine (check available tags with `ollama list` /
the Ollama library):

| Tag (example) | Rough RAM/VRAM | Notes |
|---|---|---|
| `gemma3:1b`, `gemma2:2b` | ~2–4 GB | Fast; fine for simple tool-calling like this skill. |
| `gemma3:4b` | ~6–8 GB | Better reasoning. |
| `gemma3:12b` / `gemma2:9b` | 12 GB+ | Strong, needs a real GPU for speed. |

Smaller models have **smaller context windows** — see step 6.

## 3. Install the `mdconvert` command (the skill calls it)

```bash
cd ~/Netanel_new/python
git pull origin claude/modest-mayer-pj6oup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
mdconvert --list-formats     # verify it works
```

## 4. Install the skill

```bash
mkdir -p ~/.hermes/skills/file-to-markdown
cp ~/Netanel_new/python/mdconvert/SKILL.md ~/.hermes/skills/file-to-markdown/SKILL.md
```

(Use your actual skills directory if it isn't `~/.hermes/skills` — the same one
that holds `kanban-worker` etc.)

## 5. Point your agent at the local Gemma model

Ollama serves an **OpenAI-compatible API** at `http://localhost:11434/v1` (and
its native API at `http://localhost:11434`). Configure your agent/profile to use
that endpoint and model instead of Gemini:

- **Base URL:** `http://localhost:11434/v1`
- **Model:** `gemma3` (whatever you pulled)
- **API key:** any non-empty string (Ollama ignores it, e.g. `ollama`)

For **Hermes**, set the profile's model to the local Ollama model. Confirm the
exact syntax for your build first:

```bash
hermes -p <profile> model --help
# e.g. (verify against --help):
hermes -p <profile> model ollama/gemma3
```

…or set it in `~/.hermes/config.yaml` / `~/.hermes/.env` using the base URL,
model, and key above.

## 6. Keep output within the model's context window

Small local models choke if you paste a 50-page PDF into them. Have the agent
cap large conversions — the skill already documents this:

```bash
mdconvert "<path>" --stdout --max-chars 8000
```

`--max-chars` truncates the Markdown and appends a marker so the model knows
there's more. Tune `N` to your model (≈ 8000 chars ≈ 2–3k tokens for an
8k-context Gemma).

## 7. Test end-to-end

1. Make sure `ollama serve` is running and your agent/profile points at it.
2. Send the agent a file (e.g. a PDF) the way you normally would.
3. The agent runs `mdconvert "<path>" --stdout` and reasons over the Markdown —
   entirely on your machine, no Gemini, no `429`.

## Troubleshooting

- **`429` still appears** → the agent is still using Gemini. Re-check step 5; the
  profile's model must point at `http://localhost:11434/v1` + `gemma3`.
- **`connection refused` to 11434** → `ollama serve` isn't running.
- **Agent ignores the tool / doesn't call `mdconvert`** → small models need a
  nudge; make sure the `file-to-markdown` skill is loaded for the profile
  (`--skills file-to-markdown` or profile config) and the model is at least a
  `:4b` if a `:1b`/`:2b` keeps missing the tool.
- **Output too long / model truncates mid-thought** → lower `--max-chars`.
- **`mdconvert: command not found`** → activate the venv, or call it by absolute
  path `~/Netanel_new/python/.venv/bin/mdconvert`.

## Why local?

No Gemini free-tier `429`s, no per-call cost, and the documents never leave your
machine — useful for anything sensitive.
