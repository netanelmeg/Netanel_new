# Skill: file_to_markdown

A skill for a shell-command-capable agent (e.g. your Hermes agent). It converts
an uploaded file to Markdown by shelling out to the `mdconvert` CLI and reading
the Markdown from **stdout**.

Drop the "Skill card" below into your agent's tool/skill registry (or system
prompt), adjusting `MDCONVERT` to the absolute path for your install.

---

## Skill card (give this to the agent)

**Name:** `file_to_markdown`

**Description:** Convert a document or data file to Markdown. Supports PDF,
Excel (.xlsx/.xlsm), Word (.docx), PowerPoint (.pptx), CSV, TSV, JSON, HTML, and
plain text/Markdown. Use it whenever the user uploads/sends a file and wants its
contents read, summarized, quoted, or converted to Markdown.

**When to use:**
- The user sends a document (PDF, spreadsheet, Word/PowerPoint, CSV, …) and asks
  what's in it, to summarize it, extract a table, or "convert to markdown".
- You need the textual content of an uploaded file before reasoning about it.

**Command to run:**
```bash
MDCONVERT "<ABSOLUTE_FILE_PATH>" --stdout
```
where `MDCONVERT` is the installed command, e.g.
`~/Netanel_new/python/.venv/bin/mdconvert`
(or `~/Netanel_new/python/.venv/bin/python -m mdconvert`).

**Input:** the absolute path to the file the user uploaded (your framework
usually saves it to a temp path — pass that path).

**Output contract:**
- On success: exit code `0`, the **Markdown is printed to stdout**. Read stdout.
- On failure: non-zero exit code, an error message on **stderr** (e.g. a missing
  optional library, or invalid file). Informational notes/warnings also go to
  stderr, so stdout is always clean Markdown.

**Useful flags:**
- `--stdout` — print Markdown instead of writing a `.md` file (use this).
- `--no-header` — treat the first CSV/Excel row as data, not a header.
- `--front-matter` — prepend a YAML front-matter block (title/source/date).
- `--list-formats` — print the supported extensions.

**Examples:**
```bash
# Read an uploaded PDF
~/Netanel_new/python/.venv/bin/mdconvert "/tmp/uploads/report.pdf" --stdout

# Turn a spreadsheet into Markdown tables (one per sheet)
~/Netanel_new/python/.venv/bin/mdconvert "/tmp/uploads/data.xlsx" --stdout

# A CSV whose first row is data, not a header
~/Netanel_new/python/.venv/bin/mdconvert "/tmp/uploads/rows.csv" --stdout --no-header
```

---

## JSON tool spec (if your agent registers tools with a schema)

```json
{
  "name": "file_to_markdown",
  "description": "Convert an uploaded file (PDF, Excel, Word, PowerPoint, CSV, TSV, JSON, HTML, or text) to Markdown. Returns the Markdown text.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute path to the file to convert."
      },
      "no_header": {
        "type": "boolean",
        "description": "Treat the first CSV/Excel row as data instead of a header.",
        "default": false
      }
    },
    "required": ["path"]
  }
}
```

A handler for the above just runs the command and returns stdout:
```bash
mdconvert "$path" --stdout            # + --no-header when no_header is true
```

---

## One-time setup (per machine running the agent)

```bash
cd ~/Netanel_new/python
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"     # installs the `mdconvert` command + every format library
# (or `pip install -e ".[office,pdf]"` for just the formats you need)
```

After this, `~/Netanel_new/python/.venv/bin/mdconvert` is the command the agent
calls. Text/CSV/TSV/JSON/HTML work even without the `[all]` extras; PDF and
Office formats need their libraries, and `mdconvert` will say exactly which one
to `pip install` if it's missing.
