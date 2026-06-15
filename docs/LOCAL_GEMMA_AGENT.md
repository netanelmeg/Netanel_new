# Running mdconvert with a local Gemma 4 agent

Use a **locally-hosted Gemma 4 model** (via [Ollama](https://ollama.com)) as the
brain of your [Hermes Agent](https://hermes-agent.nousresearch.com), so
file→Markdown conversion runs with **no cloud rate limits and no cost** — exactly
what bit you with Gemini's free-tier `429`s.

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

## 2. Pull Gemma 4

```bash
ollama pull gemma4:12b           # Gemma 4 12B (~6.7 GB; good on a 16 GB+ machine)
ollama run gemma4:12b "say hi"   # quick smoke test, then Ctrl-D
```

Pick a size that fits your machine (`ollama list` shows what you've pulled):

| Tag | Storage | Good for |
|---|---|---|
| `gemma4:e2b`, `gemma4:e4b` | small | Low-RAM machines; fine for simple tool-calling like this skill. |
| `gemma4:12b` | ~6.7 GB | Recommended default; 16 GB+ desktop. |
| `gemma4:26b`, `gemma4:31b` | large | Strongest reasoning; needs a real GPU. |

Smaller models have **smaller context windows** — see step 6. Gemma 4 is
multimodal and a capable reasoner, which helps it call this tool reliably.

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

## 5. Point Hermes at the local Gemma model

Hermes Agent works with any **OpenAI-compatible** endpoint — exactly what Ollama
serves at `http://127.0.0.1:11434/v1`. When `base_url` is set, Hermes calls that
endpoint directly. Config is per-profile (each profile has its own
`~/.hermes/`, i.e. its own `HERMES_HOME`). Three ways to set it:

**A. Interactive picker (easiest):**
```bash
hermes -p <profile> model        # choose the Ollama / gemma4 entry
```

**B. Edit `~/.hermes/config.yaml`:**
```yaml
model:
  default: gemma4:12b
  provider: ollama
  base_url: http://127.0.0.1:11434/v1   # MUST end in /v1
```

**C. `config set` from the CLI:**
```bash
hermes -p <profile> config set model.default  gemma4:12b
hermes -p <profile> config set model.provider ollama
hermes -p <profile> config set model.base_url http://127.0.0.1:11434/v1
```

Put a dummy key in `~/.hermes/.env` — the OpenAI client requires a non-empty key,
but Ollama ignores it:
```bash
OPENAI_API_KEY=ollama
```

Gotchas (from the Hermes issue tracker):
- `base_url` **must include `/v1`** (`http://127.0.0.1:11434/v1`), or you get 404s.
- Prefer `127.0.0.1` over `localhost` if name resolution is flaky in WSL.

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
  profile's `model.base_url` must be `http://127.0.0.1:11434/v1` and `model.default`
  a Gemma 4 tag.
- **404 from the model endpoint** → `base_url` is missing the `/v1` suffix.
- **`connection refused` to 11434** → `ollama serve` isn't running.
- **Agent ignores the tool / doesn't call `mdconvert`** → make sure the
  `file-to-markdown` skill is loaded for the profile (`--skills file-to-markdown`
  or profile config); if a tiny `e2b` model keeps missing the tool, move up to
  `gemma4:e4b` or `gemma4:12b`.
- **Output too long / model truncates mid-thought** → lower `--max-chars`.
- **`mdconvert: command not found`** → activate the venv, or call it by absolute
  path `~/Netanel_new/python/.venv/bin/mdconvert`.

## Why local?

No Gemini free-tier `429`s, no per-call cost, and the documents never leave your
machine — useful for anything sensitive.

## References

- Hermes Agent — Configuration: <https://hermes-agent.nousresearch.com/docs/user-guide/configuration/>
- Hermes Agent — AI Providers: <https://hermes-agent.nousresearch.com/docs/integrations/providers>
- Hermes Agent + Ollama: <https://docs.ollama.com/integrations/hermes>
- Gemma 4 on Ollama: <https://ollama.com/library/gemma4:12b>
