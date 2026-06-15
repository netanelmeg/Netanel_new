---
name: file-to-markdown
description: Convert an uploaded or referenced file (PDF, Excel, Word, PowerPoint, CSV, TSV, JSON, HTML, or plain text) to Markdown using the mdconvert CLI. Use whenever a user sends a document and you need its contents — to read, summarize, quote, or extract a table — by running mdconvert on the file path and reading the Markdown from stdout.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [files, documents, markdown, conversion, pdf, office, csv]
---

# File → Markdown

Convert a document or data file to Markdown by shelling out to the `mdconvert`
CLI and reading the result from **stdout**. This is a single-command tool, not a
multi-step playbook: when you have a file path and need its content, run one
command.

## When to use

- A user uploads or sends a document (PDF, spreadsheet, Word, PowerPoint, CSV, …)
  and asks what's in it, to summarize it, pull a table, or "convert to markdown."
- You need the textual content of a file before reasoning about, quoting, or
  transforming it.
- A task hands you a file path and the next step needs its text.

If the input is already plain text you can read directly, you don't need this.

## The command

```bash
mdconvert "<ABSOLUTE_FILE_PATH>" --stdout
```

`mdconvert` is the installed command. On this machine it is:

```
~/Netanel_new/python/.venv/bin/mdconvert
```

(equivalently `~/Netanel_new/python/.venv/bin/python -m mdconvert`). Pass the
absolute path the upload was saved to.

## Output contract

- **Success:** exit code `0`; the **Markdown is printed to stdout** — read stdout.
- **Failure:** non-zero exit code; a human-readable reason on **stderr** (most
  often a missing optional library, e.g. `Reading .pdf requires 'pdfplumber' —
  pip install pdfplumber`, or an unreadable/corrupt file).
- Informational notes/warnings always go to **stderr**, so **stdout is always
  clean Markdown**. Capture stdout; don't merge stderr into it.

## Supported inputs

| Works with no extra libraries | Needs a library (`pip install -e ".[all]"`) |
|---|---|
| `.txt` `.md` `.log`, `.csv` `.tsv`, `.json`, `.html`/`.htm` | `.pdf`, `.xlsx`/`.xlsm`, `.docx`, `.pptx` |

Unknown extensions are read as plain text (with a note on stderr). Run
`mdconvert --list-formats` to see the live list.

## Useful flags

- `--stdout` — print Markdown instead of writing a `.md` file. **Always use this**
  when you want the text back in-band.
- `--no-header` — treat the first CSV/Excel row as data, not a header.
- `--front-matter` — prepend a YAML front-matter block (title/source/date).
- `--list-formats` — print every supported extension.

## Examples

```bash
# Read an uploaded PDF
mdconvert "/tmp/uploads/contract.pdf" --stdout

# A spreadsheet → one Markdown table per sheet
mdconvert "/tmp/uploads/q3.xlsx" --stdout

# A headerless CSV
mdconvert "/tmp/uploads/rows.csv" --stdout --no-header
```

## Pitfalls

- **Don't write a temp `.md` then read it.** Pass `--stdout` and read stdout
  directly — one command, no cleanup.
- **Capture stdout, not stderr.** Notes/warnings on stderr are not part of the
  Markdown; mixing them corrupts the output.
- **A non-zero exit with a "pip install X" message** means that format's library
  isn't installed. Install it once (see setup below) rather than retrying.
- **Use an absolute path.** Relative paths depend on the worker's cwd.
- **Large files:** conversion is local and fast, but very large PDFs/workbooks
  take proportional time — prefer running this in a worker, not a latency-
  sensitive path.

## One-time setup (per machine running the agent)

```bash
cd ~/Netanel_new/python
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"   # installs the `mdconvert` command + every format library
```

Text/CSV/TSV/JSON/HTML work even without the `[all]` extras; PDF and Office
formats need their libraries, and `mdconvert` names the exact one to install if
it's missing.
