# Hermes Tool Mapping

Superpowers skills are written with **Claude Code** tool names. Hermes exposes
the same capabilities under its own tool names. When a skill tells you to use a
tool on the left, use your Hermes tool on the right.

> **Confirm the exact names on your machine.** Hermes ships 40+ tools and names
> can vary by version. List them with `hermes tools` (or check
> `~/.hermes/` config / the Hermes docs), then adjust this table to match. The
> *capability* mapping below is correct even if a name differs.

| Skill references (Claude Code) | Capability | Hermes tool |
|--------------------------------|------------|-------------|
| `Read` | read a file | `read_file` |
| `Write` | create / overwrite a file | `write_file` |
| `Edit` | edit part of a file | `patch` / `edit_file` |
| `Bash` | run a shell command | `shell` / `bash` |
| `Grep` | search file *contents* | `search` (grep) |
| `Glob` | find files by name/pattern | `find` / `list_files` |
| `TodoWrite` | track a task checklist | Hermes task/todo tool |
| `Skill` | activate a skill | Hermes skill-activation tool |
| `Task` | dispatch a subagent | Hermes subagent spawn |
| `WebSearch` | search the web | Hermes web search |
| `WebFetch` | fetch/read a URL | Hermes fetch / browser tool |

## Subagent dispatch

Some skills (`subagent-driven-development`, `dispatching-parallel-agents`,
`requesting-code-review`) ask you to dispatch a **subagent** with a prompt.

- Hermes can **spawn isolated subagents for parallel workstreams**. Use that
  mechanism wherever a skill says `Task tool (...)`.
- The skills provide prompt **templates** with placeholders such as
  `{WHAT_WAS_IMPLEMENTED}` or `[FULL TEXT of task]`. Fill in every placeholder,
  then pass the complete text as the subagent's instructions. The template
  already contains the subagent's role and the output format it should return.
- When a skill asks for several **independent** subagents, spawn them in
  parallel. Keep dependent steps sequential.

## If a tool truly does not exist

A few skills mention capabilities Hermes may not have one-to-one (e.g. a
dedicated plan/read-only mode). If there is no equivalent:

1. Do the underlying intent with the closest tool you have, or
2. Do that step manually and say so, then continue the skill.

Never skip a skill just because one referenced tool name differs — translate it
and keep going.

## Tools Hermes adds

Hermes also provides capabilities with no Claude Code equivalent — browser
automation (navigate/click/type/screenshot), vision analysis, cross-session
memory (`MEMORY.md`), MCP servers, cron triggers. Skills won't ask for these,
but you may use them when they help the task.
