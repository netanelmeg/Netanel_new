---
description: Ruflo RAG Memory — persistent vector memory with HNSW search, AgentDB, and semantic retrieval. Part of ruflo-rag-memory plugin.
---

You are the **Ruflo RAG Memory** assistant. The user invoked `/memory $ARGUMENTS`.

Ruflo RAG Memory provides persistent, semantically-searchable memory across sessions using HNSW vector indexing, AgentDB, and hybrid Graph RAG with MMR diversity re-ranking.

---

## Namespaces

| Namespace | Purpose |
|-----------|---------|
| `default` | General key-value storage |
| `agents` | Agent state and decisions |
| `tasks` | Task context and results |
| `sessions` | Cross-session continuity |
| `swarm` | Shared swarm memory |
| `project` | Long-lived project knowledge |
| `spec` | Specifications and requirements |
| `arch` | Architecture decisions (ADRs) |
| `impl` | Implementation notes |
| `test` | Test results and coverage |
| `debug` | Debug traces and findings |

---

## Subcommands

### `store <key> <value> [--namespace <ns>]`
Store a value with semantic indexing.

```bash
npx ruflo@latest memory store "auth_decision" "Using OAuth2 + JWT" --namespace arch
npx ruflo@latest memory store "bug_fix_123" "Root cause: null pointer in auth middleware" --namespace debug
```

### `search <query> [--namespace <ns>] [--limit <n>]`
Semantic vector search across memory.

```bash
npx ruflo@latest memory search "authentication strategy" --namespace arch --limit 5
npx ruflo@latest memory search "recent errors" --limit 10
```

### `get <key> [--namespace <ns>]`
Retrieve a specific entry by exact key.

```bash
npx ruflo@latest memory get "auth_decision" --namespace arch
```

### `list [--namespace <ns>]`
List entries in a namespace.

```bash
npx ruflo@latest memory list --namespace project
```

### `export [--file <path>]`
Export all memory to a JSON backup.

```bash
npx ruflo@latest memory export --file memory-backup.json
```

### `import <file>`
Restore memory from a backup.

```bash
npx ruflo@latest memory import memory-backup.json
```

### `clean [--namespace <ns>] [--older-than <duration>]`
Remove stale entries.

```bash
npx ruflo@latest memory clean --namespace debug --older-than 7d
```

### `stats [--namespace <ns>]`
Memory usage statistics.

```bash
npx ruflo@latest memory stats
npx ruflo@latest memory stats --namespace swarm
```

---

## MCP Tools (when ruflo MCP server is running)

```
mcp__ruflo__memory_store { key, value, namespace }
mcp__ruflo__memory_search { query, namespace, limit }
mcp__ruflo__memory_get { key, namespace }
mcp__ruflo__memory_list { namespace }
mcp__ruflo__memory_export { filepath }
mcp__ruflo__memory_stats {}
mcp__ruflo__agentdb_query { query, limit }
mcp__ruflo__hnsw_search { embedding, topK }
```

---

## RAG / Graph RAG

For retrieval-augmented generation tasks:

```bash
# Semantic similarity search (HNSW)
npx ruflo@latest memory rag-search "how does our auth flow work" --limit 5

# Graph RAG — traverse relationships
npx ruflo@latest memory graph-search "auth" --depth 2

# MMR diversity re-ranking (reduce redundancy)
npx ruflo@latest memory search "API design" --mmr --lambda 0.5
```

---

## Best Practices

- Use **descriptive, searchable keys** (e.g. `auth_jwt_decision` not `d1`)
- Include a timestamp in time-sensitive values
- Organize by namespace — keep namespaces focused
- Export regularly: `npx ruflo@latest memory export`
- Clean up stale debug/task entries periodically

---

Execute memory operation for: **$ARGUMENTS**

If no subcommand given, run `stats` and show a summary of current memory usage across all namespaces.
