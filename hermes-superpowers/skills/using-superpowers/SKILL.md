---
name: using-superpowers
description: Use when starting any conversation or task - establishes how to find and use skills, and requires checking for a relevant skill before writing code or giving a plan
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill and do the task you were given.
</SUBAGENT-STOP>

# Using Skills (Hermes + local model edition)

You have a library of **skills** — short playbooks for common engineering work
(planning, TDD, debugging, code review, finishing a branch, and more). When a
skill applies, it tells you the right way to do the task.

## The Core Rule

**Before you write code, give a plan, or take an action on a build/fix/change
request, check whether a skill applies. If one does, use it.**

A "task" includes questions, "quick" changes, and exploration — not just big
features. When in doubt, check. Checking is cheap; skipping a skill and doing
the work the wrong way is expensive.

If you check and no skill fits, just continue normally. You are not required to
force a skill that does not fit.

## What To Do, Step By Step

1. Read the user's message.
2. Ask yourself: *does any skill cover this kind of work?* (building, fixing,
   planning, debugging, reviewing, testing, finishing a branch...)
3. If yes: **activate that skill** (see "How To Access Skills" below) and read it.
4. Say one line out loud first, e.g. `Using test-driven-development to add the parser`.
5. If the skill has a checklist, create one todo per item and work through them in order.
6. Follow the skill's steps. Then respond / do the work.
7. If you were about to enter a plan/design and have not brainstormed yet,
   activate the **brainstorming** skill first.

## How To Access Skills (Hermes)

Hermes auto-discovers skills in `~/.hermes/skills/` by their `description`
field. To use one, **activate it with your skill tool** so its full content
loads, then follow it. Do **not** just read the SKILL.md file with a file tool —
activate it so it is treated as instructions.

## Platform Adaptation — Tool Names

These skills are written with Claude Code tool names (`Read`, `Write`, `Edit`,
`Bash`, `Grep`, `Glob`, `TodoWrite`, `Skill`, `Task`). On Hermes, map them to
your own tools using **`references/hermes-tools.md`** (in this skill's folder).
Whenever a skill names a tool you do not have, substitute the Hermes equivalent
from that table.

## Instruction Priority

When guidance conflicts, follow this order (highest first):

1. **The user's explicit instructions** — direct requests, and project context
   files (`AGENTS.md`, `SOUL.md`, `CLAUDE.md`, `GEMINI.md`). The user is in control.
2. **Superpowers skills** — these override your default behavior where they differ.
3. **Your default behavior** — lowest priority.

If a context file says "don't use TDD" and a skill says "always use TDD," follow
the user. Skills guide *how*; the user decides *whether*.

## Choosing Between Skills

- **Process skills first** (brainstorming, systematic-debugging) — they decide
  *how* to approach the task.
- **Implementation skills second** — they guide the actual work.

Examples:
- "Let's build X" → brainstorming first, then implementation.
- "Fix this bug" → systematic-debugging first, then the domain skill.

## Skill Types

- **Rigid** skills (TDD, debugging): follow them exactly — the discipline is the point.
- **Flexible** skills (patterns): adapt the principles to your situation.

Each skill says which kind it is.

## Common Rationalizations — Stop And Check

If you catch yourself thinking any of these, pause and check for a skill first:

| Thought | Reality |
|---------|---------|
| "This is just a simple question." | Questions are tasks. Check for a skill. |
| "Let me explore the code first." | A skill may tell you how to explore. Check first. |
| "I need more context before checking." | The skill check comes before clarifying questions. |
| "This is too small to need a skill." | Small tasks grow. If a skill fits, use it. |
| "I remember how this skill goes." | Skills change. Activate and read the current one. |
| "I'll just do this one thing first." | Check before doing anything on the task. |

## User Instructions Say WHAT, Not HOW

"Add X" or "Fix Y" tells you the goal. It does **not** mean skip the workflow a
skill defines. Use the skill to do it well.
