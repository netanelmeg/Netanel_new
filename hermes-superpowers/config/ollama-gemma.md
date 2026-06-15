# Running Hermes on Gemma 4 via Ollama

Ollama serves an **OpenAI-compatible** API at `http://localhost:11434/v1`, so
Hermes talks to it as a local OpenAI-style provider.

> Exact config keys depend on your Hermes version. Prefer the interactive
> `hermes model` flow first; fall back to the config file only if you need to
> script it. Verify against `~/.hermes/` and the Hermes docs.

## 1. Pull Gemma 4 in Ollama

```bash
ollama pull gemma4         # use the real tag from `ollama list` / ollama.com
ollama list                # confirm the exact model name you'll reference
```

If the tag differs on your machine (e.g. `gemma4:latest`, `gemma4:12b`), use
that exact string everywhere below.

## 2. Point Hermes at Ollama

### Option A — interactive (recommended)

```bash
hermes model
```

When prompted:
- **Provider:** a local / OpenAI-compatible / custom option
- **Base URL:** `http://localhost:11434/v1`
- **API key:** any non-empty value (Ollama ignores it) — e.g. `ollama`
- **Model:** the exact tag from `ollama list` (e.g. `gemma4`)

### Option B — config file (example)

Add a provider + model to your Hermes config under `~/.hermes/`. The shape
below is illustrative — match your Hermes version's schema:

```toml
[providers.ollama]
type     = "openai"                      # OpenAI-compatible endpoint
base_url = "http://localhost:11434/v1"
api_key  = "ollama"                      # placeholder; Ollama ignores it

[model]
provider = "ollama"
name     = "gemma4"                      # exact tag from `ollama list`
```

Or, if your Hermes uses environment variables:

```bash
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_API_KEY="ollama"
export HERMES_MODEL="gemma4"
```

## 3. Verify

```bash
ollama list                              # Gemma 4 present
curl -s http://localhost:11434/v1/models # endpoint responds
hermes                                   # start Hermes, then: "what model are you using?"
```

## Notes for a small local model

- **Context window:** Gemma 4 has a smaller window than Claude. The skills are
  loaded **on demand** (only when activated), not all at once, which keeps the
  prompt small. Avoid pre-loading every skill into context.
- **Keep one context file:** this adapter injects a single short bootstrap
  (`context/superpowers.md`). Don't stack multiple large always-on context
  files — small models degrade with too much standing instruction.
- **Slower tool loops:** local inference is slower; the workflows still apply,
  just expect longer turns.
