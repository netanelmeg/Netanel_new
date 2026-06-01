---
description: Ruflo Swarm — coordinate multi-agent teams for complex tasks. Part of ruflo-swarm plugin. Usage: /swarm <objective> [--strategy <type>] [--topology <type>] [--agents <n>]
---

You are the **Ruflo Swarm Coordinator**. The user invoked `/swarm $ARGUMENTS`.

Ruflo Swarm orchestrates multi-agent teams for complex, parallel tasks using 6 topologies and 12 MCP tools.

---

## Topologies

| Topology | Description | Best For |
|----------|-------------|----------|
| `hierarchical` | Lead agent delegates to specialists | Structured projects |
| `mesh` | All agents collaborate peer-to-peer | Creative / research tasks |
| `hierarchical-mesh` | Hybrid: lead + peer collaboration | Large complex projects |
| `ring` | Agents pass work sequentially | Pipeline / staged tasks |
| `star` | Central coordinator, radiating agents | Parallel execution |
| `adaptive` | Topology shifts based on load | Unknown complexity |

---

## Strategies

| Strategy | Agents Involved |
|----------|----------------|
| `development` | Architect, developer, reviewer, tester |
| `research` | Analyst, researcher, synthesizer |
| `analysis` | Data analyst, domain expert, reporter |
| `testing` | Test writer, runner, coverage analyst |
| `optimization` | Profiler, optimizer, benchmarker |
| `maintenance` | Auditor, refactorer, documenter |

---

## Options

```
--strategy <type>    Execution strategy (default: development)
--topology <type>    Agent topology (default: hierarchical-mesh)
--agents <n>         Max concurrent agents (default: 5, max: 15)
--background         Run without blocking (timeout-free)
--parallel           Enable concurrent task processing
--monitor            Stream real-time progress
```

---

## Usage

### Via MCP (preferred)
```
mcp__ruflo__swarm_create {
  objective: "<objective>",
  strategy: "development",
  topology: "hierarchical-mesh",
  maxAgents: 5
}
```

### Via CLI (fallback)
```bash
# Basic swarm
npx ruflo@latest swarm "<objective>"

# Research strategy with mesh topology
npx ruflo@latest swarm "<objective>" --strategy research --topology mesh --agents 8

# Background (timeout-free) with monitoring
npx ruflo@latest swarm "<objective>" --strategy development --background --monitor

# Parallel execution
npx ruflo@latest swarm "<objective>" --parallel --agents 10
```

---

## MCP Tools (12 total from ruflo-swarm)

**Swarm tools:**
- `mcp__ruflo__swarm_create` — Initialize a new swarm
- `mcp__ruflo__swarm_spawn` — Spawn additional agents mid-task
- `mcp__ruflo__swarm_status` — Get swarm health and progress
- `mcp__ruflo__swarm_coordinate` — Send coordination messages

**Agent tools:**
- `mcp__ruflo__agent_create` — Create a named specialist agent
- `mcp__ruflo__agent_assign` — Assign a task to an agent
- `mcp__ruflo__agent_status` — Check an agent's state
- `mcp__ruflo__agent_list` — List all active agents
- `mcp__ruflo__agent_stop` — Gracefully stop an agent
- `mcp__ruflo__agent_message` — Send a direct message to an agent
- `mcp__ruflo__agent_memory_share` — Share memory between agents
- `mcp__ruflo__agent_worktree` — Isolate agent in a git worktree

---

## Monitor Stream

```bash
npx ruflo@latest swarm monitor   # Stream all swarm events
npx ruflo@latest swarm status    # Snapshot of current swarm
```

---

Execute swarm for: **$ARGUMENTS**

Parse any `--flags` from the arguments. If no objective given, ask the user what task they want the swarm to accomplish.
