# mdconvert — files → Markdown

Convert documents and data files to Markdown (`.md`). Point it at a file or a
folder and it writes the converted Markdown next to the source (or into an
output directory).

| Format | Extensions | Output | Dependency |
|---|---|---|---|
| Plain text / Markdown | `.txt` `.text` `.log` `.md` `.markdown` | passthrough | — (stdlib) |
| CSV / TSV | `.csv` `.tsv` `.tab` | Markdown table | — (stdlib) |
| JSON | `.json` | table (list of objects) or fenced block | — (stdlib) |
| HTML | `.html` `.htm` | Markdown | — (stdlib; `markdownify` for higher fidelity) |
| Excel | `.xlsx` `.xlsm` | one table per sheet | `openpyxl` |
| PDF | `.pdf` | text + tables per page | `pdfplumber` (or `pypdf` for text-only) |
| Word | `.docx` | headings, lists, tables | `python-docx` |
| PowerPoint | `.pptx` | one section per slide | `python-pptx` |

The engine and the text/CSV/TSV/JSON/HTML converters need **nothing** beyond the
Python standard library. Office and PDF formats import their library lazily and,
if it is missing, fail with a clear `pip install ...` message.

## Install

```bash
cd python
# Optional: only needed for Excel / PDF / Word / PowerPoint
pip install -r mdconvert/requirements.txt
# ...or just the formats you use, e.g.:
pip install openpyxl pdfplumber
```

## Install as a command

```bash
cd python
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"      # adds the `mdconvert` command + every format library
```

Now `mdconvert` is on PATH (`python -m mdconvert` also works without installing).

## Use it as an agent skill

A shell-capable agent (e.g. a Hermes-style Telegram agent) can use mdconvert as a
tool: when a user uploads a file, the agent runs `mdconvert "<path>" --stdout` and
reads the Markdown from stdout. See **[SKILL.md](SKILL.md)** for a ready-to-drop
skill card and JSON tool spec.

## CLI usage

Run from the `python/` directory (or anywhere, once installed):

```bash
# One file -> report.md beside it
python -m mdconvert report.pdf

# Several files into an output directory
python -m mdconvert data.xlsx notes.docx -o build/

# Recurse a folder, mirroring its structure under ./markdown
python -m mdconvert ./inbox -r -o ./markdown

# Print to stdout instead of writing a file
python -m mdconvert report.pdf --stdout

# What can this build handle?
python -m mdconvert --list-formats
```

### Options

| Flag | Effect |
|---|---|
| `-o, --output-dir DIR` | Write `.md` files into `DIR` (mirrors folder structure for directory inputs). |
| `-r, --recursive` | Recurse into input directories. |
| `--stdout` | Print Markdown to stdout instead of writing files. |
| `--no-header` | Treat the first CSV/TSV/sheet row as data, not a header. |
| `--front-matter` | Prepend a YAML front-matter block (`title`, `source`, `converted`). |
| `--no-page-breaks` | Omit `## Page N` / `## Slide N` separators. |
| `--overwrite` | Overwrite existing `.md` files (default: skip them). |
| `-q, --quiet` | Only print errors. |

Exit codes: `0` success · `1` one or more files failed · `2` nothing to do.

## Telegram bot

Send the bot a file (as a *document*) and it replies with the converted `.md`.
It uses long polling, so it works from your laptop or the on-prem server with
no public URL or webhook.

```bash
cd python
pip install "python-telegram-bot>=20"
# plus any format extras you need, e.g. openpyxl pdfplumber python-docx python-pptx

export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."   # from @BotFather
#   Windows PowerShell:  $env:TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
#   Windows cmd:         set TELEGRAM_BOT_TOKEN=123456:ABC-DEF...

python -m mdconvert.bot
```

Then open Telegram, message your bot, and send it a file. Notes:

- **Send the file as a document**, not a compressed photo, so the bytes arrive intact.
- Telegram limits bot downloads to **20 MB** per file.
- PDF/Excel/Word/PowerPoint conversion needs the matching library installed on
  the machine running the bot (see [requirements](requirements.txt)); the bot
  replies with a clear message if one is missing.

Verify a token works without sharing it (returns your bot's info):

```bash
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"
```

### One-shot install (Linux / WSL)

From the repo's `linux/` folder:

```bash
./install-bot.sh
```

It creates a venv, installs `python-telegram-bot` (+ optional format libraries),
prompts for and validates your token, and — if your WSL has systemd — installs a
`mdconvert-bot` user service that auto-restarts and survives reboots. Without
systemd it prints how to run it manually or via Windows Task Scheduler
(`wsl.exe -- ~/.config/mdconvert/run-bot.sh`). Re-run any time; it's idempotent.

```bash
./install-bot.sh --token "123:ABC..."   # non-interactive
./install-bot.sh --no-extras            # skip PDF/Excel/Word/PowerPoint libs
systemctl --user status mdconvert-bot   # if installed as a service
journalctl --user -u mdconvert-bot -f   # follow the logs
```

### Run it always-on (Windows)

To keep the bot up across reboots without a terminal open, register it as a
Scheduled Task with the bundled installer (run from the repo's `windows\`
folder, in an elevated PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File Install-Bot-ScheduledTask.ps1
```

It prompts for the token (validated via `getMe`), stores it in the user
environment, and creates a long-running task `MdConvertBot` that starts at boot
and restarts automatically. Logs go to `%ProgramData%\MdConvertBot\logs\bot.log`.

```powershell
Start-ScheduledTask -TaskName MdConvertBot           # start now
Unregister-ScheduledTask -TaskName MdConvertBot -Confirm:$false   # remove
```

## Library usage

```python
from mdconvert import convert_file, convert_to_file, ConvertOptions

result = convert_file("report.pdf")
print(result.markdown)
for w in result.warnings:
    print("note:", w)

# Write straight to a file (dest may be a file or a directory)
convert_to_file("data.xlsx", "out/", options=ConvertOptions(has_header=True))
```

### Adding a new format

Handlers live in `converters.py` and self-register by extension:

```python
from .core import register, ConvertOptions
from pathlib import Path

@register(".rtf", description="Rich Text Format")
def convert_rtf(path: Path, options: ConvertOptions) -> str:
    ...
    return markdown
```

A handler returns either a Markdown `str` or a `ConversionResult` (when it also
wants to attach warnings). That's the only contract — every front-end (CLI,
and any future GUI / Telegram bot / web upload) goes through the same engine.

## Tests

```bash
cd python
python -m unittest discover -s tests -v
```

The suite covers the engine plus every stdlib-only converter and the CLI (no
third-party libraries required to run it).
