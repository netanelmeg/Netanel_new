---
description: Manage Claude Code plugins from registered marketplaces. Usage: /plugin <subcommand> [args]
---

You are the Claude Code **plugin manager** for this project. The user invoked `/plugin $ARGUMENTS`.

Parse `$ARGUMENTS` and execute the matching subcommand below.

---

## `marketplace add <owner/repo>`

Register a new plugin marketplace from a GitHub repository.

1. Read `.claude/marketplaces.json` (create `{}` if absent)
2. Derive name = last segment of the repo path (e.g. `ruvnet/ruflo` → `ruflo`)
3. Fetch a short description via the GitHub API or leave a placeholder
4. Append entry:
   ```json
   "<name>": {
     "source": "<owner/repo>",
     "registry": "https://github.com/<owner/repo>",
     "description": "<description>",
     "author": "<owner>",
     "addedAt": "<ISO-8601 date>"
   }
   ```
5. Write `.claude/marketplaces.json`
6. Confirm: `✅ Marketplace \`<name>\` registered from github.com/<owner/repo>`

---

## `install <plugin>@<marketplace>`

Install a plugin from a registered marketplace.

1. Parse plugin name and marketplace alias from the argument
2. Read `.claude/marketplaces.json` — error if marketplace not found
3. Read `.claude/plugins.json` (create `{}` if absent)
4. Skip silently if the plugin is already installed
5. Look up the plugin's metadata (description, version, commands) from the marketplace
6. Add record to `.claude/plugins.json`:
   ```json
   "<plugin>": {
     "marketplace": "<marketplace>",
     "version": "<version>",
     "description": "<description>",
     "commands": ["<command-names>"],
     "installedAt": "<ISO-8601 date>"
   }
   ```
7. Create command files in `.claude/commands/<command>.md` for each command the plugin provides
8. Write `.claude/plugins.json`
9. Confirm: `✅ \`<plugin>\` v<version> installed — use \`/<command>\` to activate`

---

## `list`

Display all installed plugins.

1. Read `.claude/plugins.json`
2. Output a formatted markdown table:

| Plugin | Version | Marketplace | Commands | Installed |
|--------|---------|-------------|----------|-----------|
| ruflo-core | 0.2.2 | ruflo | /ruflo-core, /sparc | 2026-06-01 |
| ... | ... | ... | ... | ... |

---

## `remove <plugin>`

Uninstall a plugin.

1. Read `.claude/plugins.json`
2. Collect the plugin's `commands` list
3. Delete `.claude/commands/<command>.md` for each listed command
4. Remove the plugin entry from `.claude/plugins.json`
5. Write `.claude/plugins.json`
6. Confirm: `🗑️ \`<plugin>\` removed`

---

## `marketplace list`

List all registered marketplaces from `.claude/marketplaces.json`.

---

Execute the subcommand for: **$ARGUMENTS**
